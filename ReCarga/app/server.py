"""
ReCarga — servidor HTTP (somente biblioteca padrão) e API REST.

Execução (a partir da raiz do repositório):

    python app/server.py            # ou: python run.py
    http://localhost:5000

Variáveis de ambiente opcionais:
    PORT=5000            porta HTTP
    GOODWE_HOST=<ip>     usa telemetria real de um inversor GoodWe (ver app/goodwe_adapter.py)
    NO_BROWSER=1         não abre o navegador automaticamente
"""

import csv
import io
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import assistant                      # noqa: E402
from app.engine import Engine, MODES           # noqa: E402

BASE_TICK_SECONDS = 1.5     # 1× : um ciclo a cada 1,5 s reais  (= 6 min simulados)
SPEEDS = (1, 3, 10, 30)     # multiplicadores de velocidade da simulação
speed = 1
PORT = int(os.environ.get("PORT", "5000"))
STATIC_DIR = ROOT / "app" / "static"
TEMPLATES_DIR = ROOT / "app" / "templates"

lock = threading.Lock()


def build_engine():
    telemetry = None
    host = os.environ.get("GOODWE_HOST")
    if host:
        from app.goodwe_adapter import GoodWeTelemetry
        telemetry = GoodWeTelemetry(host)
        print(f"Telemetria GoodWe habilitada em {host}")
    return Engine(telemetry=telemetry)


engine = build_engine()

STATIC_FILES = {
    "/style.css": (STATIC_DIR / "style.css", "text/css; charset=utf-8"),
    "/app.js": (STATIC_DIR / "app.js", "application/javascript; charset=utf-8"),
    "/chart.umd.js": (STATIC_DIR / "chart.umd.js", "application/javascript; charset=utf-8"),
}

CSV_FIELDS = ["t", "hour", "load_kw", "load_a", "solar_gen_kw", "solar_kw", "batt_kw", "charge_kw",
              "grid_kw", "export_kw", "soc", "tariff", "pre", "pos"]


def set_speed(value):
    global speed
    speed = value


def loop():
    while True:
        time.sleep(BASE_TICK_SECONDS / speed)
        with lock:
            engine.step()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, content_type="text/html; charset=utf-8", extra_headers=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _file(self, path: Path, content_type):
        if not path.is_file():
            self._send(404, f"arquivo não encontrado: {path.name}")
            return
        self._send(200, path.read_bytes(), content_type)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._file(TEMPLATES_DIR / "index.html", "text/html; charset=utf-8")
        elif path in STATIC_FILES:
            self._file(*STATIC_FILES[path])
        elif path == "/api/state":
            with lock:
                snap = engine.snapshot()
                snap["recommendation"] = assistant.recommend(engine)
                snap["speed"] = speed
                self._json(snap)
        elif path == "/api/report":
            with lock:
                self._json(dict(metrics=engine.metrics(), hour=engine.hour, mode=engine.mode,
                                recommendation=assistant.recommend(engine)))
        elif path == "/api/report.csv":
            with lock:
                rows = list(engine.full_log)
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
            self._send(200, buf.getvalue(), "text/csv; charset=utf-8",
                       {"Content-Disposition": 'attachment; filename="recarga_sessao.csv"'})
        else:
            self._send(404, "not found")

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def do_POST(self):
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts[:2] == ["api", "assistant"]:
            body = self._read_json()
            with lock:
                result = assistant.handle(engine, str(body.get("text", "")))
            self._json(result)
            return
        if len(parts) == 3 and parts[0] == "api":
            action, arg = parts[1], parts[2]
            with lock:
                ok = False
                if action in ("toggle_plug", "toggle_plan", "fault"):
                    try:
                        sid = int(arg)
                    except ValueError:
                        self._json(dict(ok=False), 400)
                        return
                    if action == "toggle_plug":
                        ok = engine.toggle_plug(sid) is not None
                    elif action == "toggle_plan":
                        ok = engine.toggle_plan(sid) is not None
                    else:
                        ok = engine.inject_fault(sid)
                elif action == "mode" and arg in MODES:
                    ok = engine.set_mode(arg)
                elif action == "speed":
                    try:
                        if int(arg) in SPEEDS:
                            set_speed(int(arg))
                            ok = True
                    except ValueError:
                        ok = False
                elif action == "set_hour":
                    try:
                        engine.jump_to_hour(float(arg))
                        ok = True
                    except ValueError:
                        ok = False
            self._json(dict(ok=ok))
            return
        if parts == ["api", "reset"]:
            with lock:
                engine.reset()
            self._json(dict(ok=True))
            return
        self._send(404, "not found")


def open_browser_later():
    time.sleep(0.8)
    try:
        webbrowser.open(f"http://localhost:{PORT}")
    except Exception:
        pass


def main():
    threading.Thread(target=loop, daemon=True).start()
    if not os.environ.get("NO_BROWSER"):
        threading.Thread(target=open_browser_later, daemon=True).start()
    print(f"ReCarga rodando em http://localhost:{PORT}  (Ctrl+C para parar)")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
