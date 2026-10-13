"""仮想検定くん + OpenPLC Runtime を一括起動する.

  ros2 launch kentei_sim kentei_sim.launch.py openplc_dir:=/path/to/OpenPLC_v3 \
      program:=/path/to/kentei_sample.st

引数
  openplc_dir    OpenPLC_v3 のディレクトリ (既定: 環境変数 OPENPLC_DIR)
  config         I/O 定義 YAML (既定: kentei_sim/config/kentei_io.yaml)
  program        起動前に書き込む ST ファイル (空なら OpenPLC に登録済みのプログラムで起動)
  start_openplc  false にすると OpenPLC は起動しない (別 PC / Docker で動かす場合)
  gui            false にすると操作パネルを表示しない
  polling        OpenPLC が I/O をポーリングする周期 [ms]
  openplc_modbus_port  OpenPLC 自身の Modbus サーバのポート (一般ユーザーでも使える 5502 が既定)
"""

import os

from ament_index_python.packages import get_package_prefix, get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, EmitEvent, ExecuteProcess, LogInfo, OpaqueFunction,
                            RegisterEventHandler)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _openplc_actions(context):
    if LaunchConfiguration('start_openplc').perform(context).lower() not in ('true', '1'):
        return []
    openplc_dir = LaunchConfiguration('openplc_dir').perform(context)
    if not openplc_dir:
        raise RuntimeError('openplc_dir:=<OpenPLC_v3 のパス> を指定するか、環境変数 OPENPLC_DIR を設定してください')
    config = LaunchConfiguration('config').perform(context)
    program = LaunchConfiguration('program').perform(context)
    polling = LaunchConfiguration('polling').perform(context)
    modbus_port = LaunchConfiguration('openplc_modbus_port').perform(context)
    tool = os.path.join(get_package_prefix('kentei_sim'), 'lib', 'kentei_sim', 'kentei_openplc')

    steps = [ExecuteProcess(
        cmd=[tool, 'configure', '--openplc-dir', openplc_dir, '--config', config, '--polling', polling,
             '--modbus-port', modbus_port],
        name='openplc_configure', output='screen')]
    if program:
        steps.append(ExecuteProcess(
            cmd=[tool, 'load', '--openplc-dir', openplc_dir, program],
            name='openplc_load', output='screen'))
    steps.append(ExecuteProcess(
        cmd=[tool, 'run', '--openplc-dir', openplc_dir],
        name='openplc_runtime', output='screen', sigterm_timeout='10'))

    # configure -> (load) -> run の順に実行。途中で失敗したら止める
    actions = [steps[0]]
    for prev, nxt in zip(steps, steps[1:]):
        def on_exit(event, _ctx, nxt=nxt):
            if event.returncode != 0:
                msg = f'{event.action.name} が失敗しました (終了コード {event.returncode})'
                return [LogInfo(msg=msg), EmitEvent(event=Shutdown(reason=msg))]
            return [nxt]
        actions.append(RegisterEventHandler(OnProcessExit(target_action=prev, on_exit=on_exit)))
    return actions


def generate_launch_description():
    default_config = os.path.join(get_package_share_directory('kentei_sim'), 'config', 'kentei_io.yaml')
    config = LaunchConfiguration('config')
    return LaunchDescription([
        DeclareLaunchArgument('openplc_dir', default_value=os.environ.get('OPENPLC_DIR', '')),
        DeclareLaunchArgument('config', default_value=default_config),
        DeclareLaunchArgument('program', default_value=''),
        DeclareLaunchArgument('start_openplc', default_value='true'),
        DeclareLaunchArgument('gui', default_value='true'),
        DeclareLaunchArgument('polling', default_value='20'),
        DeclareLaunchArgument('openplc_modbus_port', default_value='5502'),

        Node(package='kentei_sim', executable='io_server', name='kentei_io_server',
             parameters=[{'config': config}], output='screen'),
        Node(package='kentei_sim', executable='panel', name='kentei_panel',
             parameters=[{'config': config}], output='screen',
             condition=IfCondition(LaunchConfiguration('gui'))),
        OpaqueFunction(function=_openplc_actions),
    ])
