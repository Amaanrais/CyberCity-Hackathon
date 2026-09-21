import pytest
from app.plant import PlantSimulator, calculate_ph, get_ph_band


def test_calculate_ph():
    # Nominal 100 ppm -> pH ~7.6 (safe band)
    ph_nom = calculate_ph(100.0)
    assert 7.5 <= ph_nom <= 7.7
    assert get_ph_band(ph_nom) == "safe"

    # 150 ppm -> safe/elevated boundary
    ph_150 = calculate_ph(150.0)
    assert 7.9 <= ph_150 <= 8.3
    assert get_ph_band(ph_150) == "safe"

    # 300 ppm -> elevated band
    ph_300 = calculate_ph(300.0)
    assert 8.5 < ph_300 <= 10.0
    assert get_ph_band(ph_300) == "elevated"

    # 1,000 ppm -> dangerous band
    ph_1000 = calculate_ph(1000.0)
    assert ph_1000 > 10.0
    assert get_ph_band(ph_1000) == "dangerous"

    # 11,100 ppm Oldsmar spike -> extreme caustic hazard
    ph_oldsmar = calculate_ph(11100.0)
    assert ph_oldsmar >= 12.5
    assert get_ph_band(ph_oldsmar) == "dangerous"


def test_plant_simulator_baseline():
    plant = PlantSimulator(seed=42)
    p, v, flow = plant.read_sensors()
    assert 95.0 <= p <= 105.0
    assert 95.0 <= v <= 105.0
    assert 48.0 <= flow <= 52.0
    assert plant.tank_concentration == 100.0
    assert plant.ph == calculate_ph(100.0)


def test_plant_simulator_lag_step():
    plant = PlantSimulator(seed=42, tau_seconds=4.5)
    # Inject a step input of 1000 ppm dose
    for _ in range(3):
        plant.step(actual_dose_ppm=1000.0, actual_flow_l_s=50.0, dt=1.0)
    # Concentration should ramp smoothly, not teleport
    assert 100.0 < plant.tank_concentration < 1000.0
    # Over 20 seconds it should approach ~1000 ppm
    for _ in range(25):
        plant.step(actual_dose_ppm=1000.0, actual_flow_l_s=50.0, dt=1.0)
    assert plant.tank_concentration > 990.0
