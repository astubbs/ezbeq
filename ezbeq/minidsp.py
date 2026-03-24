import json
import logging
import math
import time
from concurrent.futures.thread import ThreadPoolExecutor
from typing import List, Optional, Union

import yaml
from autobahn.exception import Disconnected
from autobahn.twisted import WebSocketClientFactory, WebSocketClientProtocol
from plumbum import ProcessExecutionError
from twisted.internet.protocol import ReconnectingClientFactory

from ezbeq.apis.ws import WsServer
from ezbeq.catalogue import CatalogueEntry, CatalogueProvider
from ezbeq.device import InvalidRequestError, PersistentDevice, UnableToPatchDeviceError
from ezbeq import to_millis
from ezbeq.minidsp_commands import MinidspBeqCommandGenerator, tmp_file
from ezbeq.minidsp_descriptors import MinidspDescriptor, make_peq_layout, INPUT_NAME
from ezbeq.minidsp_state import MinidspState

logger = logging.getLogger('ezbeq.minidsp')


class Minidsp(PersistentDevice[MinidspState]):

    def __init__(self, name: str, config_path: str, cfg: dict, ws_server: WsServer, catalogue: CatalogueProvider):
        super().__init__(config_path, name, ws_server)
        self.__catalogue = catalogue
        self.__executor = ThreadPoolExecutor(max_workers=1)
        self.__cmd_timeout = cfg.get('cmdTimeout', 10)
        self.__ignore_retcode = cfg.get('ignoreRetcode', False)
        self.__slot_change_delay: Union[bool, int, float] = cfg.get('slotChangeDelay', False)
        self.__levels_interval = 1.0 / float(cfg.get('levelsFps', 10))
        self.__runner = cfg['make_runner'](cfg['exe'], cfg.get('options', ''))
        ws_device_id = cfg.get('wsDeviceId', None)
        ws_ip = cfg.get('wsIp', '127.0.0.1:5380')
        if ws_device_id is not None and ws_ip:
            self.__ws_client = MinidspRsClient(self, ws_ip, ws_device_id)
        else:
            self.__ws_client = None
        self.__descriptor: MinidspDescriptor = make_peq_layout(cfg)
        logger.info(f"[{name}] Minidsp descriptor is loaded.... exe is {self.__runner}")
        logger.info(yaml.dump(self.__descriptor, indent=2, default_flow_style=False, sort_keys=False))
        ws_server.factory.set_levels_provider(name, self.start_broadcast_levels)

    @property
    def device_type(self) -> str:
        return self.__class__.__name__.lower()

    def __load_state(self) -> MinidspState:
        result = self.__executor.submit(self.__read_state_from_device).result(timeout=self.__cmd_timeout)
        return result if result else MinidspState(self.name, self.__descriptor)

    def __read_state_from_device(self) -> Optional[MinidspState]:
        output = None
        try:
            kwargs = {'retcode': None} if self.__ignore_retcode else {}
            output = self.__runner['-o', 'jsonline'](timeout=self.__cmd_timeout, **kwargs)
            lines = output.splitlines()
            if lines:
                status = json.loads(lines[0])
                values = {
                    'active_slot': str(status['master']['preset'] + 1),
                    'mute': status['master']['mute'],
                    'mv': status['master']['volume']
                }
                try:
                    output = self.__runner['probe'](timeout=self.__cmd_timeout, **kwargs)
                    lines = output.splitlines()
                    serials = []
                    if lines:
                        # 0: Found 2x4HD with serial 911111 at ws://localhost/devices/0/ws [hw_id: 10, dsp_version: 100]
                        import re
                        p = re.compile(r'(?P<device_idx>\d+): Found (?P<device_type>.*) with serial (?P<serial>.*) at.*')
                        for line in lines:
                            m = p.match(line)
                            if m:
                                serials.append(m.group('serial'))
                            else:
                                logger.debug(f'[{name}] Unexpected output from probe : {line}')
                    if serials:
                        values['serials'] = serials
                except Exception as e:
                    logger.warning(f'[{self.name}] Unable to probe')
                return MinidspState(self.name, self.__descriptor, **values)
            else:
                logger.error(f"[{self.name}] No output returned from device")
        except:
            logger.exception(f"[{self.name}] Unable to parse device state {output}")
        return None

    @staticmethod
    def __as_idx(idx: Union[int, str]):
        return int(idx) - 1

    def __send_cmds(self, target_slot_idx: Optional[int], cmds: List[str]):
        return self.__executor.submit(self.__do_run, cmds, target_slot_idx, self.__slot_change_delay).result(
            timeout=self.__cmd_timeout)

    def activate(self, slot: str):
        def __do_it():
            target_slot_idx = self.__as_idx(slot)
            self.__validate_slot_idx(target_slot_idx)
            self.__send_cmds(target_slot_idx, [])
            self._current_state.activate(slot)

        self._hydrate_cache_broadcast(__do_it)

    @staticmethod
    def __validate_slot_idx(target_slot_idx):
        if target_slot_idx < 0 or target_slot_idx > 3:
            raise InvalidRequestError(f"Slot must be in range 1-4")

    def load_biquads(self, slot: str, overwrite: bool, inputs: List[int], outputs: List[int],
                     biquads: List[dict]) -> None:
        def __do_it():
            target_slot_idx = self.__as_idx(slot)
            self.__validate_slot_idx(target_slot_idx)
            cmds = MinidspBeqCommandGenerator.biquads(overwrite, inputs, outputs, biquads)
            try:
                self.__send_cmds(target_slot_idx, cmds)
                if inputs:
                    self._current_state.load(slot, 'CUSTOM')
                else:
                    self._current_state.activate(slot)
            except Exception as e:
                self._current_state.error(slot)
                raise e

        self._hydrate_cache_broadcast(__do_it)

    def send_commands(self, slot: str, inputs: List[int], outputs: List[int], commands: List[str]) -> None:
        def __do_it():
            target_slot_idx = self.__as_idx(slot)
            self.__validate_slot_idx(target_slot_idx)
            cmds = MinidspBeqCommandGenerator.commands(inputs, outputs, commands)
            try:
                self.__send_cmds(target_slot_idx, cmds)
                if inputs:
                    self._current_state.load(slot, 'CUSTOM')
                else:
                    self._current_state.activate(slot)
            except Exception as e:
                self._current_state.error(slot)
                raise e

        self._hydrate_cache_broadcast(__do_it)

    def load_filter(self, slot: str, entry: CatalogueEntry, mv_adjust: float = 0.0) -> None:
        def __do_it():
            target_slot_idx = self.__as_idx(slot)
            self.__validate_slot_idx(target_slot_idx)
            cmds = MinidspBeqCommandGenerator.filt(entry, self.__descriptor)
            try:
                self.__send_cmds(target_slot_idx, cmds)
                self._current_state.load(slot, entry.formatted_title, entry.author)
            except Exception as e:
                self._current_state.error(slot)
                raise e

        self._hydrate_cache_broadcast(__do_it)

    def clear_filter(self, slot: str) -> None:
        def __do_it():
            target_slot_idx = self.__as_idx(slot)
            self.__validate_slot_idx(target_slot_idx)
            cmds = MinidspBeqCommandGenerator.filt(None, self.__descriptor)
            beq_slots = self.__descriptor.to_allocator()
            levels = []
            handled = []
            s = beq_slots.pop()
            while s is not None:
                for c in s.channels:
                    if s.name == INPUT_NAME and c not in handled:
                        levels.extend(MinidspBeqCommandGenerator.mute(False, target_slot_idx, c, side=s.name))
                        levels.extend(MinidspBeqCommandGenerator.gain(0.0, target_slot_idx, c, side=s.name))
                        handled.append(c)
                s = beq_slots.pop()
            if levels:
                cmds.extend(levels)
            try:
                self.__send_cmds(target_slot_idx, cmds)
                self._current_state.clear(slot)
            except Exception as e:
                self._current_state.error(slot)
                raise e

        self._hydrate_cache_broadcast(__do_it)

    def mute(self, slot: Optional[str], channel: Optional[int]) -> None:
        self.__do_mute_op(slot, channel, True)

    def __do_mute_op(self, slot: Optional[str], channel: Optional[int], state: bool):
        def __do_it():
            target_channel_idx, target_slot_idx = self.__as_idxes(channel, slot)
            if target_slot_idx:
                self.__validate_slot_idx(target_slot_idx)
            cmds = MinidspBeqCommandGenerator.mute(state, target_slot_idx, target_channel_idx)
            self.__send_cmds(target_slot_idx, cmds)
            self._current_state.toggle_mute(slot, channel, state)

        self._hydrate_cache_broadcast(__do_it)

    def unmute(self, slot: Optional[str], channel: Optional[int]) -> None:
        self.__do_mute_op(slot, channel, False)

    def set_gain(self, slot: Optional[str], channel: Optional[int], gain: float) -> None:
        def __do_it():
            target_channel_idx, target_slot_idx = self.__as_idxes(channel, slot)
            cmds = MinidspBeqCommandGenerator.gain(gain, target_slot_idx, target_channel_idx)
            self.__send_cmds(target_slot_idx, cmds)
            self._current_state.gain(slot, channel, gain)

        self._hydrate_cache_broadcast(__do_it)

    def __as_idxes(self, channel, slot):
        target_slot_idx = self.__as_idx(slot) if slot else None
        target_channel_idx = self.__as_idx(channel) if channel else None
        return target_channel_idx, target_slot_idx

    def __do_run(self, config_cmds: List[str], slot: Optional[int], slot_change_delay: Union[bool, int, float]):
        if slot is not None:
            change_slot = True
            current_state = self.__read_state_from_device()
            if current_state and current_state.active_slot == str(slot + 1):
                change_slot = False
            if change_slot is True:
                if slot_change_delay:
                    self.__do_run([], slot, False)
                    if slot_change_delay is not True and slot_change_delay > 0:
                        from time import sleep
                        logger.info(f"[{self.name}] Sleeping for {slot_change_delay} seconds after config slot change")
                        sleep(slot_change_delay)
                else:
                    logger.info(
                        f"[{self.name}] Activating slot {slot}, current is {current_state.active_slot if current_state else 'UNKNOWN'}")
                    config_cmds.insert(0, MinidspBeqCommandGenerator.activate(slot))
        formatted = '\n'.join(config_cmds)
        logger.info(f"\n{formatted}")
        with tmp_file(config_cmds) as file_name:
            kwargs = {'retcode': None} if self.__ignore_retcode else {}
            exe = self.__runner['-f', file_name]
            logger.info(
                f"[{self.name}] Sending {len(config_cmds)} commands to slot {slot} using {exe} {kwargs if kwargs else ''}")
            start = time.time()
            try:
                code, stdout, stderr = exe.run(timeout=self.__cmd_timeout, **kwargs)
            except ProcessExecutionError as e:
                raise UnableToPatchDeviceError(f'minidsp cmd failed due to : {e.stderr}', False) from e
            end = time.time()
            logger.info(
                f"[{self.name}] Sent {len(config_cmds)} commands to slot {slot} in {to_millis(start, end)}ms - result is {code}")

    def _load_initial_state(self) -> MinidspState:
        return self.__load_state()

    def state(self, refresh: bool = False) -> MinidspState:
        if not self._hydrate() or refresh is True:
            new_state = self.__load_state()
            self._current_state.update_master_state(new_state.mute, new_state.master_volume)
        return self._current_state

    def _merge_state(self, loaded: MinidspState, cached: dict) -> MinidspState:
        loaded.merge_with(cached)
        return loaded

    def update(self, params: dict) -> bool:
        def __do_it() -> bool:
            any_update = False
            if 'slots' in params:
                for slot in params['slots']:
                    any_update |= self.__update_slot(slot)
            if 'mute' in params and params['mute'] != self._current_state.mute:
                if self._current_state.mute:
                    self.unmute(None, None)
                else:
                    self.mute(None, None)
                any_update = True
            if 'masterVolume' in params and not math.isclose(params['masterVolume'], self._current_state.master_volume):
                self.set_gain(None, None, params['masterVolume'])
                any_update = True
            return any_update

        return self._hydrate_cache_broadcast(__do_it)

    def __update_slot(self, slot: dict) -> bool:
        any_update = False
        current_slot = self._current_state.get_slot(slot['id'])
        if not current_slot:
            raise UnableToPatchDeviceError(f'Unknown device slot {slot["id"]}', True)
        match: Optional[CatalogueEntry] = None
        if 'entry' in slot and slot['entry']:
            match = self.__catalogue.find(slot['entry'])
            if not match:
                raise UnableToPatchDeviceError(f'Unknown catalogue entry {slot["entry"]}', True)
        if 'gains' in slot:
            for gain in slot['gains']:
                self.set_gain(current_slot.slot_id, int(gain['id']), gain['value'])
                any_update = True
        if 'mutes' in slot:
            for mute in slot['mutes']:
                if mute['value'] is True:
                    self.mute(current_slot.slot_id, int(mute['id']))
                else:
                    self.unmute(current_slot.slot_id, int(mute['id']))
                any_update = True
        if 'entry' in slot:
            if slot['entry']:
                self.load_filter(current_slot.slot_id, match)
                any_update = True
            else:
                self.clear_filter(current_slot.slot_id)
        if 'active' in slot:
            self.activate(current_slot.slot_id)
            any_update = True
        return any_update

    def levels(self) -> dict:
        return self.__executor.submit(self.__read_levels_from_device).result(timeout=self.__cmd_timeout)

    def __read_levels_from_device(self) -> dict:
        lines = None
        try:
            kwargs = {'retcode': None} if self.__ignore_retcode else {}
            start = time.time()
            lines = self.__runner['-o', 'jsonline'](timeout=self.__cmd_timeout, **kwargs)
            end = time.time()
            levels = json.loads(lines)
            ts = time.time()
            logger.info(f"{self.name},readlevels,{ts},{to_millis(start, end)}")
            return {
                'name': self.name,
                'ts': ts,
                'levels': format_levels(levels)
            }
        except:
            logger.exception(f"[{self.name}] Unable to load levels {lines}")
            return {}

    def start_broadcast_levels(self) -> None:
        if self.__ws_client is None:
            from twisted.internet import reactor
            sched = lambda: reactor.callLater(self.__levels_interval, __send)

            def __send():
                if self.ws_server.levels(self.name, self.levels()):
                    sched()

            sched()

    def on_ws_message(self, msg: dict):
        logger.debug(f"[{self.name}] Received {msg}")
        if 'master' in msg:
            master = msg['master']
            if master:
                def do_it():
                    preset = str(master['preset'] + 1)
                    mv = master['volume']
                    mute = master['mute']
                    if self._current_state.master_volume != mv:
                        self._current_state.master_volume = mv
                    if self._current_state.mute != mute:
                        self._current_state.mute = mute
                    if self._current_state.active_slot != preset:
                        self._current_state.activate(preset)

                self._hydrate_cache_broadcast(do_it)
        if 'input_levels' in msg and 'output_levels' in msg:
            self.ws_server.levels(self.name, {
                'name': self.name,
                'ts': time.time(),
                'levels': format_levels(msg)
            })


