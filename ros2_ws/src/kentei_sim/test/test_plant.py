from kentei_sim.io_map import Cylinder
from kentei_sim.plant import Plant


def _run(plant, outputs, seconds, dt=0.01):
    sensors = {}
    for _ in range(int(round(seconds / dt))):
        sensors = plant.step(dt, outputs)
    return sensors


def test_single_acting_cylinder():
    plant = Plant([Cylinder('CYL1', 'SOL1', '', 'LS1', 'LS2', stroke_time=1.0)])
    assert plant.step(0.0, {}) == {'LS1': True, 'LS2': False}
    sensors = _run(plant, {'SOL1': True}, 0.5)
    assert sensors == {'LS1': False, 'LS2': False}
    sensors = _run(plant, {'SOL1': True}, 0.6)
    assert sensors == {'LS1': False, 'LS2': True}
    sensors = _run(plant, {'SOL1': False}, 1.1)
    assert sensors == {'LS1': True, 'LS2': False}


def test_double_acting_cylinder_holds_position():
    plant = Plant([Cylinder('CYL1', 'FWD', 'BWD', 'LS1', 'LS2', stroke_time=1.0)])
    _run(plant, {'FWD': True}, 0.5)
    _run(plant, {}, 1.0)
    assert abs(plant.positions()['CYL1'] - 0.5) < 0.02
    _run(plant, {'BWD': True}, 0.6)
    assert plant.positions()['CYL1'] == 0.0
