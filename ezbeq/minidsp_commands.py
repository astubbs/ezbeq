import os
from contextlib import contextmanager
from typing import List, Optional

from ezbeq.catalogue import CatalogueEntry
from ezbeq.device import InvalidRequestError
from ezbeq.minidsp_descriptors import MinidspDescriptor, INPUT_NAME, OUTPUT_NAME, CROSSOVER_NAME


@contextmanager
def tmp_file(cmds: List[str]):
    import tempfile
    tmp_name = None
    try:
        f = tempfile.NamedTemporaryFile(mode='w+', delete=False)
        for cmd in cmds:
            f.write(cmd)
            f.write('\n')
        tmp_name = f.name
        f.close()
        yield tmp_name
    finally:
        if tmp_name:
            os.unlink(tmp_name)


class MinidspBeqCommandGenerator:

    @staticmethod
    def activate(slot: int) -> str:
        return f"config {slot}"

    @staticmethod
    def biquads(overwrite: bool, inputs: List[int], outputs: List[int], biquads: List[dict]):
        # [in|out]put <channel> peq <index> set -- <b0> <b1> <b2> <a1> <a2>
        # [in|out]put <channel> peq <index> bypass [on|off]
        cmds = []
        for side, channels in {INPUT_NAME: inputs, OUTPUT_NAME: outputs}.items():
            for channel in channels:
                for idx, bq in enumerate(biquads):
                    if bq:
                        coeffs = [bq['b0'], bq['b1'], bq['b2'], bq['a1'], bq['a2']]
                        cmds.append(MinidspBeqCommandGenerator.bq(channel - 1, idx, coeffs, side=side))
                        bypass = 'BYPASS' in bq and bq['BYPASS'] is True
                        cmds.append(MinidspBeqCommandGenerator.bypass(channel - 1, idx, bypass, side=side))
                    elif overwrite:
                        cmds.append(MinidspBeqCommandGenerator.bypass(channel - 1, idx, True, side=side))
                if overwrite:
                    for idx in range(len(biquads), 10):
                        cmds.append(MinidspBeqCommandGenerator.bypass(channel - 1, idx, True, side=side))
        return cmds

    @staticmethod
    def commands(inputs: List[int], outputs: List[int], commands: List[str]):
        cmds = []
        for side, channels in {INPUT_NAME: inputs, OUTPUT_NAME: outputs}.items():
            for channel in channels:
                for command in commands:
                    cmds.append(MinidspBeqCommandGenerator.cmd(channel - 1, command, side=side))
        return cmds

    @staticmethod
    def as_bq(f: dict, fs: str):
        if fs in f['biquads']:
            bq = f['biquads'][fs]['b'] + f['biquads'][fs]['a']
        else:
            t = f['type']
            freq = f['freq']
            gain = f['gain']
            q = f['q']
            from ezbeq.iir import PeakingEQ, LowShelf, HighShelf
            if t == 'PeakingEQ':
                f = PeakingEQ(int(fs), freq, q, gain)
            elif t == 'LowShelf':
                f = LowShelf(int(fs), freq, q, gain)
            elif t == 'HighShelf':
                f = HighShelf(int(fs), freq, q, gain)
            else:
                raise InvalidRequestError(f"Unknown filt_type {t}")
            bq = list(f.format_biquads().values())
        if len(bq) != 5:
            raise ValueError(f"Invalid coeff count {len(bq)}")
        return bq

    @staticmethod
    def filt(entry: Optional[CatalogueEntry], descriptor: MinidspDescriptor):
        # [in|out]put <channel> peq <index> set -- <b0> <b1> <b2> <a1> <a2>
        # [in|out]put <channel> peq <index> bypass [on|off]
        cmds = []
        # write filts to the inputs first then the output if it's a split device
        filters = [MinidspBeqCommandGenerator.as_bq(f, descriptor.fs) for f in entry.filters] if entry else []
        beq_slots = descriptor.to_allocator()

        def push(chs: List[int], i: int, s: str, group: Optional[int]):
            for ch in chs:
                cmds.append(MinidspBeqCommandGenerator.bq(ch, i, coeffs, s, group=group))
                cmds.append(MinidspBeqCommandGenerator.bypass(ch, i, False, s, group=group))

        idx = 0
        while idx < len(filters):
            coeffs: List[str] = filters[idx]
            slot = beq_slots.pop()
            if slot is not None:
                push(slot.channels, slot.idx, slot.name, slot.group)
            else:
                raise ValueError(f"Loaded {idx} filters but no slots remaining")
            idx += 1
        s = beq_slots.pop()
        while s is not None:
            for c in s.channels:
                cmds.append(MinidspBeqCommandGenerator.bypass(c, s.idx, True, s.name, s.group))
            s = beq_slots.pop()
        return cmds

    @staticmethod
    def bq(channel: int, idx: int, coeffs, side: str = INPUT_NAME, group: Optional[int] = None):
        is_xo = side == CROSSOVER_NAME
        addr = f"crossover {group}" if is_xo and group is not None else 'peq'
        return f"{OUTPUT_NAME if is_xo else side} {channel} {addr} {idx} set -- {' '.join(coeffs)}"

    @staticmethod
    def cmd(channel: int, cmd: str, side: str = INPUT_NAME):
        return f"{side} {channel} {cmd}"

    @staticmethod
    def bypass(channel: int, idx: int, bypass: bool, side: str = INPUT_NAME, group: Optional[int] = 0):
        is_xo = side == CROSSOVER_NAME
        addr = f"crossover {group}" if is_xo and group is not None else 'peq'
        return f"{OUTPUT_NAME if is_xo else side} {channel} {addr} {idx} bypass {'on' if bypass else 'off'}"

    @staticmethod
    def mute(state: bool, slot: Optional[int], channel: Optional[int], side: Optional[str] = INPUT_NAME):
        '''
        Generates commands to mute the configuration.
        :param state: mute if true otherwise unmute.
        :param slot: the target slot, if not set apply to the master control.
        :param channel: the channel, applicable only if slot is set, if not set apply to both input channels.
        :param side: the side, input by default.
        :return: the commands.
        '''
        state_cmd = 'on' if state else 'off'
        if slot is not None:
            cmds = []
            if channel is None:
                cmds.append(f"{side} 0 mute {state_cmd}")
                cmds.append(f"{side} 1 mute {state_cmd}")
            else:
                cmds.append(f"{side} {channel} mute {state_cmd}")
            return cmds
        else:
            return [f"mute {state_cmd}"]

    @staticmethod
    def gain(gain: float, slot: Optional[int], channel: Optional[int], side: Optional[str] = INPUT_NAME):
        '''
        Generates commands to set gain.
        :param gain: the gain to set.
        :param slot: the target slot, if not set apply to the master control.
        :param channel: the channel, applicable only if slot is set, if not set apply to both input channels.
        :param side: the side to apply the gain to, input by default.
        :return: the commands.
        '''
        if slot is not None:
            # TODO is this valid for other devices
            if not -72.0 <= gain <= 12.0:
                raise InvalidRequestError(f"{side} gain {gain:.2f} out of range (>= -72.0 and <= 12.0)")
            cmds = []
            if channel is None:
                cmds.append(f"{side} 0 gain -- {gain:.2f}")
                cmds.append(f"{side} 1 gain -- {gain:.2f}")
            else:
                cmds.append(f"{side} {channel} gain -- {gain:.2f}")
            return cmds
        else:
            if not -127.0 <= gain <= 0.0:
                raise InvalidRequestError(f"Master gain {gain:.2f} out of range (>= -127.0 and <= 0.0)")
            return [f"gain -- {gain:.2f}"]
