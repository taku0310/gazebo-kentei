"""仮想検定くん 操作パネル (tkinter GUI).

押しボタン・スイッチを操作すると kentei/cmd/<入力名> を配信し、
kentei/state/<信号名> を購読してランプやセンサの状態を表示する。
"""

import threading
import tkinter as tk

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool, Float32

from .io_map import load_config

LATCHED = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)

LAMP_COLORS = {
    'red': '#ff3b30', 'green': '#34c759', 'orange': '#ff9500', 'yellow': '#ffd60a',
    'white': '#f2f2f7', 'blue': '#0a84ff',
}
OFF_COLOR = '#3a3a3c'
BG = '#1c1c1e'
FG = '#f2f2f7'
SUB_FG = '#98989d'
FONT = ('Noto Sans CJK JP', 11)
SMALL = ('Noto Sans CJK JP', 9)


class PanelNode(Node):
    def __init__(self):
        super().__init__('kentei_panel')
        self.cfg = load_config(self.declare_parameter('config', '').value)
        self.state = {}
        self.positions = {}
        self.connected = False
        self.cmd_pubs = {
            s.name: self.create_publisher(Bool, f'kentei/cmd/{s.name}', 10) for s in self.cfg.inputs
        }
        for s in self.cfg.inputs + self.cfg.outputs:
            self.create_subscription(
                Bool, f'kentei/state/{s.name}',
                lambda msg, name=s.name: self.state.__setitem__(name, msg.data), LATCHED)
        for c in self.cfg.cylinders:
            self.create_subscription(
                Float32, f'kentei/plant/{c.name}/position',
                lambda msg, name=c.name: self.positions.__setitem__(name, msg.data), 10)
        self.create_subscription(
            Bool, 'kentei/plc_connected', lambda msg: setattr(self, 'connected', msg.data), LATCHED)

    def send(self, name: str, value: bool) -> None:
        self.cmd_pubs[name].publish(Bool(data=value))


class PanelApp:
    def __init__(self, node: PanelNode):
        self.node = node
        cfg = node.cfg
        self.root = tk.Tk()
        self.root.title('仮想検定くん')
        self.root.configure(bg=BG)

        self.status = tk.Label(self.root, font=FONT, bg=BG, anchor='w')
        self.status.grid(row=0, column=0, columnspan=2, sticky='we', padx=12, pady=(10, 4))

        in_frame = self._frame('入力 (操作 → PLC)', 0)
        out_frame = self._frame('出力 (PLC → 表示)', 1)

        plant_sensors = {c.retracted_sensor for c in cfg.cylinders} | {c.extended_sensor for c in cfg.cylinders}
        self.input_leds = {}
        self.toggles = {}
        for row, s in enumerate(cfg.inputs):
            led = self._led(in_frame, row, s)
            self.input_leds[s.name] = led
            if s.type == 'momentary':
                btn = tk.Button(in_frame, text=s.text, width=18, font=FONT)
                btn.bind('<ButtonPress-1>', lambda _e, n=s.name: node.send(n, True))
                btn.bind('<ButtonRelease-1>', lambda _e, n=s.name: node.send(n, False))
            elif s.name in plant_sensors:
                btn = tk.Label(in_frame, text=s.text + ' (自動)', font=FONT, bg=BG, fg=SUB_FG, anchor='w')
            else:
                var = tk.BooleanVar(value=False)
                self.toggles[s.name] = var
                btn = tk.Checkbutton(
                    in_frame, text=s.text, variable=var, indicatoron=False, width=18, font=FONT,
                    selectcolor='#0a84ff', command=lambda n=s.name, v=var: node.send(n, v.get()))
            btn.grid(row=row, column=2, sticky='w', padx=4, pady=3)

        self.output_leds = {}
        for row, s in enumerate(cfg.outputs):
            self.output_leds[s.name] = self._led(out_frame, row, s, size=26)
            tk.Label(out_frame, text=s.text, font=FONT, bg=BG, fg=FG, anchor='w').grid(
                row=row, column=2, sticky='w', padx=4)

        self.bars = {}
        if cfg.cylinders:
            plant_frame = tk.LabelFrame(self.root, text='設備', font=FONT, bg=BG, fg=FG)
            plant_frame.grid(row=2, column=0, columnspan=2, sticky='we', padx=12, pady=(4, 12))
            for row, c in enumerate(cfg.cylinders):
                tk.Label(plant_frame, text=c.name, font=FONT, bg=BG, fg=FG).grid(row=row, column=0, padx=6)
                canvas = tk.Canvas(plant_frame, width=360, height=26, bg='#2c2c2e', highlightthickness=0)
                canvas.grid(row=row, column=1, padx=6, pady=6)
                self.bars[c.name] = canvas

        self.root.after(50, self._refresh)

    def _frame(self, title: str, column: int) -> tk.LabelFrame:
        frame = tk.LabelFrame(self.root, text=title, font=FONT, bg=BG, fg=FG, padx=8, pady=6)
        frame.grid(row=1, column=column, sticky='nwe', padx=12, pady=4)
        return frame

    def _led(self, parent, row: int, s, size: int = 18) -> tk.Canvas:
        canvas = tk.Canvas(parent, width=size + 4, height=size + 4, bg=BG, highlightthickness=0)
        canvas.create_oval(2, 2, size + 2, size + 2, fill=OFF_COLOR, outline='#636366', tags='led')
        canvas.grid(row=row, column=0, padx=4)
        tk.Label(parent, text=f'{s.label:>4} {s.openplc_address}', font=SMALL, bg=BG, fg=SUB_FG).grid(
            row=row, column=1, sticky='w')
        return canvas

    def _refresh(self) -> None:
        if not rclpy.ok():  # Ctrl+C (launch 終了) で閉じる
            self.root.destroy()
            return
        node = self.node
        if node.connected:
            self.status.configure(text='● OpenPLC 接続中', fg='#34c759')
        else:
            self.status.configure(text='● OpenPLC 未接続 (ポーリング待ち)', fg='#ff9500')
        for s in node.cfg.inputs:
            on = node.state.get(s.name, False)
            self.input_leds[s.name].itemconfigure('led', fill='#0a84ff' if on else OFF_COLOR)
            if s.name in self.toggles and s.name in node.state:
                # トピックから直接切り替えられた場合もボタンの表示を合わせる
                self.toggles[s.name].set(on != s.normally_closed)
        for s in node.cfg.outputs:
            on = node.state.get(s.name, False)
            color = LAMP_COLORS.get(s.color) or ('#ffd60a' if s.type == 'buzzer' else '#0a84ff')
            self.output_leds[s.name].itemconfigure('led', fill=color if on else OFF_COLOR)
        for name, canvas in self.bars.items():
            pos = node.positions.get(name, 0.0)
            canvas.delete('all')
            canvas.create_rectangle(4, 8, 40, 18, fill='#636366', outline='')
            x = 40 + pos * 300
            canvas.create_rectangle(40, 11, x, 15, fill='#aeaeb2', outline='')
            canvas.create_rectangle(x, 4, x + 12, 22, fill='#0a84ff', outline='')
            canvas.create_text(356, 13, text=f'{pos * 100:3.0f}%', fill=FG, font=SMALL, anchor='e')
        self.root.after(50, self._refresh)

    def run(self) -> None:
        self.root.mainloop()


def main(args=None):
    rclpy.init(args=args)
    node = PanelNode()

    def spin():
        try:
            rclpy.spin(node)
        except ExternalShutdownException:
            pass

    threading.Thread(target=spin, daemon=True).start()
    app = PanelApp(node)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
