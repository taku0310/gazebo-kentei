"""OpenPLC Runtime の設定・プログラム書き込み・起動を行うコマンド (kentei_openplc).

  kentei_openplc configure --openplc-dir DIR --config kentei_io.yaml
      仮想検定くんを Modbus スレーブデバイスとして登録し、RUN モード起動を有効にする
  kentei_openplc load --openplc-dir DIR program.st
      ST ファイルを OpenPLC に登録してコンパイルする (Web 画面からのアップロードと同じ)
  kentei_openplc run --openplc-dir DIR
      OpenPLC Runtime を起動する (Ctrl+C で子プロセスまでまとめて停止)
  kentei_openplc vars --config kentei_io.yaml
      ST / OpenPLC Editor に貼る変数宣言を表示する
  kentei_openplc table --config kentei_io.yaml
      I/O 対応表 (Markdown) を表示する
"""

import argparse
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time

from .io_map import load_config, markdown_table, st_var_block

DEVICE_NAME = 'kentei_kun'


def _webserver_dir(openplc_dir: str) -> str:
    path = os.path.join(os.path.abspath(os.path.expanduser(openplc_dir)), 'webserver')
    if not os.path.isfile(os.path.join(path, 'webserver.py')):
        sys.exit(f'OpenPLC_v3 が見つかりません: {openplc_dir}')
    return path


def _connect(webserver: str) -> sqlite3.Connection:
    return sqlite3.connect(os.path.join(webserver, 'openplc.db'))


def _set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute('INSERT OR REPLACE INTO Settings (Key, Value) VALUES (?, ?)', (key, value))


def write_mbconfig(conn: sqlite3.Connection, path: str) -> None:
    """OpenPLC の webserver.py generate_mbconfig() と同じ形式で mbconfig.cfg を書く."""
    settings = dict(conn.execute('SELECT Key, Value FROM Settings'))
    rows = conn.execute('SELECT * FROM Slave_dev').fetchall()
    text = f'Num_Devices = "{len(rows)}"'
    text += f'\nPolling_Period = "{settings.get("Slave_polling", "100")}"'
    text += f'\nTimeout = "{settings.get("Slave_timeout", "1000")}"'
    for i, row in enumerate(rows):
        dev = f'device{i}'
        text += f'\n# ------------\n#   DEVICE {i}\n# ------------\n'
        text += f'{dev}.name = "{row[1]}"\n{dev}.slave_id = "{row[3]}"\n'
        if str(row[2]) in ('ESP32', 'ESP8266', 'TCP'):
            text += f'{dev}.protocol = "TCP"\n{dev}.address = "{row[9]}"\n'
        else:
            port = str(row[4])
            if port.startswith('COM'):
                port = '/dev/ttyS' + str(int(port[3:]) - 1)
            text += f'{dev}.protocol = "RTU"\n{dev}.address = "{port}"\n'
        text += f'{dev}.IP_Port = "{row[10]}"\n{dev}.RTU_Baud_Rate = "{row[5]}"\n'
        text += f'{dev}.RTU_Parity = "{row[6]}"\n{dev}.RTU_Data_Bits = "{row[7]}"\n'
        text += f'{dev}.RTU_Stop_Bits = "{row[8]}"\n{dev}.RTU_TX_Pause = "{row[21]}"\n\n'
        keys = ('Discrete_Inputs', 'Coils', 'Input_Registers', 'Holding_Registers_Read', 'Holding_Registers')
        for n, key in enumerate(keys):
            text += f'{dev}.{key}_Start = "{row[11 + 2 * n]}"\n{dev}.{key}_Size = "{row[12 + 2 * n]}"\n'
    with open(path, 'w') as f:
        f.write(text)


def configure(args) -> None:
    cfg = load_config(args.config)
    webserver = _webserver_dir(args.openplc_dir)
    conn = _connect(webserver)
    with conn:
        conn.execute('DELETE FROM Slave_dev WHERE dev_name = ?', (DEVICE_NAME,))
        conn.execute(
            'INSERT INTO Slave_dev (dev_name, dev_type, slave_id, com_port, baud_rate, parity, data_bits, '
            'stop_bits, ip_address, ip_port, di_start, di_size, coil_start, coil_size, ir_start, ir_size, '
            'hr_read_start, hr_read_size, hr_write_start, hr_write_size, pause) '
            "VALUES (?, 'TCP', ?, '', 115200, 'None', 8, 1, ?, ?, 0, ?, 0, ?, 0, 0, 0, 0, 0, 0, 0)",
            (DEVICE_NAME, cfg.unit_id, args.slave_host, args.slave_port or cfg.port,
             cfg.input_size, cfg.output_size))
        _set_setting(conn, 'Slave_polling', str(args.polling))
        _set_setting(conn, 'Slave_timeout', str(args.timeout))
        _set_setting(conn, 'Start_run_mode', 'true')
        if args.modbus_port:
            _set_setting(conn, 'Modbus_port', args.modbus_port)
    write_mbconfig(conn, os.path.join(webserver, 'mbconfig.cfg'))
    conn.close()
    print(f'OpenPLC にスレーブデバイス "{DEVICE_NAME}" '
          f'({args.slave_host}:{args.slave_port or cfg.port}, 入力 {cfg.input_size} 点 / 出力 {cfg.output_size} 点, '
          f'ポーリング {args.polling} ms) を登録しました')


