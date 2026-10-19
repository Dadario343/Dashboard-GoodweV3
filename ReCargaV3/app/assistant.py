"""
Assistente virtual do ReCarga (português do Brasil).

Interpreta comandos e perguntas em linguagem natural — digitados ou falados
(o navegador faz o reconhecimento de voz via Web Speech API) — e consulta/controla
o motor de simulação.

É um NLU baseado em regras (palavras-chave + extração do número da vaga), sem
dependência de serviços externos. A função `handle()` recebe texto e devolve JSON,
o que a torna pronta para ser chamada por um webhook de Alexa Skill / Google
Assistant Action (essa ponte NÃO está implementada nesta versão).
"""

import re
import unicodedata

from .engine import (MODE_LABELS, PEAK_END, PEAK_START, TARIFF_PEAK, is_peak)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _has(t: str, *words) -> bool:
    return any(w in t for w in words)


def _station_id(t: str, n_stations: int):
    m = re.search(r"(?:vaga|carregador|posicao|numero|#)\s*(?:n[o°º]?\s*)?(\d+)", t) or re.search(r"\b(\d)\b", t)
    if m:
        sid = int(m.group(1))
        if 1 <= sid <= n_stations:
            return sid
    return None


def _hour(t: str):
    m = re.search(r"(\d{1,2})\s*(?:h\b|hs\b|horas?\b|:00)", t) or re.search(r"as\s+(\d{1,2})\b", t)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 24:
            return h % 24
    return None


def recommend(engine):
    """Recomendação proativa baseada no estado atual (usada pelo assistente e pelo painel)."""
    snap = engine.snapshot()
    sol, batt = snap["solar"], snap["battery"]
    idle = [s for s in snap["stations"] if not s["active"]]
    hour = snap["hour"]
    if snap["solar"]["export_kw"] > 3 and idle:
        return (f"Há {sol['export_kw']:.1f} kW de excedente solar sendo injetado na rede. "
                f"Conecte um veículo na vaga #{idle[0]['id']} para aproveitar essa energia gratuita.")
    if hour < PEAK_START and hour >= 12 and batt["soc_pct"] < 60 and sol["power_kw"] < 8:
        return (f"A bateria está em {batt['soc_pct']:.0f}% e a geração solar está caindo; "
                f"a ponta ({PEAK_START}h–{PEAK_END}h, R$ {TARIFF_PEAK:.2f}/kWh) se aproxima. "
                "Considere adiar recargas pós-pago para depois das 21h.")
    if is_peak(hour) and batt["soc_pct"] <= batt["min_soc_pct"] + 3:
        return "Estamos na ponta com a bateria esgotada: recomendo adiar recargas pós-pago ou migrar o veículo para o plano pré-pago."
    if snap["overload_events"] > 0 and snap["mode"] != "auto":
        return "Houve limitação de carga e o modo Auto (IA) não está ativo. Ative-o para que o otimizador antecipe a ponta."
    return "Operação equilibrada. Nenhuma ação recomendada no momento."


