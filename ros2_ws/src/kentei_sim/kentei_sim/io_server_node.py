"""仮想検定くん I/O サーバノード.

OpenPLC から見ると Modbus/TCP のリモート I/O、ROS 2 から見るとトピックの集まり。

  購読  kentei/cmd/<入力名>    std_msgs/Bool  操作 (押した=True)。b接点の反転はここで行う
  配信  kentei/state/<信号名>  std_msgs/Bool  PLC が見ている入力値 / PLC からの出力値
        kentei/plant/<設備名>/position  std_msgs/Float32  シリンダ位置 0.0〜1.0
        kentei/plc_connected   std_msgs/Bool  OpenPLC からのポーリングが届いているか
"""

import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool, Float32

from .io_map import load_config
from .modbus_slave import BitStore, ModbusTcpSlave
from .plant import Plant

LATCHED = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
PLC_TIMEOUT = 1.0


class IoServerNode(Node):
    def __init__(self):
        super().__init__('kentei_io_server')
        config_path = self.declare_parameter('config', '').value
        if not config_path:
            raise RuntimeError('パラメータ config (I/O 定義 YAML のパス) を指定してください')
        self.cfg = load_config(config_path)
        host = self.declare_parameter('modbus_host', self.cfg.host).value
        port = int(self.declare_parameter('modbus_port', self.cfg.port).value)
        period = float(self.declare_parameter('update_period', 0.01).value)

        self.store = BitStore(self.cfg.input_size, self.cfg.output_size)
        self.plant = Plant(self.cfg.cylinders)
        plant_sensors = {c.retracted_sensor for c in self.cfg.cylinders}
        plant_sensors |= {c.extended_sensor for c in self.cfg.cylinders}
        self.plant_sensors = plant_sensors - {''}

        # 未操作の状態で初期化。b接点は操作していない時に ON
        for s in self.cfg.inputs:
            self.store.set_input(s.bit, s.normally_closed)

        self.state_pubs = {}
        for s in self.cfg.inputs + self.cfg.outputs:
            self.state_pubs[s.name] = self.create_publisher(Bool, f'kentei/state/{s.name}', LATCHED)
        for s in self.cfg.inputs:
            self.create_subscription(
                Bool, f'kentei/cmd/{s.name}', lambda msg, sig=s: self._on_cmd(sig, msg.data), 10)
        self.pos_pubs = {
            c.name: self.create_publisher(Float32, f'kentei/plant/{c.name}/position', 10)
            for c in self.cfg.cylinders
        }
        self.conn_pub = self.create_publisher(Bool, 'kentei/plc_connected', LATCHED)

        self.server = ModbusTcpSlave(self.store, host, port, self.cfg.unit_id)
        self.server.start()
        self.get_logger().info(
            f'Modbus/TCP スレーブ待受 {host}:{port} (unit {self.cfg.unit_id}) '
            f'入力 {self.cfg.input_size} 点 / 出力 {self.cfg.output_size} 点')

        self.published = {}
        self.connected = None
        self.last_time = time.monotonic()
        self.create_timer(period, self._update)

    def _on_cmd(self, sig, value: bool) -> None:
        if sig.name in self.plant_sensors:
            self.get_logger().warn(f'{sig.name} は設備モデルが動かすセンサのため手動操作は無視します')
            return
        self.store.set_input(sig.bit, bool(value) != sig.normally_closed)

    def _update(self) -> None:
        now = time.monotonic()
        dt, self.last_time = now - self.last_time, now

        coils = self.store.coils()
        outputs = {s.name: coils[s.bit] for s in self.cfg.outputs}
        for name, value in self.plant.step(dt, outputs).items():
            self.store.set_input(self.cfg.signal(name).bit, value)
        for name, pos in self.plant.positions().items():
            if self.published.get(('pos', name)) != pos:
                self.published[('pos', name)] = pos
                self.pos_pubs[name].publish(Float32(data=float(pos)))

        inputs = self.store.inputs()
        values = dict(outputs)
        values.update({s.name: inputs[s.bit] for s in self.cfg.inputs})
        for name, value in values.items():
            if self.published.get(name) != value:
                self.published[name] = value
                self.state_pubs[name].publish(Bool(data=value))

        connected = now - self.server.last_request < PLC_TIMEOUT
        if connected != self.connected:
            self.connected = connected
            self.conn_pub.publish(Bool(data=connected))
            if connected:
                self.get_logger().info('OpenPLC からのポーリングを受信しました')
            else:
                self.get_logger().warn('OpenPLC からのポーリングがありません (起動待ち / 設定を確認)')

    def destroy_node(self):
        self.server.stop()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = IoServerNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
