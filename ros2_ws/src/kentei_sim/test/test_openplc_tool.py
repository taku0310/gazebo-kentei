import os
import shutil
import sqlite3

import pytest

from kentei_sim import openplc_tool

HERE = os.path.dirname(os.path.realpath(__file__))
CONFIG = os.path.join(HERE, '..', 'config', 'kentei_io.yaml')
OPENPLC_DB = os.path.join(HERE, '..', '..', '..', '..', 'third_party', 'OpenPLC_v3', 'webserver', 'openplc.db')


@pytest.fixture
def openplc_dir(tmp_path):
    if not os.path.exists(OPENPLC_DB):
        pytest.skip('OpenPLC_v3 サブモジュールがありません (git submodule update --init)')
    webserver = tmp_path / 'webserver'
    webserver.mkdir()
    (webserver / 'webserver.py').write_text('')
    shutil.copyfile(OPENPLC_DB, webserver / 'openplc.db')
    return tmp_path


def test_configure_registers_slave_device(openplc_dir):
    args = ['configure', '--openplc-dir', str(openplc_dir), '--config', CONFIG, '--polling', '20']
    openplc_tool.main(args)
    openplc_tool.main(args)  # 2 回実行しても重複登録しない

    conn = sqlite3.connect(openplc_dir / 'webserver' / 'openplc.db')
    rows = conn.execute(
        'SELECT dev_type, ip_address, ip_port, di_start, di_size, coil_start, coil_size '
        'FROM Slave_dev WHERE dev_name = "kentei_kun"').fetchall()
    assert rows == [('TCP', '127.0.0.1', 5020, 0, 9, 0, 8)]
    settings = dict(conn.execute('SELECT Key, Value FROM Settings'))
    assert settings['Start_run_mode'] == 'true'
    assert settings['Slave_polling'] == '20'

    mbconfig = (openplc_dir / 'webserver' / 'mbconfig.cfg').read_text()
    assert 'Num_Devices = "1"' in mbconfig
    assert 'Polling_Period = "20"' in mbconfig
    assert 'device0.protocol = "TCP"' in mbconfig
    assert 'device0.address = "127.0.0.1"' in mbconfig
    assert 'device0.IP_Port = "5020"' in mbconfig
    assert 'device0.Discrete_Inputs_Size = "9"' in mbconfig
    assert 'device0.Coils_Size = "8"' in mbconfig
    assert 'device0.Holding_Registers_Size = "0"' in mbconfig


def test_vars_output(capsys):
    openplc_tool.main(['vars', '--config', CONFIG])
    assert 'LS2 AT %IX101.0 : BOOL;' in capsys.readouterr().out
