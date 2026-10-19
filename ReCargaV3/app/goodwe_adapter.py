"""
Adaptador de telemetria GoodWe (opcional).

O ReCarga funciona 100% simulado por padrão. Se houver um inversor GoodWe na
rede local (séries ET/EH/DT, protocolo UDP 8899 ou Modbus-TCP), o motor pode
passar a usar a geração fotovoltaica e o SOC da bateria REAIS no lugar da
simulação:

    pip install goodwe            # biblioteca open-source de comunicação com inversores GoodWe
    set GOODWE_HOST=192.168.0.50  # (Windows)   |   export GOODWE_HOST=192.168.0.50  (Linux/macOS)
    python app/server.py

Escopo desta versão: **somente leitura** (telemetria). Os comandos de carga/descarga
da bateria continuam sendo decididos pelo otimizador do ReCarga e não são escritos
no inversor.

Os nomes dos sensores abaixo (`ppv`, `battery_soc`, ...) seguem a biblioteca
`goodwe`; eles podem variar conforme o modelo/firmware — confira com
`await inverter.read_runtime_data()` no seu equipamento. Esta integração foi
validada apenas com um objeto simulado (ver tests/test_engine.py); NÃO foi
testada em um inversor físico.
"""

import asyncio
import threading
import time


class GoodWeTelemetry:
    """Lê o inversor em uma thread própria e expõe o último valor via `read()`."""

    def __init__(self, host: str, interval_s: float = 5.0):
        self.host = host
        self.interval_s = interval_s
        self._last = None
        self._lock = threading.Lock()
        self._error = None
        threading.Thread(target=self._run, daemon=True).start()

    def read(self):
        with self._lock:
            return dict(self._last) if self._last else None

    @property
    def error(self):
        return self._error

    def _run(self):
        try:
            import goodwe  # noqa: WPS433 (importação tardia: dependência opcional)
        except ImportError:
            self._error = "pacote 'goodwe' não instalado (pip install goodwe)"
            return
        asyncio.run(self._loop(goodwe))

    async def _loop(self, goodwe):
        inverter = None
        while True:
            try:
                if inverter is None:
                    inverter = await goodwe.connect(self.host)
                data = await inverter.read_runtime_data()
                reading = parse_runtime_data(data)
                with self._lock:
                    self._last = reading
                self._error = None
            except Exception as exc:  # rede fora, firmware diferente, etc.
                self._error = str(exc)
                inverter = None
            await asyncio.sleep(self.interval_s)


def parse_runtime_data(data: dict) -> dict:
    """Converte o dicionário da biblioteca `goodwe` para o formato do motor (kW e %)."""
    ppv_w = data.get("ppv")                          # potência FV total (W)
    soc = data.get("battery_soc")                    # estado de carga da bateria (%)
    p_batt_w = data.get("pbattery1")                 # >0 descarregando / <0 carregando (convenção da lib)
    house_w = data.get("house_consumption")          # consumo local (W)
    return dict(
        solar_kw=(float(ppv_w) / 1000.0) if ppv_w is not None else None,
        battery_soc=float(soc) if soc is not None else None,
        battery_kw=(float(p_batt_w) / 1000.0) if p_batt_w is not None else None,
        house_kw=(float(house_w) / 1000.0) if house_w is not None else None,
        timestamp=time.time(),
    )
