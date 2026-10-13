#!/usr/bin/env python3
"""kentei_sample.st の動作を自動で確認するスクリプト.

OpenPLC と kentei_sim を起動した状態で実行する:
  ros2 launch kentei_sim kentei_sim.launch.py program:=$PWD/plc_programs/kentei_sample.st
  python3 plc_programs/check_kentei_sample.py

ROS 2 トピック経由でボタンを操作し、ランプ等が仕様どおりに変化するかを判定する。
自分のプログラム用に、下の scenario() を書き換えて使える。
"""

import sys
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool

LATCHED = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
SIGNALS = ['PB1', 'PB2', 'PB3', 'PB4', 'SS1', 'SS2', 'EMG', 'LS1', 'LS2',
           'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'BZ', 'SOL1']


class Checker(Node):
    def __init__(self):
        super().__init__('kentei_checker')
        self.state = {}
        self.connected = False
        self.pubs = {}
        self.failures = 0
        for name in SIGNALS:
            self.create_subscription(Bool, f'kentei/state/{name}',
                                     lambda m, n=name: self.state.__setitem__(n, m.data), LATCHED)
        self.create_subscription(Bool, 'kentei/plc_connected',
                                 lambda m: setattr(self, 'connected', m.data), LATCHED)

    def set(self, name: str, value: bool) -> None:
        if name not in self.pubs:
            self.pubs[name] = self.create_publisher(Bool, f'kentei/cmd/{name}', 10)
            time.sleep(0.3)  # 接続待ち
        self.pubs[name].publish(Bool(data=value))

    def press(self, name: str, hold: float = 0.2) -> None:
        self.set(name, True)
        time.sleep(hold)
        self.set(name, False)

    def wait_for(self, desc: str, cond, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond(self.state):
                print(f'  OK   {desc}')
                return True
            time.sleep(0.02)
        on = sorted(k for k, v in self.state.items() if v)
        print(f'  NG   {desc}  (ON の信号: {", ".join(on) or "なし"})')
        self.failures += 1
        return False

    def expect(self, desc: str, **expected) -> bool:
        return self.wait_for(desc, lambda s: all(s.get(k) == v for k, v in expected.items()), 1.0)


def scenario(c: Checker) -> None:
    print('[1] 初期状態')
    c.expect('停止ランプ L2 点灯・シリンダ後退端', L1=False, L2=True, LS1=True, SOL1=False)

    print('[2] 手動運転 (SS1 OFF)')
    c.press('PB1')
    c.expect('PB1 で運転 L1 点灯', L1=True, L2=False)
    c.set('PB3', True)
    c.expect('PB3 押下中は SOL1 / L3', SOL1=True, L3=True)
    c.wait_for('前進端 LS2 に到達', lambda s: s.get('LS2'), 3.0)
    c.set('PB3', False)
    c.wait_for('PB3 を離すと後退端 LS1 に戻る', lambda s: s.get('LS1') and not s.get('SOL1'), 3.0)
    c.press('PB2')
    c.expect('PB2 で停止', L1=False, L2=True)

    print('[3] 自動運転 (SS1 ON) 3 サイクル')
    c.set('SS1', True)
    c.press('PB1')
    c.expect('運転開始', L1=True)
    c.wait_for('L4 が点滅する', lambda s: s.get('L4'), 1.0)
    for i in range(1, 4):
        c.wait_for(f'{i} 回目 前進端', lambda s: s.get('LS2'), 4.0)
        c.wait_for(f'{i} 回目 後退端', lambda s: s.get('LS1') and not s.get('SOL1'), 5.0)
    c.wait_for('3 サイクルで完了 L5 + ブザー', lambda s: s.get('L5') and s.get('BZ') and not s.get('L1'), 2.0)
    c.wait_for('ブザーは 1 秒で止まる', lambda s: not s.get('BZ'), 2.0)
    c.set('SS1', False)

    print('[4] 非常停止')
    c.press('PB1')
    c.expect('運転開始', L1=True)
    c.set('EMG', True)
    c.expect('非常停止で運転停止・ブザー', L1=False, BZ=True)
    c.wait_for('L6 点滅', lambda s: s.get('L6'), 1.0)
    c.set('EMG', False)
    c.expect('非常停止解除でブザー停止', BZ=False)


def main() -> int:
    rclpy.init()
    c = Checker()
    threading.Thread(target=rclpy.spin, args=(c,), daemon=True).start()
    if not c.wait_for('OpenPLC 接続', lambda _s: c.connected, 30.0):
        return 1
    try:
        scenario(c)
    finally:
        print('結果:', '合格' if c.failures == 0 else f'NG {c.failures} 件')
        rclpy.shutdown()
    return 1 if c.failures else 0


if __name__ == '__main__':
    sys.exit(main())
