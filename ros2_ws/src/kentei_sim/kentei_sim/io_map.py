"""I/O 定義 (YAML) の読み込みと OpenPLC アドレスへの対応付け."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import yaml

# OpenPLC は Modbus スレーブデバイスの I/O を %IX100.0 / %QX100.0 以降に割り当てる
OPENPLC_SLAVE_BYTE_OFFSET = 100

INPUT_TYPES = ('momentary', 'alternate', 'sensor')
OUTPUT_TYPES = ('lamp', 'buzzer', 'solenoid', 'motor')


@dataclass
class Signal:
    name: str
    bit: int
    direction: str  # 'in' or 'out'
    type: str
    label: str = ''
    text: str = ''
    color: str = ''
    normally_closed: bool = False

    @property
    def openplc_address(self) -> str:
        prefix = '%IX' if self.direction == 'in' else '%QX'
        return f'{prefix}{OPENPLC_SLAVE_BYTE_OFFSET + self.bit // 8}.{self.bit % 8}'


@dataclass
class Cylinder:
    name: str
    extend_output: str
    retract_output: str = ''
    retracted_sensor: str = ''
    extended_sensor: str = ''
    stroke_time: float = 1.0


@dataclass
class IoConfig:
    host: str = '0.0.0.0'
    port: int = 5020
    unit_id: int = 1
    inputs: List[Signal] = field(default_factory=list)
    outputs: List[Signal] = field(default_factory=list)
    cylinders: List[Cylinder] = field(default_factory=list)

    @property
    def input_size(self) -> int:
        return max((s.bit for s in self.inputs), default=-1) + 1

    @property
    def output_size(self) -> int:
        return max((s.bit for s in self.outputs), default=-1) + 1

    def signal(self, name: str) -> Optional[Signal]:
        for s in self.inputs + self.outputs:
            if s.name == name:
                return s
        return None

    def by_name(self) -> Dict[str, Signal]:
        return {s.name: s for s in self.inputs + self.outputs}

    @property
    def plant_sensors(self) -> Set[str]:
        """設備モデルが自動で動かすセンサ入力の名前."""
        names = {c.retracted_sensor for c in self.cylinders} | {c.extended_sensor for c in self.cylinders}
        return names - {''}


def _parse_signals(items, direction: str, types) -> List[Signal]:
    signals = []
    for item in items or []:
        sig = Signal(
            name=str(item['name']),
            bit=int(item['bit']),
            direction=direction,
            type=str(item.get('type', types[0])),
            label=str(item.get('label', '')),
            text=str(item.get('text', item['name'])),
            color=str(item.get('color', '')),
            normally_closed=bool(item.get('normally_closed', False)),
        )
        if sig.type not in types:
            raise ValueError(f'{sig.name}: type は {types} のいずれかにしてください (指定値: {sig.type})')
        if sig.bit < 0:
            raise ValueError(f'{sig.name}: bit は 0 以上にしてください')
        signals.append(sig)
    return signals


def parse_config(data: dict) -> IoConfig:
    modbus = data.get('modbus') or {}
    cfg = IoConfig(
        host=str(modbus.get('host', '0.0.0.0')),
        port=int(modbus.get('port', 5020)),
        unit_id=int(modbus.get('unit_id', 1)),
        inputs=_parse_signals(data.get('inputs'), 'in', INPUT_TYPES),
        outputs=_parse_signals(data.get('outputs'), 'out', OUTPUT_TYPES),
    )
    for item in (data.get('plant') or {}).get('cylinders') or []:
        cfg.cylinders.append(Cylinder(
            name=str(item['name']),
            extend_output=str(item['extend_output']),
            retract_output=str(item.get('retract_output') or ''),
            retracted_sensor=str(item.get('retracted_sensor') or ''),
            extended_sensor=str(item.get('extended_sensor') or ''),
            stroke_time=float(item.get('stroke_time', 1.0)),
        ))
    _validate(cfg)
    return cfg


def _validate(cfg: IoConfig) -> None:
    names = set()
    for s in cfg.inputs + cfg.outputs:
        if s.name in names:
            raise ValueError(f'信号名 {s.name} が重複しています')
        names.add(s.name)
    for group, label in ((cfg.inputs, '入力'), (cfg.outputs, '出力')):
        bits = {}
        for s in group:
            if s.bit in bits:
                raise ValueError(f'{label}の bit {s.bit} が {bits[s.bit]} と {s.name} で重複しています')
            bits[s.bit] = s.name
    in_names = {s.name for s in cfg.inputs}
    out_names = {s.name for s in cfg.outputs}
    for c in cfg.cylinders:
        for out in filter(None, (c.extend_output, c.retract_output)):
            if out not in out_names:
                raise ValueError(f'{c.name}: 出力 {out} が outputs にありません')
        for sensor in filter(None, (c.retracted_sensor, c.extended_sensor)):
            if sensor not in in_names:
                raise ValueError(f'{c.name}: センサ {sensor} が inputs にありません')
        if c.stroke_time <= 0:
            raise ValueError(f'{c.name}: stroke_time は正の値にしてください')


def load_config(path: str) -> IoConfig:
    with open(path, encoding='utf-8') as f:
        return parse_config(yaml.safe_load(f) or {})


def st_var_block(cfg: IoConfig) -> str:
    """ST / OpenPLC Editor にそのまま貼れる変数宣言を作る."""
    lines = ['  VAR']
    for s in cfg.inputs + cfg.outputs:
        comment = ' '.join(filter(None, (s.label, s.text)))
        lines.append(f'    {s.name} AT {s.openplc_address} : BOOL; (* {comment} *)')
    lines.append('  END_VAR')
    return '\n'.join(lines)


def markdown_table(cfg: IoConfig) -> str:
    lines = ['| 信号 | 実機デバイス | OpenPLC | 種類 | 内容 |', '|---|---|---|---|---|']
    for s in cfg.inputs + cfg.outputs:
        kind = s.type + (' (b接点)' if s.normally_closed else '')
        lines.append(f'| {s.name} | {s.label} | `{s.openplc_address}` | {kind} | {s.text} |')
    return '\n'.join(lines)
