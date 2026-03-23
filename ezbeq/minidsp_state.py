from typing import List, Optional, Union

from ezbeq.device import SlotState, DeviceState
from ezbeq.minidsp_descriptors import MinidspDescriptor


class MinidspSlotState(SlotState['MinidspSlotState']):

    def __init__(self, slot_id: str, active: bool, input_channels: int, output_channels: int, slot_name: str = None):
        super().__init__(slot_id)
        self.__input_channels = input_channels
        self.__output_channels = output_channels
        self.gains = self.__make_vals(0.0)
        self.mutes = self.__make_vals(False)
        self.active = active
        self.slot_name = slot_name

    def clear(self):
        super().clear()
        self.gains = self.__make_vals(0.0)
        self.mutes = self.__make_vals(False)

    def __make_vals(self, val: Union[float, bool]) -> List[dict]:
        return [{'id': str(i + 1), 'value': val} for i in range(self.__input_channels)]

    def set_gain(self, channel: Optional[int], value: float):
        if channel is None:
            self.gains = self.__make_vals(value)
        else:
            if channel <= self.__input_channels:
                next(g for g in self.gains if g['id'] == str(channel))['value'] = value
            else:
                raise ValueError(f'Unknown channel {channel} for slot {self.slot_id}')

    def mute(self, channel: Optional[int]):
        self.__do_mute(channel, True)

    def __do_mute(self, channel: Optional[int], value: bool):
        if channel is None:
            self.mutes = self.__make_vals(value)
        else:
            if channel <= self.__input_channels:
                next(g for g in self.mutes if g['id'] == str(channel))['value'] = value
            else:
                raise ValueError(f'Unknown channel {channel} for slot {self.slot_id}')

    def unmute(self, channel: Optional[int]):
        self.__do_mute(channel, False)

    def merge_with(self, state: dict) -> None:
        super().merge_with(state)
        if 'gains' in state and len(state['gains']) == self.__input_channels:
            self.gains = []
            for i, g in enumerate(state['gains']):
                if isinstance(g, dict):
                    self.gains.append(g)
                else:
                    self.gains.append({'id': str(i+1), 'value': float(g)})
        if 'mutes' in state and len(state['mutes']) == self.__input_channels:
            self.mutes = []
            for i, m in enumerate(state['mutes']):
                if isinstance(m, dict):
                    self.mutes.append(m)
                else:
                    self.mutes.append({'id': str(i+1), 'value': bool(m)})

    def as_dict(self) -> dict:
        sup = super().as_dict()
        if self.slot_name:
            sup['name'] = self.slot_name
        return {
            **sup,
            'gains': self.gains,
            'mutes': self.mutes,
            'canActivate': True,
            'inputs': self.__input_channels,
            'outputs': self.__output_channels,
        }

    def __repr__(self):
        vals = ' '.join([f"{g['id']}: {g['value']:.2f}/{self.mutes[i]['value']}" for i, g in enumerate(self.gains)])
        return f"{super().__repr__()} - {vals}"


class MinidspState(DeviceState):

    def __init__(self, name: str, descriptor: MinidspDescriptor, **kwargs):
        self.__name = name
        self.master_volume: float = kwargs['mv'] if 'mv' in kwargs else 0.0
        self.__mute: bool = kwargs['mute'] if 'mute' in kwargs else False
        self.__active_slot: str = kwargs['active_slot'] if 'active_slot' in kwargs else ''
        self.__serials: list = kwargs['serials'] if 'serials' in kwargs else []
        self.__descriptor = descriptor
        slot_ids = [str(i + 1) for i in range(4)]
        self.__slots: List[MinidspSlotState] = [
            MinidspSlotState(c_id,
                             c_id == self.active_slot,
                             0 if not descriptor.input else len(descriptor.input.channels),
                             0 if not descriptor.output else len(descriptor.output.channels),
                             slot_name=descriptor.slot_names.get(c_id, None))
            for c_id in slot_ids
        ]

    def update_master_state(self, mute: bool, gain: float):
        self.__mute = mute
        self.master_volume = gain

    def activate(self, slot_id: str):
        self.__active_slot = slot_id
        for s in self.__slots:
            s.active = s.slot_id == slot_id

    @property
    def active_slot(self) -> str:
        return self.__active_slot

    @property
    def mute(self) -> bool:
        return self.__mute

    def load(self, slot_id: str, title: str, author: str = None):
        slot = self.get_slot(slot_id)
        slot.last = title
        slot.last_author = author
        self.activate(slot_id)

    def get_slot(self, slot_id) -> MinidspSlotState:
        return next(s for s in self.__slots if s.slot_id == slot_id)

    def clear(self, slot_id):
        slot = self.get_slot(slot_id)
        slot.unmute(None)
        slot.set_gain(None, 0.0)
        slot.last = 'Empty'
        slot.last_author = None
        self.activate(slot_id)

    def error(self, slot_id):
        slot = self.get_slot(slot_id)
        slot.last = 'ERROR'
        slot.last_author = None
        self.activate(slot_id)

    def gain(self, slot_id: Optional[str], channel: Optional[int], gain: float):
        if slot_id is None:
            self.master_volume = gain
        else:
            self.get_slot(slot_id).set_gain(channel, gain)
            self.activate(slot_id)

    def toggle_mute(self, slot_id: Optional[str], channel: Optional[int], mute: bool):
        if slot_id is None:
            self.__mute = mute
        else:
            slot = self.get_slot(slot_id)
            if mute:
                slot.mute(channel)
            else:
                slot.unmute(channel)
            self.activate(slot_id)

    def serialise(self) -> dict:
        serials = {'serials': self.__serials} if self.__serials else {}
        return {
            'type': 'minidsp',
            'name': self.__name,
            'masterVolume': self.master_volume,
            'mute': self.__mute,
            'slots': [s.as_dict() for s in self.__slots],
        } | serials

    def merge_with(self, cached: dict) -> None:
        saved_slots_by_id = {v['id']: v for v in cached.get('slots', [])}
        current_slots_by_id = {s.slot_id: s for s in self.__slots}
        if saved_slots_by_id.keys() == current_slots_by_id.keys():
            for slot_id, state in saved_slots_by_id.items():
                current_slots_by_id[slot_id].merge_with(state)