class MinidspRsClient:

    def __init__(self, listener, ip, device_id):
        ws_url = f"ws://{ip}/devices/{device_id}?levels=true&poll=true"
        logger.info(f"Listening to ws on {ws_url}")
        self.__factory = MinidspRsClientFactory(listener, device_id, url=ws_url)
        from twisted.internet.endpoints import clientFromString
        from twisted.internet import reactor
        # wsclient = clientFromString(reactor, 'unix:path=/tmp/minidsp.sock:timeout=5')
        wsclient = clientFromString(reactor, f"tcp:{ip}:timeout=5")
        self.__connector = wsclient.connect(self.__factory)

    def send(self, msg: str):
        self.__factory.broadcast(msg)


class MinidspRsProtocol(WebSocketClientProtocol):

    def onConnecting(self, transport_details):
        logger.info(f"Connecting to {transport_details}")

    def onConnect(self, response):
        logger.info(f"Connected to {response.peer}")

    def onOpen(self):
        logger.info("Connected to Minidsp")
        self.factory.register(self)

    def onClose(self, was_clean, code, reason):
        if was_clean:
            logger.info(f"Disconnected code: {code} reason: {reason}")
        else:
            logger.warning(f"UNCLEAN! Disconnected code: {code} reason: {reason}")

    def onMessage(self, payload, is_binary):
        if is_binary:
            logger.warning(f"Received {len(payload)} bytes in binary payload, ignoring")
        else:
            msg = payload.decode('utf8')
            logger.debug(f"[{self.factory.device_id}] Received {msg}")
            try:
                self.factory.listener.on_ws_message(json.loads(msg))
            except:
                logger.exception(f"[{self.factory.device_id}] Receiving unparseable message {msg}")


