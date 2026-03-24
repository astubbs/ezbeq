from typing import List, Optional, Union

INPUT_NAME = 'input'
OUTPUT_NAME = 'output'
CROSSOVER_NAME = 'crossover'


def zero_til(count: int) -> List[int]:
    return list(range(0, count))


class PeqRoutes:
    def __init__(self, name: str, biquads: int, channels: List[int], beq_slots: List[int], groups: List[int] = None):
        self.name = name
        self.biquads = biquads
        self.channels = channels
        self.beq_slots = beq_slots
        self.groups = groups

    @property
    def takes_beq(self) -> bool:
        return self.channels and len(self.channels) > 0 and self.beq_slots and len(self.beq_slots) > 0

    def __repr__(self):
        return f"{self.name}"

    def __eq__(self, o: object) -> bool:
        if isinstance(o, PeqRoutes):
            same = self.name == o.name and self.biquads == o.biquads and self.channels == o.channels and self.beq_slots == o.beq_slots
            if same:
                return (self.groups is None and o.groups is None) or (
                        self.groups is not None and self.groups == o.groups)
            return same
        return NotImplemented


class BeqFilterSlot:

    def __init__(self, name: str, idx: int, channels: List[int], group: Optional[int] = None):
        self.name = name
        self.idx = idx
        self.channels = channels
        self.group = group

    def __repr__(self):
        return f"{self.name}{self.group if self.group is not None else ''}/{self.idx}/{self.channels}"


class BeqFilterAllocator:

    def __init__(self, routes: List[PeqRoutes]):
        self.slots = []
        for r in routes:
            if r and r.takes_beq:
                for s in r.beq_slots:
                    if r.groups:
                        for g in r.groups:
                            self.slots.append(BeqFilterSlot(r.name, s, r.channels, g))
                    else:
                        self.slots.append(BeqFilterSlot(r.name, s, r.channels))

    def pop(self) -> Optional[BeqFilterSlot]:
        if self.slots:
            return self.slots.pop(0)
        return None

    def __len__(self):
        return len(self.slots)

    def __repr__(self):
        return f"{self.slots}"


class MinidspDescriptor:

    def __init__(self, name: str, fs: str, i: Optional[PeqRoutes] = None, xo: Optional[PeqRoutes] = None,
                 o: Optional[PeqRoutes] = None, extra: List[PeqRoutes] = None, slot_names: dict[str, str] = None):
        self.name = name
        self.fs = str(int(fs))
        self.input = i
        self.crossover = xo
        self.output = o
        self.extra = extra
        self.slot_names = slot_names if slot_names else {}

    @property
    def peq_routes(self) -> List[PeqRoutes]:
        return [x for x in [self.input, self.crossover, self.output] if x] + (
            [x for x in self.extra] if self.extra else [])

    def to_allocator(self) -> BeqFilterAllocator:
        return BeqFilterAllocator(self.peq_routes)

    def __repr__(self):
        s = f"{self.name}, fs:{self.fs}"
        if self.input:
            s = f"{s}, inputs: {self.input}"
        if self.crossover:
            s = f"{s}, crossovers: {self.crossover}"
        if self.output:
            s = f"{s}, outputs: {self.output}"
        if self.slot_names:
            s = f"{s}, slot_names: {self.slot_names}"
        return s


class Minidsp24HD(MinidspDescriptor):

    def __init__(self, slot_names: dict[str, str] = None):
        super().__init__('2x4HD',
                         '96000',
                         i=PeqRoutes(INPUT_NAME, 10, zero_til(2), zero_til(10)),
                         xo=PeqRoutes(CROSSOVER_NAME, 4, zero_til(4), [], groups=zero_til(2)),
                         o=PeqRoutes(OUTPUT_NAME, 10, zero_til(4), []),
                         slot_names=slot_names)


class Minidsp812CDSP(MinidspDescriptor):

    def __init__(self, slot_names: dict[str, str] = None):
        super().__init__('8x12CDSP',
                         '192000',
                         i=PeqRoutes(INPUT_NAME, 10, zero_til(6), zero_til(10)),
                         xo=PeqRoutes(CROSSOVER_NAME, 4, zero_til(12), [], groups=zero_til(2)),
                         o=PeqRoutes(OUTPUT_NAME, 10, zero_til(12), []),
                         slot_names=slot_names)


class MinidspDDRC24(MinidspDescriptor):

    def __init__(self, slot_names: dict[str, str] = None):
        super().__init__('DDRC24',
                         '48000',
                         xo=PeqRoutes(CROSSOVER_NAME, 4, zero_til(4), [], zero_til(2)),
                         o=PeqRoutes(OUTPUT_NAME, 10, zero_til(4), zero_til(10)),
                         slot_names=slot_names)


class MinidspHTX(MinidspDescriptor):

    def __init__(self, slot_names: dict[str, str] = None, sw_channels: List[int] = None):
        c = sw_channels if sw_channels is not None else [3]
        if any(ch for ch in c if ch < 0 or ch > 7):
            raise ValueError(f"Invalid channels {c} must be between 0 and 7")
        non_sw = [c1 for c1 in zero_til(8) if c1 not in c]
        super().__init__('HTX',
                         '48000',
                         xo=PeqRoutes(CROSSOVER_NAME, 8, zero_til(8), [], zero_til(2)),
                         o=PeqRoutes(OUTPUT_NAME, 10, c, zero_til(10)),
                         extra=[PeqRoutes(OUTPUT_NAME, 10, non_sw, []) if non_sw else None],
                         slot_names=slot_names)


