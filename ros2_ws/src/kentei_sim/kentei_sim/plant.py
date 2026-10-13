"""出力に応じてセンサ入力を動かす簡易設備モデル."""

from typing import Dict, List

from .io_map import Cylinder


class CylinderModel:
    """位置 0.0 (後退端) 〜 1.0 (前進端) を一定速度で移動するシリンダ."""

    def __init__(self, cfg: Cylinder):
        self.cfg = cfg
        self.position = 0.0

    def step(self, dt: float, outputs: Dict[str, bool]) -> None:
        extend = outputs.get(self.cfg.extend_output, False)
        if self.cfg.retract_output:
            retract = outputs.get(self.cfg.retract_output, False)
            # 複動: 両方 ON / 両方 OFF ならその場で停止
            direction = (1 if extend else 0) - (1 if retract else 0)
        else:
            # 単動 (スプリングリターン)
            direction = 1 if extend else -1
        self.position += direction * dt / self.cfg.stroke_time
        self.position = min(1.0, max(0.0, self.position))

    def sensors(self) -> Dict[str, bool]:
        result = {}
        if self.cfg.retracted_sensor:
            result[self.cfg.retracted_sensor] = self.position <= 0.0
        if self.cfg.extended_sensor:
            result[self.cfg.extended_sensor] = self.position >= 1.0
        return result


class Plant:
    def __init__(self, cylinders: List[Cylinder]):
        self.cylinders = [CylinderModel(c) for c in cylinders]

    def step(self, dt: float, outputs: Dict[str, bool]) -> Dict[str, bool]:
        """dt 秒進めて、センサ名 -> 値 を返す."""
        sensors = {}
        for c in self.cylinders:
            c.step(dt, outputs)
            sensors.update(c.sensors())
        return sensors

    def positions(self) -> Dict[str, float]:
        return {c.cfg.name: c.position for c in self.cylinders}