class MinidspRsClientFactory(WebSocketClientFactory, ReconnectingClientFactory):
    protocol = MinidspRsProtocol
    maxDelay = 5
    initialDelay = 0.5

    def __init__(self, listener, device_id, *args, **kwargs):
        super(MinidspRsClientFactory, self).__init__(*args, **kwargs)
        self.__device_id = device_id
        self.__clients: List[MinidspRsProtocol] = []
        self.listener = listener

    @property
    def device_id(self):
        return self.__device_id

    def clientConnectionFailed(self, connector, reason):
        logger.warning(f"[{self.device_id}] Client connection failed {reason} .. retrying ..")
        super().clientConnectionFailed(connector, reason)

    def clientConnectionLost(self, connector, reason):
        logger.warning(f"[{self.device_id}] Client connection failed {reason} .. retrying ..")
        super().clientConnectionLost(connector, reason)

    def register(self, client: MinidspRsProtocol):
        if client not in self.__clients:
            logger.info(f"[{self.device_id}] Registered device {client.peer}")
            self.__clients.append(client)
        else:
            logger.info(f"[{self.device_id}] Ignoring duplicate device {client.peer}")

    def unregister(self, client: MinidspRsProtocol):
        if client in self.__clients:
            logger.info(f"Unregistering device {client.peer}")
            self.__clients.remove(client)
        else:
            logger.info(f"Ignoring unregistered device {client.peer}")

    def broadcast(self, msg):
        if self.__clients:
            disconnected_clients = []
            for c in self.__clients:
                logger.info(f"[{self.device_id}] Sending to {c.peer} - {msg}")
                try:
                    c.sendMessage(msg.encode('utf8'))
                except Disconnected as e:
                    logger.exception(f"[{self.device_id}] Failed to send to {c.peer}, discarding")
                    disconnected_clients.append(c)
            for c in disconnected_clients:
                self.unregister(c)
        else:
            raise ValueError(f"No devices connected, ignoring {msg}")


def format_levels(levels: dict) -> dict:
    # quick hack for testing purposes
    # INPUT_NAME: [x + ((random() * 5) * (-1.0 if self.name == 'd1' else 1.0)) for x in msg['input_levels']],
    return {
        **{f'I{i}': v for i, v in enumerate(levels['input_levels'])},
        **{f'O{i}': v for i, v in enumerate(levels['output_levels'])}
    }
