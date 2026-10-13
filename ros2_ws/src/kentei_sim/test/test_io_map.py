import os
import re

import pytest

from kentei_sim.io_map import load_config, markdown_table, parse_config, st_var_block

CONFIG = os.path.join(os.path.dirname(__file__), '..', 'config', 'kentei_io.yaml')


def test_default_config_loads():
    cfg = load_config(CONFIG)
    assert cfg.port == 5020
    assert cfg.input_size == 9
    assert cfg.output_size == 8
    assert cfg.signal('PB1').openplc_address == '%IX100.0'
    assert cfg.signal('LS2').openplc_address == '%IX101.0'
    assert cfg.signal('SOL1').openplc_address == '%QX100.7'
    assert cfg.signal('EMG').normally_closed
    assert cfg.cylinders[0].extended_sensor == 'LS2'


def test_var_block_and_table():
    cfg = load_config(CONFIG)
    block = st_var_block(cfg)
    assert 'PB1 AT %IX100.0 : BOOL;' in block
    assert 'SOL1 AT %QX100.7 : BOOL;' in block
    assert '`%IX101.0`' in markdown_table(cfg)


def test_sample_program_matches_config():
    """サンプル ST の AT 指定が YAML の割り当てと一致していること."""
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', '..', '..', '..',
                        'plc_programs', 'kentei_sample.st')
    if not os.path.exists(path):
        pytest.skip('plc_programs/kentei_sample.st が見つかりません')
    cfg = load_config(CONFIG)
    st = open(path, encoding='utf-8').read()
    for s in cfg.inputs + cfg.outputs:
        assert re.search(rf'\b{s.name}\s+AT\s+{re.escape(s.openplc_address)}\s', st), s.name


@pytest.mark.parametrize('data, message', [
    ({'inputs': [{'name': 'A', 'bit': 0}, {'name': 'A', 'bit': 1}]}, '重複'),
    ({'inputs': [{'name': 'A', 'bit': 0}, {'name': 'B', 'bit': 0}]}, 'bit 0'),
    ({'inputs': [{'name': 'A', 'bit': 0, 'type': 'lamp'}]}, 'type'),
    ({'outputs': [{'name': 'Y', 'bit': 0}],
      'plant': {'cylinders': [{'name': 'C', 'extend_output': 'NONE'}]}}, 'NONE'),
])
def test_invalid_config(data, message):
    with pytest.raises(ValueError, match=message):
        parse_config(data)