class MinidspDDRC88(MinidspDescriptor):

    def __init__(self, slot_names: dict[str, str] = None, sw_channels: List[int] = None):
        c = sw_channels if sw_channels is not None else [3]
        if any(ch for ch in c if ch < 0 or ch > 7):
            raise ValueError(f"Invalid channels {c} must be between 0 and 7")
        non_sw = [c1 for c1 in zero_til(8) if c1 not in c]
        super().__init__('DDRC88',
                         '48000',
                         xo=PeqRoutes(CROSSOVER_NAME, 8, zero_til(8), [], zero_til(2)),
                         o=PeqRoutes(OUTPUT_NAME, 10, c, zero_til(10)),
                         extra=[PeqRoutes(OUTPUT_NAME, 10, non_sw, []) if non_sw else None],
                         slot_names=slot_names)


class Minidsp410(MinidspDescriptor):

    def __init__(self, slot_names: dict[str, str] = None):
        super().__init__('4x10',
                         '96000',
                         i=PeqRoutes(INPUT_NAME, 5, zero_til(2), zero_til(5)),
                         o=PeqRoutes(OUTPUT_NAME, 5, zero_til(8), zero_til(5)),
                         slot_names=slot_names)


class Minidsp1010(MinidspDescriptor):

    def __init__(self, use_xo: Union[bool, int, str], slot_names: dict[str, str] = None):
        if use_xo is True:
            secondary = {'xo': PeqRoutes(CROSSOVER_NAME, 4, zero_til(8), zero_til(4), groups=[0])}
        elif use_xo is False:
            secondary = {'o': PeqRoutes(OUTPUT_NAME, 6, zero_til(8), zero_til(4))}
        elif use_xo == '0' or use_xo == '1':
            secondary = {'xo': PeqRoutes(CROSSOVER_NAME, 4, zero_til(8), zero_til(4), groups=[int(use_xo)])}
        elif use_xo == 0 or use_xo == 1:
            secondary = {'xo': PeqRoutes(CROSSOVER_NAME, 4, zero_til(8), zero_til(4), groups=[use_xo])}
        elif use_xo == 'all':
            secondary = {'xo': PeqRoutes(CROSSOVER_NAME, 4, zero_til(8), zero_til(4), groups=zero_til(2))}
        else:
            secondary = {'o': PeqRoutes(OUTPUT_NAME, 6, zero_til(8), zero_til(4))}
        super().__init__('10x10',
                         '48000',
                         i=PeqRoutes(INPUT_NAME, 6, zero_til(8), zero_til(6)),
                         slot_names=slot_names,
                         **secondary)


def make_peq_layout(cfg: dict) -> MinidspDescriptor:
    slot_names: dict[str, str] = {str(k): str(v) for k, v in cfg.get('slotNames', {}).items()}
    if 'device_type' in cfg:
        device_type = cfg['device_type']
        if device_type == '24HD':
            return Minidsp24HD(slot_names=slot_names)
        elif device_type == '8x12CDSP':
            return Minidsp812CDSP(slot_names=slot_names)
        elif device_type == 'DDRC24':
            return MinidspDDRC24(slot_names=slot_names)
        elif device_type == 'DDRC88':
            return MinidspDDRC88(sw_channels=cfg.get('sw_channels', None), slot_names=slot_names)
        elif device_type == '4x10':
            return Minidsp410(slot_names=slot_names)
        elif device_type == '10x10':
            return Minidsp1010(cfg.get('use_xo', False), slot_names=slot_names)
        elif device_type == 'SHD':
            return MinidspDDRC24(slot_names=slot_names)
        elif device_type == 'HTx':
            return MinidspHTX(sw_channels=cfg.get('sw_channels', None), slot_names=slot_names)
    elif 'descriptor' in cfg:
        desc: dict = cfg['descriptor']
        named_args = ['name', 'fs', 'routes']
        missing_keys = [x for x in named_args if x not in desc.keys()]
        if missing_keys:
            raise ValueError(f"Custom descriptor is missing keys - {missing_keys} - from {desc}")
        routes: List[dict] = desc['routes']

        def make_route(r: dict) -> PeqRoutes:
            r_named_args = ['name', 'biquads', 'channels', 'slots']
            missing_route_keys = [x for x in r_named_args if x not in r.keys()]
            if missing_route_keys:
                raise ValueError(f"Custom PeqRoutes is missing keys - {missing_route_keys} - from {r}")

            def to_ints(v):
                return [int(i) for i in v] if v else None

            return PeqRoutes(r['name'], int(r['biquads']), to_ints(r['channels']), to_ints(r['slots']),
                             to_ints(r.get('groups', None)))

        routes_by_name = {}
        extra = []
        for r in routes:
            route = make_route(r)
            if route.name == 'input':
                if 'i' in routes_by_name:
                    extra.append(route)
                else:
                    routes_by_name['i'] = route
            elif route.name == 'output':
                if 'o' in routes_by_name:
                    extra.append(route)
                else:
                    routes_by_name['o'] = route
            elif route.name == 'xo' or route.name == CROSSOVER_NAME:
                if 'xo' in routes_by_name:
                    extra.append(route)
                else:
                    routes_by_name['xo'] = route
            else:
                extra.append(route)
        if extra:
            routes_by_name['extra'] = extra
        return MinidspDescriptor(desc['name'], str(desc['fs']), **routes_by_name, slot_names=slot_names)
    else:
        return Minidsp24HD(slot_names=slot_names)
