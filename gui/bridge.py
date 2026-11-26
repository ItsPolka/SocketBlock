"""Puente entre un nodo SocketBlock y el navegador.

Arranca el nodo con --json, lee sus eventos línea por línea y los reenvía al
front por Server-Sent Events (/api/events). Los botones del front llegan por
POST /api/cmd y se escriben en la entrada estándar del nodo.

Solo escucha en 127.0.0.1: el control del nodo no queda expuesto a la red.

Uso:
  python3 gui/bridge.py --name Ana --advertise 192.168.1.11 --peer 192.168.1.10:6000
Luego abre http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "web" / "dist"
ALLOWED = {"/minar", "/pausar", "/iniciar", "/conectar", "/estado", "/usuarios",
           "/ofrecer", "/ofertas", "/mensaje", "/decir"}
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
         ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2"}


class Bridge:
    def __init__(self, command: list[str], cwd: Path) -> None:
        self.lock = threading.Lock()
        self.clients: list[queue.Queue[str]] = []
        self.status: dict | None = None
        self.users: list = []
        self.blocks: list[dict] = []
        self.chain_hash: str | None = None
        self.offers: list[dict] = []
        self.input_lock = threading.Lock()
        self.log: deque[dict] = deque(maxlen=150)
        self.proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._poll, daemon=True).start()

    # ---- nodo ----
    def send(self, line: str) -> None:
        with self.input_lock:
            if self.proc.poll() is None and self.proc.stdin:
                try:
                    self.proc.stdin.write(line.strip() + "\n")
                    self.proc.stdin.flush()
                except OSError:
                    pass

    def _poll(self) -> None:
        while self.proc.poll() is None:
            self.send("/estado")
            self.send("/usuarios")
            self.send("/ofertas")
            with self.lock:
                chain_changed = self.status is not None and self.status["hash"] != self.chain_hash
            if chain_changed:
                self.send("/cadena todo")
            time.sleep(1.5)

    def _read(self) -> None:
        assert self.proc.stdout
        for raw in self.proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                event = {"event": "log", "text": raw}
                print(f"[nodo] {raw}", flush=True)
            event["ts"] = time.time()
            if event.get("event") == "chain":
                for block in event["blocks"]:
                    block["nonce"] = str(block["nonce"])
            elif event.get("event") == "winner":
                event["block"]["nonce"] = str(event["block"]["nonce"])
            self.publish(event)
        code = self.proc.wait()
        self.publish({"event": "node_exit", "code": code, "ts": time.time()})
        print(f"El nodo terminó (código {code}). Cerrando la interfaz.", flush=True)
        time.sleep(0.5)
        import os
        os._exit(code or 1)

    def _absorb(self, event: dict) -> None:
        kind = event.get("event")
        if kind in ("status", "ready"):
            self.status = {k: v for k, v in event.items() if k not in ("event", "ts")}
        elif kind == "users":
            self.users = event["users"]
        elif kind == "chain":
            self.blocks = event["blocks"]
            self.chain_hash = event["hash"]
        elif kind == "offers":
            self.offers = event["offers"]
        elif kind != "response":
            self.log.append(event)
            if kind == "offer":
                self.offers = [*self.offers, {key: event[key] for key in ("id", "author", "name", "text", "timestamp")}]
            elif kind == "winner":
                self.offers = [offer for offer in self.offers if offer["id"] != event["offer_id"]]
                if self.status is not None:
                    self.status.update(height=event["height"], hash=event["hash"], balance=event["balance"],
                                       mining=False, template=None, classroom=False)
            elif self.status is not None:
                if kind == "mining_started":
                    self.status.update(mining=True, template=event["template"])
                elif kind == "mining_paused":
                    self.status.update(mining=False, template=None)
                elif kind == "classroom_started":
                    self.status["classroom"] = True

    # ---- navegador ----
    def publish(self, event: dict) -> None:
        data = json.dumps(event, ensure_ascii=False)
        with self.lock:
            self._absorb(event)
            for client in list(self.clients):
                try:
                    client.put_nowait(data)
                except queue.Full:
                    self.clients.remove(client)

    def subscribe(self, client: queue.Queue[str]) -> str:
        with self.lock:
            self.clients.append(client)
            return json.dumps({"event": "snapshot", "status": self.status, "users": self.users,
                               "blocks": self.blocks, "offers": self.offers, "log": list(self.log)},
                              ensure_ascii=False)


def make_handler(bridge: Bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:
            if self.path == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                client: queue.Queue[str] = queue.Queue(maxsize=2000)
                try:
                    self.wfile.write(f"data: {bridge.subscribe(client)}\n\n".encode())
                    self.wfile.flush()
                    while True:
                        try:
                            data = client.get(timeout=15)
                            self.wfile.write(f"data: {data}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with bridge.lock:
                        if client in bridge.clients:
                            bridge.clients.remove(client)
                return
            path = self.path.split("?")[0]
            file = (DIST / path.lstrip("/")).resolve()
            if path == "/" or not file.is_file() or DIST not in file.parents:
                file = DIST / "index.html"
            if not file.exists():
                self.send_error(503, "Falta compilar el front: cd web && npm run build")
                return
            body = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", TYPES.get(file.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path != "/api/cmd":
                self.send_error(404)
                return
            if self.headers.get_content_type() != "application/json":
                self.send_error(415)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 1 <= length <= 32768:
                    raise ValueError("Tamaño inválido")
                raw = json.loads(self.rfile.read(length))["cmd"]
                if not isinstance(raw, str) or "\r" in raw or "\n" in raw:
                    raise ValueError("Comando inválido")
                line = raw.strip()
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
                return
            # Comandos permitidos, o texto de chat (sin /).
            if not line or (line.startswith("/") and line.split(maxsplit=1)[0] not in ALLOWED):
                self.send_error(400, "Comando no permitido")
                return
            bridge.send(line)
            self.send_response(204)
            self.end_headers()

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Interfaz web para un nodo SocketBlock")
    parser.add_argument("--repo", default=str(HERE.parent), help="Carpeta del repo socketblock")
    parser.add_argument("--ui-port", type=int, default=8765)
    args, node_args = parser.parse_known_args()
    command = [sys.executable, "-m", "socketblock", "--json", *node_args]
    bridge = Bridge(command, Path(args.repo))
    server = ThreadingHTTPServer(("127.0.0.1", args.ui_port), make_handler(bridge))
    server.daemon_threads = True
    print(f"Interfaz lista en http://127.0.0.1:{args.ui_port}  (Ctrl+C para salir)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.send("/salir")
        try:
            bridge.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            bridge.proc.terminate()


if __name__ == "__main__":
    main()
