"""
Simulação de cenários (headless) — gera os resultados quantitativos da Sprint 4.

Compara quatro configurações do MESMO estacionamento, com a mesma semente
(mesmo clima e mesma ocupação), por 30 dias simulados:

    A  Referência        — só rede (sem solar, sem bateria)
    B  Solar             — painéis 30 kWp, sem bateria
    C  Solar + bateria   — autoconsumo (solar-first: a bateria cobre a carga sempre que o sol não basta,
                           comportamento padrão de inversores híbridos)
    D  Solar + bateria + IA preditiva (modo auto: previsão + reserva para a ponta)

Uso (a partir da raiz do repositório):
    python simulation/run_scenarios.py
Saídas: simulation/results/*.csv|json  e  docs/img/*.png  (requer matplotlib)
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engine import (BATT_CAPACITY_KWH, TICKS_PER_DAY, TARIFF_OFFPEAK, TARIFF_PEAK,  # noqa: E402
                        Engine)

DAYS = 30
SEED = 42

# perfil de ocupação típico de um estacionamento comercial/misto (horas de plug-in por vaga)
OCCUPANCY = {
    1: [(8, 18)],            # funcionário (pré-pago)
    2: [(8, 17)],            # funcionário (pós-pago)
    3: [(9, 19)],            # cliente (pós-pago)
    4: [(17, 23)],           # morador/cliente noturno (pré-pago)
    5: [(18, 24)],           # noturno (pós-pago)
    6: [(10, 14), (18, 22)], # visitante (pré-pago)
}


def schedule(hour, sid):
    return any(a <= hour < b for a, b in OCCUPANCY[sid])


SCENARIOS = [
    ("A", "Referência (só rede)",        dict(mode="grid", battery_kwh=0.0)),
    ("B", "Solar sem bateria",           dict(mode="eco",  battery_kwh=0.0)),
    ("C", "Solar + bateria (autoconsumo)",    dict(mode="eco",  battery_kwh=BATT_CAPACITY_KWH)),
    ("D", "Solar + bateria + IA",        dict(mode="auto", battery_kwh=BATT_CAPACITY_KWH)),
]


def simulate(days=DAYS, seed=SEED, **kw):
    e = Engine(seed=seed, schedule=schedule, start_tick=0, log_limit=days * TICKS_PER_DAY + 10, **kw)
    for _ in range(days * TICKS_PER_DAY):
        e.step()
    return e


def summarize(e, days=DAYS):
    m = e.metrics()
    net_grid_cost = m["grid_cost"] - m["export_credit"]
    return dict(
        energia_entregue_kwh=round(m["load_kwh"], 1),
        energia_rede_kwh=round(m["grid_kwh"], 1),
        energia_rede_ponta_kwh=round(m["grid_peak_kwh"], 1),
        solar_direta_kwh=round(m["solar_to_load_kwh"], 1),
        bateria_kwh=round(m["batt_to_load_kwh"], 1),
        excedente_injetado_kwh=round(m["export_kwh"], 1),
        participacao_renovavel_pct=round(m["renewable_share_pct"], 1),
        demanda_atendida_pct=round(m["service_level_pct"], 1),
        custo_rede_liquido_rs=round(net_grid_cost, 2),
        economia_vs_referencia_rs=round(m["baseline_cost"] - net_grid_cost, 2),
        receita_rs=round(m["revenue"], 2),
        margem_operacional_rs=round(m["margin"], 2),
        co2_evitado_kg=round(m["co2_avoided_kg"], 1),
        arvores_equivalentes=round(m["trees_eq"], 2),
        limitacoes_de_carga=m["overload_events"],
        sobrecargas_evitadas_pela_geracao_local=m["overload_avoided_local"],
    )


def main():
    out = ROOT / "simulation" / "results"
    out.mkdir(parents=True, exist_ok=True)
    engines, rows = {}, []
    for key, label, kw in SCENARIOS:
        e = simulate(**kw)
        engines[key] = e
        rows.append(dict(cenario=key, descricao=label, **summarize(e)))
        print(f"[{key}] {label}: renovável {rows[-1]['participacao_renovavel_pct']}% · "
              f"custo rede R$ {rows[-1]['custo_rede_liquido_rs']} · ponta {rows[-1]['energia_rede_ponta_kwh']} kWh")

    with open(out / "cenarios_30_dias.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    (out / "cenarios_30_dias.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- sensibilidade: capacidade da bateria no modo IA ----------------------
    sens = []
    for kwh in (0, 10, 20, 30, 45, 60):
        e = simulate(mode="auto", battery_kwh=float(kwh))
        s = summarize(e)
        sens.append(dict(bateria_kwh=kwh, renovavel_pct=s["participacao_renovavel_pct"],
                         custo_rede_liquido_rs=s["custo_rede_liquido_rs"],
                         rede_ponta_kwh=s["energia_rede_ponta_kwh"], demanda_atendida_pct=s["demanda_atendida_pct"]))
    with open(out / "sensibilidade_bateria.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(sens[0].keys()))
        w.writeheader(); w.writerows(sens)
    print("Sensibilidade (bateria):", *[f"\n  {s}" for s in sens])

    try:
        make_plots(engines, rows, sens)
    except ImportError:
        print("matplotlib não instalado — gráficos PNG não gerados (pip install matplotlib).")


def day_profile(e, day):
    log = list(e.full_log)
    return log[day * TICKS_PER_DAY:(day + 1) * TICKS_PER_DAY]


def make_plots(engines, rows, sens):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    img = ROOT / "docs" / "img"
    img.mkdir(parents=True, exist_ok=True)
    BG, FG, GRID = "#0B1210", "#E7F0EC", "#243430"
    C = dict(solar="#FFD166", batt="#2DD4C8", grid="#7E9A90", green="#34D399", red="#EF5350")
    plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": "#121C19", "axes.edgecolor": GRID,
                         "axes.labelcolor": FG, "xtick.color": FG, "ytick.color": FG, "text.color": FG,
                         "grid.color": GRID, "font.size": 10})

    # 1) um dia típico: fluxo de potência — referência x IA -----------------------
    day = 3
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for ax, key, title in ((axes[0], "A", "A · Referência (só rede)"), (axes[1], "D", "D · Solar + bateria + IA preditiva")):
        p = day_profile(engines[key], day)
        h = [(i + 1) * 24 / TICKS_PER_DAY for i in range(len(p))]
        ax.stackplot(h, [r["solar_kw"] for r in p], [r["batt_kw"] for r in p], [r["grid_kw"] for r in p],
                     labels=["solar direta", "bateria", "rede"], colors=[C["solar"], C["batt"], C["grid"]], alpha=.9)
        ax.axvspan(18, 21, color=C["red"], alpha=.15, label="ponta (18–21h)")
        if key != "A":
            ax2 = ax.twinx()
            ax2.plot(h, [r["soc"] for r in p], color=FG, lw=1.2, ls="--", label="SOC da bateria (%)")
            ax2.set_ylim(0, 105); ax2.set_ylabel("SOC (%)")
        ax.set_ylabel("potência (kW)"); ax.set_title(title, loc="left"); ax.grid(alpha=.4)
        ax.set_xlim(0, 24); ax.set_ylim(0, 13.5)
    axes[1].set_xlabel("hora do dia (simulada)")
    hs, ls = axes[1].get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    fig.legend(hs + h2, ls + l2, loc="lower center", ncol=5, frameon=False, fontsize=9)
    fig.suptitle("Origem da energia entregue aos carregadores — um dia típico", x=.02, ha="left", fontsize=13)
    fig.tight_layout(rect=(0, .05, 1, 1)); fig.savefig(img / "sim_fluxo_dia.png", dpi=140); plt.close(fig)

    # 2) comparação de cenários ---------------------------------------------------
    fig, axs = plt.subplots(1, 3, figsize=(13, 4.2))
    labels = [r["cenario"] for r in rows]
    cols = ["#54695F", C["solar"], C["batt"], C["green"]]
    for ax, (k, t) in zip(axs, (("participacao_renovavel_pct", "Participação renovável (%)"),
                                ("custo_rede_liquido_rs", "Custo líquido da rede (R$, 30 dias)"),
                                ("energia_rede_ponta_kwh", "Energia comprada na ponta (kWh)"))):
        vals = [r[k] for r in rows]
        bars = ax.bar(labels, vals, color=cols)
        ax.set_title(t, fontsize=10, loc="left"); ax.grid(axis="y", alpha=.4)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:,.0f}", ha="center", va="bottom", fontsize=9)
    fig.suptitle("A = só rede · B = solar · C = solar+bateria · D = solar+bateria+IA", x=.02, ha="left", fontsize=11)
    fig.tight_layout(); fig.savefig(img / "sim_cenarios.png", dpi=140); plt.close(fig)

    # 3) sensibilidade -------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    xs = [s["bateria_kwh"] for s in sens]
    ax.plot(xs, [s["custo_rede_liquido_rs"] for s in sens], marker="o", color=C["green"], label="custo líquido da rede (R$)")
    ax.set_xlabel("capacidade da bateria (kWh)"); ax.set_ylabel("R$ em 30 dias"); ax.grid(alpha=.4)
    ax2 = ax.twinx()
    ax2.plot(xs, [s["rede_ponta_kwh"] for s in sens], marker="s", color=C["red"], label="rede na ponta (kWh)")
    ax2.set_ylabel("kWh na ponta")
    ax.set_title("Dimensionamento: efeito da capacidade da bateria (modo IA)", loc="left")
    l1, n1 = ax.get_legend_handles_labels(); l2, n2 = ax2.get_legend_handles_labels()
    ax.legend(l1 + l2, n1 + n2, frameon=False, loc="upper right")
    fig.tight_layout(); fig.savefig(img / "sim_sensibilidade_bateria.png", dpi=140); plt.close(fig)
    print("Gráficos salvos em docs/img/")


if __name__ == "__main__":
    main()