def load(args) -> None:
    webserver = _webserver_dir(args.openplc_dir)
    src = os.path.abspath(args.program)
    if not os.path.isfile(src):
        sys.exit(f'ST ファイルが見つかりません: {src}')
    name = os.path.basename(src)
    shutil.copyfile(src, os.path.join(webserver, 'st_files', name))
    conn = _connect(webserver)
    with conn:
        conn.execute('DELETE FROM Programs WHERE File = ?', (name,))
        conn.execute(
            'INSERT INTO Programs (Name, Description, File, Date_upload) VALUES (?, ?, ?, ?)',
            (os.path.splitext(name)[0], 'gazebo-kentei から登録', name, int(time.time())))
    conn.close()
    print(f'{name} をコンパイルしています...')
    result = subprocess.run(['bash', 'scripts/compile_program.sh', name], cwd=webserver)
    if result.returncode != 0:
        sys.exit('コンパイルに失敗しました。上のエラーメッセージを確認してください')
    print(f'{name} を OpenPLC の実行プログラムにしました')


def run(args) -> None:
    openplc_dir = os.path.abspath(os.path.expanduser(args.openplc_dir))
    _webserver_dir(openplc_dir)
    script = os.path.join(openplc_dir, 'start_openplc.sh')
    if not os.path.isfile(script):
        sys.exit(f'{script} がありません。先に scripts/setup_openplc.sh で OpenPLC をインストールしてください')
    # webserver.py が core/openplc を子プロセスで起動するので、プロセスグループごと止める
    # ハンドラは Popen より先に設定する (SIGINT が無視状態のまま子に引き継がれないように)
    stop_requested = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_requested.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_requested.set())
    proc = subprocess.Popen(['bash', script], cwd=openplc_dir, start_new_session=True)
    print('OpenPLC Runtime を起動しました (Web 画面 http://localhost:8080  ユーザー/パスワード openplc/openplc)',
          flush=True)
    while proc.poll() is None and not stop_requested.wait(0.5):
        pass
    _stop_group(proc)
    if not stop_requested.is_set():
        sys.exit(f'OpenPLC Runtime が終了しました (終了コード {proc.returncode})。上のエラーを確認してください')


def _group_alive(proc: subprocess.Popen) -> bool:
    proc.poll()  # bash がゾンビのままだとグループが残って見えるので回収する
    try:
        os.killpg(proc.pid, 0)
        return True
    except ProcessLookupError:
        return False


def _stop_group(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        if not _group_alive(proc):
            return
        print(f'OpenPLC を停止しています ({signal.Signals(sig).name})', flush=True)
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _group_alive(proc):
            time.sleep(0.1)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog='kentei_openplc', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    default_dir = os.environ.get('OPENPLC_DIR', '')

    p = sub.add_parser('configure', help='仮想検定くんを OpenPLC のスレーブデバイスとして登録')
    p.add_argument('--openplc-dir', default=default_dir, required=not default_dir)
    p.add_argument('--config', required=True)
    p.add_argument('--slave-host', default='127.0.0.1', help='I/O サーバノードの IP (既定 127.0.0.1)')
    p.add_argument('--slave-port', type=int, default=0, help='既定は YAML の modbus.port')
    p.add_argument('--polling', type=int, default=20, help='ポーリング周期 ms (既定 20)')
    p.add_argument('--timeout', type=int, default=1000, help='通信タイムアウト ms (既定 1000)')
    p.add_argument('--modbus-port', default='', help='OpenPLC 自身の Modbus サーバポート (例 5502, disabled)')
    p.set_defaults(func=configure)

    p = sub.add_parser('load', help='ST プログラムを登録してコンパイル')
    p.add_argument('--openplc-dir', default=default_dir, required=not default_dir)
    p.add_argument('program')
    p.set_defaults(func=load)

    p = sub.add_parser('run', help='OpenPLC Runtime を起動')
    p.add_argument('--openplc-dir', default=default_dir, required=not default_dir)
    p.set_defaults(func=run)

    p = sub.add_parser('vars', help='ST 用の変数宣言を表示')
    p.add_argument('--config', required=True)
    p.set_defaults(func=lambda a: print(st_var_block(load_config(a.config))))

    p = sub.add_parser('table', help='I/O 対応表を表示')
    p.add_argument('--config', required=True)
    p.set_defaults(func=lambda a: print(markdown_table(load_config(a.config))))

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
