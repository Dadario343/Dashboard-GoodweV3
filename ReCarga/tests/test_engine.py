"""Testes do motor ReCarga. Execute com:  python -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import assistant                                   # noqa: E402
from app.engine import (BATT_MIN_SOC, BUS_LIMIT_A, GRID_CAPACITY_A, TICKS_PER_DAY,  # noqa: E402
                        VOLTAGE, Engine, TICK_HOURS)
from app.goodwe_adapter import parse_runtime_data           # noqa: E402


def run(engine, days=3):
    for _ in range(TICKS_PER_DAY * days):
        engine.step()
        yield engine


class FakeInverter:
    """Simula a leitura de um inversor GoodWe real."""
    def read(self):
        return dict(solar_kw=12.0, battery_soc=80.0)


class PhysicalInvariants(unittest.TestCase):
    def test_bus_and_grid_limits_are_never_exceeded(self):
        for mode in ("auto", "eco", "grid"):
            e = Engine(seed=7, mode=mode)
            for e in run(e, 3):
                load_a = sum(s["current_a"] for s in e.stations)
                self.assertLessEqual(load_a, BUS_LIMIT_A + 1e-6, mode)
                self.assertLessEqual(e.last["grid_to_load"], GRID_CAPACITY_A * VOLTAGE / 1000 + 1e-6, mode)
                if mode == "grid":
                    self.assertLessEqual(load_a, GRID_CAPACITY_A + 1e-6)

    def test_battery_soc_stays_within_bounds(self):
        e = Engine(seed=3, mode="auto")
        for e in run(e, 4):
            self.assertGreaterEqual(e.soc, BATT_MIN_SOC - 1e-6)
            self.assertLessEqual(e.soc, 1.0 + 1e-6)

    def test_power_balance_each_tick(self):
        e = Engine(seed=5)
        for e in run(e, 2):
            l = e.last
            self.assertAlmostEqual(l["solar_to_load"] + l["batt_to_load"] + l["grid_to_load"], l["load_kw"], places=6)

    def test_solar_energy_conservation(self):
        e = Engine(seed=11)
        list(run(e, 2))
        t = e.t
        # toda energia solar gerada foi usada, armazenada (com perdas) ou exportada
        self.assertLessEqual(t["solar_to_load"] + t["export"], t["solar_gen"] + 1e-6)

    def test_grid_mode_ignores_solar_and_battery(self):
        e = Engine(seed=1, mode="grid")
        list(run(e, 1))
        self.assertEqual(e.t["solar_to_load"], 0)
        self.assertEqual(e.t["batt_to_load"], 0)
        self.assertAlmostEqual(e.t["grid_to_load"], e.t["load"], places=6)

    def test_prepaid_has_priority(self):
        e = Engine(seed=2, mode="grid")
        for s in e.stations:
            s["active"] = True
        e.step()
        pre = [s for s in e.stations if s["plan"] == "pre"]
        pos = [s for s in e.stations if s["plan"] == "pos"]
        self.assertTrue(all(s["status"] in ("reservado", "carregando") for s in pre))
        self.assertTrue(all(s["status"] in ("em fila", "limitado") for s in pos))

    def test_energy_integration_uses_simulated_dt(self):
        e = Engine(seed=4, mode="grid")
        e.step()
        s1 = e.stations[0]
        self.assertAlmostEqual(s1["energy_kwh"], s1["current_a"] * VOLTAGE / 1000 * TICK_HOURS, places=9)


class Optimization(unittest.TestCase):
    def test_renewables_reduce_grid_cost_vs_baseline(self):
        base, smart = Engine(seed=9, mode="grid"), Engine(seed=9, mode="auto")
        list(run(base, 5)); list(run(smart, 5))
        self.assertLess(smart.t["grid_cost"] - smart.t["export_credit"], base.t["grid_cost"])
        self.assertGreater(smart.metrics()["renewable_share_pct"], 20)

    def test_local_generation_avoids_overload(self):
        e = Engine(seed=1, mode="eco")
        list(run(e, 2))
        self.assertGreater(e.overload_avoided_local, 0)

    def test_forecast_shape(self):
        e = Engine(seed=1)
        e.step()
        f = e.forecast_solar(24)
        self.assertEqual(len(f), 24)
        self.assertEqual(max(f, key=lambda x: x["kw"])["hour"] in (11, 12), True)
        night = [x for x in f if x["hour"] in (22, 23, 0, 1, 2)]
        self.assertTrue(all(x["kw"] == 0 for x in night))

    def test_auto_mode_reserves_battery_for_peak(self):
        e = Engine(seed=1, mode="auto")
        e.jump_to_hour(14)
        e.batt_kwh = e.battery_kwh_cap * 0.40
        e.step()
        self.assertTrue(any("Previsão de ponta" in d for d in e.decisions))


class Protection(unittest.TestCase):
    def test_overcurrent_trips_station_and_recovers(self):
        e = Engine(seed=1)
        e.step()
        self.assertTrue(e.inject_fault(1, ticks=1))
        e.step()
        s = e.stations[0]
        self.assertEqual(s["status"], "protegido")
        self.assertEqual(s["current_a"], 0.0)
        self.assertEqual(e.trips, 1)
        for _ in range(12):
            e.step()
        self.assertNotEqual(e.stations[0]["status"], "protegido")

    def test_normal_jitter_never_trips(self):
        e = Engine(seed=13)
        list(run(e, 5))
        self.assertEqual(e.trips, 0)


class Telemetry(unittest.TestCase):
    def test_real_inverter_overrides_simulation(self):
        e = Engine(seed=1, telemetry=FakeInverter())
        e.jump_to_hour(12)
        e.step()
        self.assertAlmostEqual(e.last["solar_gen_kw"], 12.0)
        self.assertEqual(e.telemetry_info["connected"], True)
        self.assertAlmostEqual(e.soc, 0.80, places=2)

    def test_parse_goodwe_runtime_data(self):
        r = parse_runtime_data({"ppv": 4200, "battery_soc": 63, "pbattery1": -1500, "house_consumption": 900})
        self.assertAlmostEqual(r["solar_kw"], 4.2)
        self.assertEqual(r["battery_soc"], 63.0)
        self.assertAlmostEqual(r["battery_kw"], -1.5)
        self.assertIsNone(parse_runtime_data({})["solar_kw"])


class Assistant(unittest.TestCase):
    def setUp(self):
        self.e = Engine(seed=1)
        self.e.step()

    def ask(self, text):
        return assistant.handle(self.e, text)

    def test_commands(self):
        self.assertEqual(self.ask("Desligue a vaga 3")["intent"], "plug_off")
        self.assertFalse(self.e.stations[2]["active"])
        self.assertEqual(self.ask("ligue a vaga 5")["intent"], "plug_on")
        self.assertTrue(self.e.stations[4]["active"])
        self.ask("mude a vaga 2 para pré-pago")
        self.assertEqual(self.e.stations[1]["plan"], "pre")
        self.ask("ative o modo eco")
        self.assertEqual(self.e.mode, "eco")
        self.ask("ative o modo IA")
        self.assertEqual(self.e.mode, "auto")
        self.ask("vá para as 18 horas")
        self.assertEqual(int(self.e.hour), 18)

    def test_queries(self):
        for q, intent in [("como está a bateria?", "battery"), ("quanta energia solar agora", "solar"),
                          ("quanto CO2 evitamos", "co2"), ("qual a economia?", "finance"),
                          ("status geral", "status"), ("como está a vaga 1", "station"),
                          ("o que você recomenda?", "recommend"), ("qual a tarifa", "tariff")]:
            self.assertEqual(self.ask(q)["intent"], intent, q)
        self.assertEqual(self.ask("blablabla")["intent"], "unknown")
        self.assertEqual(self.ask("")["intent"], "empty")


if __name__ == "__main__":
    unittest.main()
