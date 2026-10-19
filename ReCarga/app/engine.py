"""
ReCarga — motor de simulação e otimização (Sprint 4)

Integra, em um único ciclo de controle (`Engine.step`):

  geração solar  ->  armazenamento (bateria)  ->  gerenciamento de demanda
  (30 kWp simulados)   (modelo tipo GoodWe Lynx)  (pré-pago prioritário)

e adiciona três camadas de inteligência:

  1. Otimizador preditivo   — prevê a geração solar e reserva bateria para o
                              horário de ponta (peak shaving).
  2. Proteção/anomalia      — compara corrente medida (Hall) x comandada e
                              desarma a vaga em caso de sobrecorrente.
  3. Explicabilidade        — cada decisão do otimizador é registrada em texto.

Tempo simulado: 1 ciclo (tick) = 6 minutos simulados, 240 ciclos = 1 dia.
Isso faz a energia (kWh), a bateria (SOC) e a tarifa de ponta evoluírem de forma
realista mesmo com o dia "acelerado" para a demonstração.

O módulo usa somente a biblioteca padrão do Python.
"""

import math
import random
from collections import deque

# ---------------------------------------------------------------------------
# Parâmetros elétricos / comerciais
# ---------------------------------------------------------------------------
VOLTAGE = 230                    # V (monofásico equivalente por carregador)
GRID_CAPACITY_A = 40             # A contratados junto à concessionária
BUS_LIMIT_A = 60                 # A — limite físico do barramento (rede + geração local)
PRICE_PRE = 1.35                 # R$/kWh cobrado do usuário pré-pago
PRICE_POS = 0.98                 # R$/kWh cobrado do usuário pós-pago
CAR_NAMES = ["Onix EV", "HB20 e", "Kwid Volt", "Compass e", "Fastback e", "Corolla e+"]

# ---------------------------------------------------------------------------
# Tempo simulado
# ---------------------------------------------------------------------------
TICKS_PER_DAY = 240
TICK_HOURS = 24 / TICKS_PER_DAY  # 0,1 h = 6 min simulados por ciclo

# ---------------------------------------------------------------------------
# Geração solar (fotovoltaica)
# ---------------------------------------------------------------------------
SOLAR_KWP = 30.0                 # potência instalada (cobertura do estacionamento)

# ---------------------------------------------------------------------------
# Armazenamento (bateria de lítio — dimensionamento ilustrativo)
# ---------------------------------------------------------------------------
BATT_CAPACITY_KWH = 30.0
BATT_MAX_KW = 15.0               # potência máxima de carga/descarga
BATT_MIN_SOC = 0.15              # reserva técnica (proteção da vida útil)
BATT_EFFICIENCY = 0.95           # eficiência por sentido (round-trip ≈ 90%)

# ---------------------------------------------------------------------------
# Tarifa da rede (valores ILUSTRATIVOS, inspirados na tarifa branca)
# ---------------------------------------------------------------------------
PEAK_START, PEAK_END = 18, 21    # horário de ponta
TARIFF_OFFPEAK = 0.65            # R$/kWh fora de ponta
TARIFF_PEAK = 1.95               # R$/kWh na ponta
EXPORT_CREDIT = 0.45             # R$/kWh creditado pelo excedente injetado na rede
GRID_EMISSION_FACTOR_KG_KWH = 0.117   # kg CO2/kWh (referência simplificada, uso didático)
KG_CO2_PER_TREE_YEAR = 22.0      # equivalência didática de absorção anual por árvore

# ---------------------------------------------------------------------------
# Proteção
# ---------------------------------------------------------------------------
OVERCURRENT_RATIO = 1.25         # medido/comandado acima disso => desarme
TRIP_COOLDOWN_TICKS = 10         # 1 hora simulada fora de operação
PEAK_POS_THROTTLE = 0.70         # redução do pós-pago na ponta com bateria esgotada (modo auto)

MODES = ("auto", "eco", "grid")
MODE_LABELS = {
    "auto": "Auto (IA preditiva)",
    "eco": "Solar-first (autoconsumo)",
    "grid": "Somente rede (sem otimização)",
}


def is_peak(hour: float) -> bool:
    return PEAK_START <= hour < PEAK_END


def tariff_at(hour: float) -> float:
    return TARIFF_PEAK if is_peak(hour) else TARIFF_OFFPEAK