def handle(engine, text: str) -> dict:
    t = _norm(text or "").strip()
    if not t:
        return dict(reply="Não ouvi nada. Pergunte, por exemplo: 'qual o status da bateria?'", intent="empty")
    snap = engine.snapshot()
    n = len(snap["stations"])
    sid = _station_id(t, n)

    # ---- comandos (alteram o sistema) --------------------------------------
    if _has(t, "desligue", "desligar", "desativ", "desconect", "remova", "encerre"):
        if sid:
            engine.set_plug(sid, False)
            return dict(reply=f"Pronto, a vaga #{sid} foi desligada.", intent="plug_off", action=dict(type="plug", id=sid, active=False))
        return dict(reply="Qual vaga devo desligar? Diga, por exemplo: 'desligue a vaga 3'.", intent="plug_off")
    if _has(t, "ligue", "ligar", "ative", "ativar", "conecte", "conectar", "inicie", "iniciar") and not _has(t, "modo"):
        if sid:
            engine.set_plug(sid, True)
            return dict(reply=f"Vaga #{sid} ativada. O motor de demanda já está redistribuindo a corrente.", intent="plug_on", action=dict(type="plug", id=sid, active=True))
        return dict(reply="Qual vaga devo ligar? Diga, por exemplo: 'ligue a vaga 5'.", intent="plug_on")
    if _has(t, "plano", "pre-pago", "prepago", "pos-pago", "pospago", "pre pago", "pos pago") and _has(t, "troque", "trocar", "mude", "mudar", "altere", "passe", "coloque", "para"):
        if sid:
            plan = "pre" if _has(t, "pre-pago", "prepago", "pre pago") else ("pos" if _has(t, "pos-pago", "pospago", "pos pago") else None)
            if plan:
                engine.set_plan(sid, plan)
            else:
                engine.toggle_plan(sid)
            new = next(s for s in engine.stations if s["id"] == sid)["plan"]
            return dict(reply=f"A vaga #{sid} agora está no plano {'pré-pago' if new == 'pre' else 'pós-pago'}.", intent="plan", action=dict(type="plan", id=sid, plan=new))
        return dict(reply="De qual vaga devo trocar o plano?", intent="plan")
    if _has(t, "modo") or _has(t, "ative o eco", "somente rede", "so rede"):
        if _has(t, "auto", "inteligente", "preditivo", "otimiz") or re.search(r"\bia\b", t):
            engine.set_mode("auto")
            return dict(reply="Modo Auto (IA preditiva) ativado: vou prever a geração solar e reservar bateria para a ponta.", intent="mode", action=dict(type="mode", mode="auto"))
        if _has(t, "eco", "solar", "guloso"):
            engine.set_mode("eco")
            return dict(reply="Modo Solar-first ativado: uso solar e bateria sempre que possível, sem reservar para a ponta.", intent="mode", action=dict(type="mode", mode="eco"))
        if _has(t, "rede", "manual", "normal", "referencia"):
            engine.set_mode("grid")
            return dict(reply="Modo 'somente rede' ativado: solar e bateria ignorados (cenário de referência).", intent="mode", action=dict(type="mode", mode="grid"))
        return dict(reply="Modos disponíveis: Auto (IA), Solar-first e Somente rede. Qual deseja?", intent="mode")
    if _has(t, "va para", "ir para", "pule", "pular", "avance", "avancar", "salte") and _hour(t) is not None:
        h = _hour(t)
        engine.jump_to_hour(h)
        return dict(reply=f"Relógio simulado ajustado para {h:02d}h.", intent="jump", action=dict(type="hour", hour=h))
    if _has(t, "simule", "simular", "injete", "injetar") and _has(t, "falha", "pico", "sobrecorrente", "anomalia"):
        target = sid or next((s["id"] for s in engine.stations if s["active"]), None)
        if target and engine.inject_fault(target):
            return dict(reply=f"Falha simulada na vaga #{target}. Observe a proteção atuar no painel de alertas.", intent="fault", action=dict(type="fault", id=target))
        return dict(reply="Preciso de uma vaga ativa para simular a falha.", intent="fault")

    # ---- consultas -----------------------------------------------------------
    if _has(t, "recomend", "sugest", "dica", "o que devo", "o que fazer", "conselho"):
        return dict(reply=recommend(engine), intent="recommend")
    if _has(t, "bateria", "soc", "armazen"):
        b = snap["battery"]
        return dict(reply=(f"A bateria está com {b['soc_pct']:.0f}% ({b['kwh']:.1f} de {b['capacity_kwh']:.0f} kWh) e está {b['state']}"
                           f"{' a ' + format(abs(b['power_kw']), '.1f') + ' kW' if abs(b['power_kw']) > 0.05 else ''}."), intent="battery")
    if _has(t, "solar", "geracao", "painel", "paineis", "fotovolt", "renovav") or re.search(r"\bsol\b", t):
        s = snap["solar"]
        return dict(reply=(f"Os painéis geram {s['power_kw']:.1f} kW agora (de {s['installed_kwp']:.0f} kWp instalados). "
                           f"{s['coverage_pct']:.0f}% do consumo do estacionamento está sendo coberto por energia renovável "
                           f"(solar direta + bateria). Nebulosidade estimada: {(1 - s['cloud_est']) * 100:.0f}%."), intent="solar")
    if _has(t, "co2", "carbono", "emiss", "ambient", "arvore", "sustent"):
        e = snap["env"]
        return dict(reply=(f"Já evitamos {e['co2_avoided_kg']:.2f} kg de CO₂ nesta sessão, o que equivale a "
                           f"{e['trees_eq']:.2f} árvore(s) em um ano (equivalência didática). A fatia renovável do consumo é {e['renewable_share_pct']:.0f}%."), intent="co2")
    if _has(t, "economi", "custo", "gasto", "dinheiro", "receita", "lucro", "margem", "financ"):
        f = snap["finance"]
        return dict(reply=(f"Receita das recargas: R$ {snap['total_revenue']:.2f}. Custo da energia da rede: R$ {f['grid_cost']:.2f} "
                           f"(sem solar/bateria seria R$ {f['baseline_cost']:.2f}). Economia estimada: R$ {f['savings']:.2f}. "
                           f"Margem operacional: R$ {f['margin']:.2f}."), intent="finance")
    if _has(t, "tarifa", "ponta", "preco da energia"):
        tf = snap["tariff"]
        return dict(reply=(f"A tarifa agora é R$ {tf['current']:.2f}/kWh ({'horário de ponta' if tf['peak'] else 'fora de ponta'}). "
                           f"A ponta vai das {PEAK_START}h às {PEAK_END}h, a R$ {TARIFF_PEAK:.2f}/kWh."), intent="tariff")
    if _has(t, "sobrecarga", "limite", "alerta", "falha", "protec"):
        return dict(reply=(f"Limitações de carga: {snap['overload_events']}. Sobrecargas evitadas pela geração local: {snap['overload_avoided_local']}. "
                           f"Desarmes por sobrecorrente: {snap['trips']}."), intent="overload")
    if sid and _has(t, "vaga", "carro", "veiculo", "status", "como esta", "carregador"):
        s = next(x for x in snap["stations"] if x["id"] == sid)
        kw = s["current_a"] * snap["voltage"] / 1000
        return dict(reply=(f"Vaga #{sid} ({s['name']}): {s['status']}, plano {'pré-pago' if s['plan'] == 'pre' else 'pós-pago'}, "
                           f"{kw:.2f} kW, {s['energy_kwh']:.1f} kWh entregues, R$ {s['cost']:.2f}."), intent="station")
    if _has(t, "status", "resumo", "como esta", "situacao", "geral", "panorama"):
        active = sum(1 for s in snap["stations"] if s["active"])
        return dict(reply=(f"São {snap['hour']:02.0f}h simuladas, modo {MODE_LABELS[snap['mode']]}. {active} de {n} vagas ativas, "
                           f"carga de {snap['total_load']:.0f} A (limite atual {snap['max_capacity']:.0f} A). "
                           f"Solar {snap['solar']['power_kw']:.1f} kW, bateria {snap['battery']['soc_pct']:.0f}%, "
                           f"{snap['env']['renewable_share_pct']:.0f}% do consumo é renovável."), intent="status")
    if _has(t, "ajuda", "help", "o que voce faz", "comandos", "o que posso"):
        return dict(reply=("Posso responder sobre solar, bateria, CO₂, economia, tarifa e vagas; ligar/desligar uma vaga, trocar o plano, "
                           "mudar o modo (Auto, Solar-first, Somente rede), pular para uma hora do dia, simular uma falha e dar recomendações."), intent="help")
    return dict(reply="Não entendi. Tente: 'status geral', 'como está a bateria?', 'desligue a vaga 3' ou 'o que você recomenda?'.", intent="unknown")