def clear_sky_factor(hour: float) -> float:
    """Curva senoidal 6h–18h (pico às 12h) — geração com céu limpo, normalizada em 0..1."""
    if hour < 6 or hour > 18:
        return 0.0
    return max(0.0, math.sin(math.pi * (hour - 6) / 12))


def make_station(i, plan, active):
    return dict(
        id=i, name=CAR_NAMES[(i - 1) % len(CAR_NAMES)], plan=plan, active=active,
        target_a=16 if plan == "pre" else 10, current_a=0.0, commanded_a=0.0,
        status="carregando" if active else "livre", energy_kwh=0.0, cost=0.0,
        trip_ticks=0, fault_ticks=0, anomaly=False,
    )


def default_stations():
    return [
        make_station(1, "pre", True), make_station(2, "pos", True),
        make_station(3, "pos", True), make_station(4, "pre", True),
        make_station(5, "pos", False), make_station(6, "pre", False),
    ]


class Engine:
    """Simulador determinístico (com `seed`) do estacionamento solar com bateria."""

    def __init__(self, seed=None, mode="auto", solar_kwp=SOLAR_KWP,
                 battery_kwh=BATT_CAPACITY_KWH, start_tick=60, schedule=None,
                 telemetry=None, log_limit=3000):
        self.rng = random.Random(seed)
        self.mode = mode
        self.solar_kwp = solar_kwp
        self.battery_kwh_cap = battery_kwh
        self.schedule = schedule          # callable(hour, station_id) -> bool | None
        self.telemetry = telemetry        # objeto com .read() -> dict | None (inversor real)
        self.start_tick = start_tick
        self.log_limit = log_limit
        self.reset()

    # ------------------------------------------------------------------ estado
    def reset(self):
        self.tick = self.start_tick
        self.stations = default_stations()
        self.batt_kwh = self.battery_kwh_cap * 0.5
        self.day_weather = self.rng.uniform(0.65, 1.0)
        self.cloud_est = 0.85               # estimativa (EMA) da nebulosidade
        self.load_ema_kw = 10.0             # demanda média recente (para prever a ponta)
        self.history = deque(maxlen=80)
        self.full_log = deque(maxlen=self.log_limit)
        self.events = deque(maxlen=12)      # alertas de proteção
        self.decisions = []
        self.overload_events = 0
        self.overload_flag = False
        self.overload_avoided_local = 0
        self.avoided_flag = False
        self.trips = 0
        self.last = {}
        self.t = dict(  # totais acumulados
            solar_gen=0.0, solar_to_load=0.0, batt_to_load=0.0, grid_to_load=0.0,
            export=0.0, load=0.0, requested=0.0, grid_peak=0.0, curtailed=0.0,
            grid_cost=0.0, export_credit=0.0, baseline_cost=0.0, co2_avoided=0.0,
        )
        self.telemetry_info = dict(source="simulado", connected=False)
        self._log_event("Sistema iniciado.")

    @property
    def hour(self) -> float:
        return (self.tick % TICKS_PER_DAY) / TICKS_PER_DAY * 24

    @property
    def soc(self) -> float:
        return self.batt_kwh / self.battery_kwh_cap if self.battery_kwh_cap > 0 else 0.0

    def _log_event(self, msg, level="info"):
        self.events.appendleft(dict(hour=round(self.hour, 1), level=level, msg=msg))

    # ------------------------------------------------------------- comandos
    def toggle_plug(self, sid):
        for s in self.stations:
            if s["id"] == sid:
                s["active"] = not s["active"]
                s["current_a"] = 0.0
                s["trip_ticks"] = 0
                s["status"] = "carregando" if s["active"] else "livre"
                return s
        return None

    def toggle_plan(self, sid):
        for s in self.stations:
            if s["id"] == sid:
                s["plan"] = "pos" if s["plan"] == "pre" else "pre"
                s["target_a"] = 10 if s["plan"] == "pos" else 16
                return s
        return None

    def set_plug(self, sid, active):
        for s in self.stations:
            if s["id"] == sid and s["active"] != bool(active):
                return self.toggle_plug(sid)
        return next((s for s in self.stations if s["id"] == sid), None)

    def set_plan(self, sid, plan):
        for s in self.stations:
            if s["id"] == sid and s["plan"] != plan:
                return self.toggle_plan(sid)
        return next((s for s in self.stations if s["id"] == sid), None)

    def set_mode(self, mode):
        if mode in MODES:
            self.mode = mode
            self._log_event(f"Modo alterado para: {MODE_LABELS[mode]}.")
            return True
        return False

    def jump_to_hour(self, hour):
        hour = float(hour) % 24
        day = self.tick // TICKS_PER_DAY
        self.tick = day * TICKS_PER_DAY + int(round(hour / TICK_HOURS))
        self._log_event(f"Relógio simulado ajustado para {int(hour):02d}h.")

    def inject_fault(self, sid, ticks=3, factor=1.6):
        """Simula um pico anômalo na leitura do sensor de efeito Hall."""
        for s in self.stations:
            if s["id"] == sid and s["active"]:
                s["fault_ticks"] = ticks
                s["fault_factor"] = factor
                return True
        return False

    # ------------------------------------------------------------- previsão
    def forecast_solar(self, horizon_h=24):
        """Previsão horária (kW): curva de céu limpo × nebulosidade estimada (EMA)."""
        out = []
        for k in range(horizon_h):
            h = (self.hour + k) % 24
            out.append(dict(
                hour=int(h), kw=round(self.solar_kwp * clear_sky_factor(h + 0.5) * self.cloud_est, 2),
            ))
        return out

    # -------------------------------------------------------------- um ciclo
    def step(self):
        dt = TICK_HOURS
        self.tick += 1
        hour = self.hour
        peak = is_peak(hour)
        tariff = tariff_at(hour)
        decisions = []

        if self.schedule:
            for s in self.stations:
                want = self.schedule(hour, s["id"])
                if want is not None and want != s["active"] and s["trip_ticks"] == 0:
                    s["active"] = want
                    s["current_a"] = 0.0
                    s["status"] = "carregando" if want else "livre"

        # novo dia -> novo "clima"
        if self.tick % TICKS_PER_DAY == 0:
            self.day_weather = self.rng.uniform(0.45, 1.0)

        # --- 1. Geração solar (simulada ou telemetria real) -----------------
        use_local = self.mode != "grid"
        clear = clear_sky_factor(hour)
        solar_gen_kw = self.solar_kwp * clear * self.day_weather * self.rng.uniform(0.92, 1.0)
        tele = self.telemetry.read() if self.telemetry else None
        if tele and tele.get("solar_kw") is not None:
            solar_gen_kw = float(tele["solar_kw"])
            self.telemetry_info = dict(source="GoodWe (telemetria real)", connected=True)
            if tele.get("battery_soc") is not None and self.battery_kwh_cap > 0:
                self.batt_kwh = self.battery_kwh_cap * float(tele["battery_soc"]) / 100.0
        solar_kw = solar_gen_kw if use_local else 0.0
        if clear > 0.15 and self.solar_kwp > 0:
            ratio = min(1.0, solar_gen_kw / (self.solar_kwp * clear))
            self.cloud_est = 0.9 * self.cloud_est + 0.1 * ratio

        # --- 2. Política da bateria ----------------------------------------
        cap = self.battery_kwh_cap
        min_kwh = cap * BATT_MIN_SOC
        has_batt = use_local and cap > 0
        full_cover = False
        reserve_kwh = min_kwh
        if has_batt and self.mode == "eco":
            full_cover = True            # autoconsumo: bateria cobre a carga sempre que o sol não basta
        elif has_batt and self.mode == "auto":
            if peak:
                full_cover = True        # na ponta, a bateria cobre toda a carga que puder
            elif hour < PEAK_START:
                # prevê a energia que a ponta vai exigir e a preserva
                expected = self.load_ema_kw * (PEAK_END - PEAK_START) * 0.8
                reserve_kwh = min(cap * 0.85, min_kwh + expected)
        # energia que a bateria pode entregar neste ciclo: tudo acima do piso vigente
        # (reserva técnica; ou, no modo auto antes da ponta, a reserva prevista para a ponta)
        batt_avail_kw = 0.0
        if has_batt:
            usable = max(0.0, self.batt_kwh - reserve_kwh)
            batt_avail_kw = min(BATT_MAX_KW, usable * BATT_EFFICIENCY / dt)
        capacity_kw = batt_avail_kw
        deliverable_kw = batt_avail_kw

        # --- 3. Gerenciamento de demanda -----------------------------------
        for s in self.stations:
            if s["trip_ticks"] > 0:
                s["trip_ticks"] -= 1
        active = [s for s in self.stations if s["active"] and s["trip_ticks"] == 0]
        pre = [s for s in active if s["plan"] == "pre"]
        pos = [s for s in active if s["plan"] == "pos"]
        pre_t = sum(s["target_a"] for s in pre)
        pos_t = sum(s["target_a"] for s in pos)
        demand_a = pre_t + pos_t

        grid_a = GRID_CAPACITY_A
        local_a = (solar_kw + capacity_kw) * 1000 / VOLTAGE
        cap_total_a = min(BUS_LIMIT_A, grid_a + local_a)

        pre_alloc = min(pre_t, cap_total_a)
        pre_scale = pre_alloc / pre_t if pre_t > 0 else 1.0
        remaining = max(cap_total_a - pre_alloc, 0.0)
        pos_scale = min(remaining / pos_t, 1.0) if pos_t > 0 else 1.0

        battery_empty_peak = (self.mode == "auto" and peak and has_batt and
                              self.batt_kwh <= min_kwh + 0.02 * cap)
        if self.mode == "auto" and peak and (not has_batt or battery_empty_peak) and pos_t > 0:
            pos_scale *= PEAK_POS_THROTTLE
            decisions.append("Ponta com bateria esgotada: reduzindo o pós-pago em 30% para limitar a compra de energia cara.")

        overloaded = demand_a > cap_total_a + 0.01
        if overloaded and not self.overload_flag:
            self.overload_events += 1
        self.overload_flag = overloaded
        # a rede sozinha não aguentaria, mas a geração local sim?
        avoided = demand_a > grid_a + 0.01 and not overloaded
        if avoided and not self.avoided_flag:
            self.overload_avoided_local += 1
        self.avoided_flag = avoided

        # --- 4. Correntes, proteção e cobrança por vaga ---------------------
        for s in self.stations:
            s["anomaly"] = False
            if not s["active"]:
                s["current_a"] = s["commanded_a"] = 0.0
                s["status"] = "livre"
                continue
            if s["trip_ticks"] > 0:
                s["current_a"] = s["commanded_a"] = 0.0
                s["status"] = "protegido"
                continue
            scale = pre_scale if s["plan"] == "pre" else pos_scale
            commanded = s["target_a"] * scale
            measured = commanded * self.rng.uniform(0.92, 1.0)
            if s["fault_ticks"] > 0:
                measured = commanded * s.get("fault_factor", 1.6)
                s["fault_ticks"] -= 1
            s["commanded_a"] = commanded
            if commanded > 0.01 and measured / commanded > OVERCURRENT_RATIO:
                s["anomaly"] = True
                s["trip_ticks"] = TRIP_COOLDOWN_TICKS
                s["current_a"] = 0.0
                s["status"] = "protegido"
                self.trips += 1
                self._log_event(
                    f"Vaga #{s['id']}: leitura {measured:.1f} A vs. comando {commanded:.1f} A "
                    f"({measured / commanded * 100:.0f}%) — sobrecorrente detectada, vaga desarmada.", "alert")
                continue
            s["current_a"] = measured
            if s["plan"] == "pre":
                s["status"] = "reservado" if pre_scale < 0.999 else "carregando"
            else:
                s["status"] = "em fila" if pos_scale <= 0.01 else ("limitado" if pos_scale < 0.85 else "carregando")
            price = PRICE_PRE if s["plan"] == "pre" else PRICE_POS
            e = measured * VOLTAGE / 1000 * dt
            s["energy_kwh"] += e
            s["cost"] += e * price

        # --- 5. Balanço de potência (de onde veio cada kWh) ----------------
        load_kw = sum(s["current_a"] for s in self.stations) * VOLTAGE / 1000
        requested_kw = sum(s["target_a"] for s in self.stations if s["active"]) * VOLTAGE / 1000
        self.load_ema_kw = 0.97 * self.load_ema_kw + 0.03 * load_kw

        solar_to_load = min(solar_kw, load_kw)
        residual = load_kw - solar_to_load
        grid_kw_limit = GRID_CAPACITY_A * VOLTAGE / 1000
        batt_to_load = 0.0
        if has_batt and residual > 0:
            if full_cover:
                batt_to_load = min(residual, deliverable_kw)
                if batt_to_load > 0.05 and peak:
                    decisions.append(f"Horário de ponta: bateria cobrindo {batt_to_load:.1f} kW para evitar tarifa de R$ {TARIFF_PEAK:.2f}/kWh.")
                elif batt_to_load > 0.05:
                    decisions.append(f"Autoconsumo: bateria cobrindo {batt_to_load:.1f} kW da carga.")
            else:
                need = max(0.0, residual - grid_kw_limit)          # só o que a rede não suporta
                batt_to_load = min(need, capacity_kw)
                if batt_to_load > 0.05:
                    decisions.append(f"Bateria complementando a rede ({batt_to_load:.1f} kW) para não limitar clientes.")
        grid_to_load = max(residual - batt_to_load, 0.0)

        surplus = max(solar_kw - solar_to_load, 0.0)
        charge_kw = 0.0
        if has_batt and surplus > 0:
            room_kw = (cap - self.batt_kwh) / (dt * BATT_EFFICIENCY)
            charge_kw = min(surplus, BATT_MAX_KW, max(room_kw, 0.0))
            if charge_kw > 0.05:
                decisions.append(f"Excedente solar de {surplus:.1f} kW: carregando bateria com {charge_kw:.1f} kW.")
        export_kw = max(surplus - charge_kw, 0.0) if use_local else 0.0
        if export_kw > 0.05 and has_batt and self.batt_kwh >= cap * 0.98:
            decisions.append(f"Bateria cheia: injetando {export_kw:.1f} kW de excedente na rede.")
        elif export_kw > 0.05 and not has_batt:
            decisions.append(f"Sem bateria: {export_kw:.1f} kW de excedente injetados na rede.")

        if has_batt:
            self.batt_kwh += charge_kw * dt * BATT_EFFICIENCY - batt_to_load * dt / BATT_EFFICIENCY
            self.batt_kwh = min(max(self.batt_kwh, 0.0), cap)

        if self.mode == "auto" and has_batt and not peak and hour < PEAK_START and reserve_kwh > min_kwh + 0.5:
            decisions.append(
                f"Previsão de ponta às {PEAK_START}h: preservando {reserve_kwh / cap * 100:.0f}% de SOC "
                f"(demanda média recente {self.load_ema_kw:.1f} kW).")
        if self.mode == "grid":
            decisions.append("Modo 'somente rede': geração solar e bateria ignoradas (cenário de referência).")
        if overloaded:
            decisions.append("Demanda acima da capacidade disponível: pós-pago limitado/enfileirado, pré-pago preservado.")
        if avoided:
            decisions.append("Demanda acima do contrato da rede, mas atendida pela geração local — sobrecarga evitada.")
        self.decisions = decisions or ["Operação normal — nenhuma intervenção necessária."]

        # --- 6. Contabilidade ----------------------------------------------
        t = self.t
        t["solar_gen"] += solar_gen_kw * dt if use_local else 0.0
        t["solar_to_load"] += solar_to_load * dt
        t["batt_to_load"] += batt_to_load * dt
        t["grid_to_load"] += grid_to_load * dt
        t["export"] += export_kw * dt
        t["load"] += load_kw * dt
        t["requested"] += requested_kw * dt
        if peak:
            t["grid_peak"] += grid_to_load * dt
        t["grid_cost"] += grid_to_load * dt * tariff
        t["export_credit"] += export_kw * dt * EXPORT_CREDIT
        t["baseline_cost"] += load_kw * dt * tariff
        t["co2_avoided"] += (solar_to_load + batt_to_load) * dt * GRID_EMISSION_FACTOR_KG_KWH

        pre_rev = sum(s["cost"] for s in self.stations if s["plan"] == "pre")
        pos_rev = sum(s["cost"] for s in self.stations if s["plan"] == "pos")
        row = dict(
            t=self.tick, hour=round(hour, 1), pre=round(pre_rev, 2), pos=round(pos_rev, 2),
            load_a=round(sum(s["current_a"] for s in self.stations), 1), load_kw=round(load_kw, 2),
            solar_gen_kw=round(solar_gen_kw if use_local else 0.0, 2), solar_kw=round(solar_to_load, 2),
            batt_kw=round(batt_to_load, 2), grid_kw=round(grid_to_load, 2),
            charge_kw=round(charge_kw, 2), export_kw=round(export_kw, 2),
            soc=round(self.soc * 100, 1), tariff=tariff,
        )
        self.history.append(row)
        self.full_log.append(row)
        self.last = dict(
            solar_gen_kw=solar_gen_kw if use_local else 0.0, solar_to_load=solar_to_load,
            batt_to_load=batt_to_load, charge_kw=charge_kw, grid_to_load=grid_to_load,
            export_kw=export_kw, load_kw=load_kw, cap_total_a=cap_total_a, peak=peak, tariff=tariff,
            demand_a=demand_a, local_a=local_a if use_local else 0.0,
        )

    # --------------------------------------------------------------- saídas
    def metrics(self):
        t = self.t
        load = t["load"]
        renew = t["solar_to_load"] + t["batt_to_load"]
        net_grid_cost = t["grid_cost"] - t["export_credit"]
        revenue = sum(s["cost"] for s in self.stations)
        return dict(
            load_kwh=load, solar_gen_kwh=t["solar_gen"], solar_to_load_kwh=t["solar_to_load"],
            batt_to_load_kwh=t["batt_to_load"], grid_kwh=t["grid_to_load"], export_kwh=t["export"],
            grid_peak_kwh=t["grid_peak"],
            renewable_share_pct=(renew / load * 100) if load > 0 else 0.0,
            service_level_pct=(load / t["requested"] * 100) if t["requested"] > 0 else 100.0,
            grid_cost=t["grid_cost"], export_credit=t["export_credit"], baseline_cost=t["baseline_cost"],
            savings=t["baseline_cost"] - net_grid_cost,
            revenue=revenue, margin=revenue - net_grid_cost,
            co2_avoided_kg=t["co2_avoided"], trees_eq=t["co2_avoided"] / KG_CO2_PER_TREE_YEAR,
            overload_events=self.overload_events, overload_avoided_local=self.overload_avoided_local,
            trips=self.trips,
        )

    def snapshot(self):
        m = self.metrics()
        last = self.last or {}
        cap = self.battery_kwh_cap
        batt_power = last.get("charge_kw", 0.0) - last.get("batt_to_load", 0.0)
        if batt_power > 0.05:
            batt_state = "carregando"
        elif batt_power < -0.05:
            batt_state = "descarregando"
        else:
            batt_state = "em espera"
        stations = self.stations
        total_load_a = sum(s["current_a"] for s in stations)
        return dict(
            stations=stations, history=list(self.history),
            overload_events=self.overload_events, overload_avoided_local=self.overload_avoided_local,
            total_load=total_load_a,
            total_revenue=m["revenue"], total_energy=sum(s["energy_kwh"] for s in stations),
            grid_capacity=GRID_CAPACITY_A, bus_limit=BUS_LIMIT_A,
            max_capacity=round(last.get("cap_total_a", GRID_CAPACITY_A), 1),
            voltage=VOLTAGE, price_pre=PRICE_PRE, price_pos=PRICE_POS,
            mode=self.mode, modes=MODE_LABELS, hour=round(self.hour, 1),
            solar=dict(
                installed_kwp=self.solar_kwp, power_kw=round(last.get("solar_gen_kw", 0.0), 2),
                to_load_kw=round(last.get("solar_to_load", 0.0), 2),
                bonus_a=round(max(last.get("cap_total_a", GRID_CAPACITY_A) - GRID_CAPACITY_A, 0.0), 2), hour_of_day=round(self.hour, 1),
                coverage_pct=round(((last.get("solar_to_load", 0) + last.get("batt_to_load", 0))
                                    / last["load_kw"] * 100) if last.get("load_kw", 0) > 0 else 0.0, 1),
                solar_energy_kwh=m["solar_to_load_kwh"], grid_energy_kwh=m["grid_kwh"],
                co2_avoided_kg=m["co2_avoided_kg"], cloud_est=round(self.cloud_est, 2),
                export_kw=round(last.get("export_kw", 0.0), 2), export_kwh=m["export_kwh"],
            ),
            battery=dict(
                capacity_kwh=cap, kwh=round(self.batt_kwh, 2), soc_pct=round(self.soc * 100, 1),
                power_kw=round(batt_power, 2), state=batt_state, min_soc_pct=BATT_MIN_SOC * 100,
                to_load_kwh=m["batt_to_load_kwh"],
            ),
            tariff=dict(current=tariff_at(self.hour), peak=is_peak(self.hour),
                        offpeak=TARIFF_OFFPEAK, peak_price=TARIFF_PEAK,
                        peak_window=[PEAK_START, PEAK_END], export_credit=EXPORT_CREDIT),
            finance=dict(grid_cost=m["grid_cost"], baseline_cost=m["baseline_cost"],
                         export_credit=m["export_credit"], savings=m["savings"], margin=m["margin"]),
            env=dict(co2_avoided_kg=m["co2_avoided_kg"], renewable_share_pct=m["renewable_share_pct"],
                     trees_eq=m["trees_eq"], service_level_pct=m["service_level_pct"]),
            forecast=self.forecast_solar(24), expected_load_kw=round(self.load_ema_kw, 2), decisions=self.decisions, events=list(self.events),
            trips=self.trips, source=self.telemetry_info,
        )
