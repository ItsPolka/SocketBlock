"""Terminal en español para operar un nodo en Windows, Linux o macOS."""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import __version__
from .models import Consensus, valid_address
from .network import parse_endpoint, valid_advertised_host
from .node import Node

HELP = """Comandos:
  /iniciar                 Inicia la minería en TODOS los nodos conectados
  /minar                   Inicia o reanuda solamente tu minería
  /pausar                  Pausa solamente tu minería; sigues recibiendo bloques
  /usuarios (o /pares)      Muestra usuarios, direcciones, alturas y hashes
  /estado                  Muestra tu cadena, saldo, conexiones y configuración
  /verificar               Compara tu hash con el último anunciado por cada par
  /saldo [direccion]       Saldo de leonelcoin en la cadena principal
  /cadena [cantidad]       Últimos bloques (10 por defecto, máximo 100)
  /ganadores [cantidad]    Últimos ganadores y recompensas
  /conectar IP:PUERTO      Agrega un par sin reiniciar
  /ayuda                   Muestra estos comandos
  /salir                   Guarda y cierra el nodo
Escribe cualquier texto sin / para enviarlo al chat del salón."""


class Console:
    def __init__(self, json_output: bool = False) -> None:
        self.json_output = json_output

    def emit(self, event: str, data: dict[str, Any]) -> None:
        if self.json_output:
            print(json.dumps({"event": event, **data}, ensure_ascii=True), flush=True)
            return
        text = ""
        if event == "ready":
            text = (f"SocketBlock {__version__} | {data['name']} | TCP {data['host']}:{data['port']}\n"
                    f"Dirección: {data['address']}\n"
                    f"Red: {data['network']} | PoW: {data['difficulty']} ceros | Premio: {data['reward']} leonelcoin\n"
                    f"Cadena #{data['height']}: {data['hash']}\n"
                    "Usa /usuarios para ver al salón, /iniciar para minar juntos y /ayuda para los comandos.")
        elif event == "peer_connected":
            text = f"Conectado: {data['name']} ({data['endpoint']}) | {data['peers']} pares + tú"
        elif event == "peer_disconnected":
            text = f"Desconectado: {data['name']} | Quedan {data['peers']} pares"
        elif event == "chat":
            text = f"{data['name']}: {data['text']}"
        elif event == "mining_started":
            text = f"Minando bloque #{data['height']} con {data['workers']} proceso(s). Chat y red siguen disponibles."
        elif event == "mining_paused":
            text = "Minería local pausada. La cadena y el chat siguen sincronizándose."
        elif event == "classroom_started":
            text = f"{data['name']} inició la minería del salón."
        elif event == "winner":
            reorg = " | Cadena reorganizada; saldos recalculados" if data["reorganization"] else ""
            next_round = f" | Minando ahora #{data['height'] + 1}" if data["mining"] else ""
            text = (f"BLOQUE #{data['height']} | Ganador: {data['name']} | +{data['reward']} leonelcoin{reorg}\n"
                    f"Hash de la cadena: {data['hash']}\n"
                    f"Trabajo anterior cancelado | Tu saldo: {data['balance']} leonelcoin{next_round}")
        elif event == "fork":
            text = f"Bloque alternativo #{data['height']} de {data['name']} guardado; se aplica la regla de consenso."
        elif event == "sync":
            text = f"Sincronizados {data['received']} bloque(s) desde {data['name']}. Cadena local #{data['height']}: {data['hash']}"
        elif event == "connection_retry":
            text = f"Esperando a {data['endpoint']}; se reintentará automáticamente."
        elif event in ("error", "peer_error"):
            text = f"Aviso: {data['message']}"
        elif event == "response":
            text = data["text"]
        if text:
            print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


def handle_command(node: Node, line: str, console: Console) -> bool:
    """Devuelve False cuando se pide salir."""
    line = line.strip()
    if not line:
        return True
    if not line.startswith("/"):
        node.chat(line)
        return True
    parts = line.split()
    command, arguments = parts[0].lower(), parts[1:]
    text = ""
    if command == "/salir":
        return False
    if command in ("/ayuda", "/help"):
        text = HELP
    elif command == "/iniciar":
        node.start_classroom()
    elif command == "/minar":
        node.start_mining()
    elif command == "/pausar":
        node.pause_mining()
    elif command == "/estado":
        console.emit("status", node.status()) if console.json_output else console.emit(
            "response", {"text": json.dumps(node.status(), ensure_ascii=False, indent=2)})
    elif command in ("/usuarios", "/pares"):
        users = node.users()
        console.emit("users", {"users": users}) if console.json_output else console.emit("response", {"text":
            f"{len(users)}/20 usuarios visibles:\n" + "\n".join(
                f"{'TÚ' if u['local'] else 'PAR'} {u['name']} | {u['endpoint']} | #{u['height']} {u['hash'][:16]}\n  {u['address']}" for u in users)})
    elif command == "/verificar":
        users = node.users()
        agree = sum(u["hash"] == node.chain.head.hash for u in users[1:])
        text = (f"Cadena local #{node.chain.head.height}: {node.chain.head.hash}\n"
                f"{agree}/{len(users) - 1} pares conectados anuncian el mismo hash. "
                "Los anuncios se actualizan cada 5 segundos; para una foto estable usa /pausar en todos los nodos.")
        if len(users) == 1:
            text += "\nTodavía no hay pares: falta conectar al salón."
    elif command == "/saldo":
        if len(arguments) > 1:
            raise ValueError("Uso: /saldo [direccion]")
        address = arguments[0] if arguments else node.identity.address
        if not valid_address(address):
            raise ValueError("La dirección debe tener 64 caracteres hexadecimales")
        text = (f"{address}\nSaldo: {node.chain.balance(address)} leonelcoin\n"
                f"Con 6 confirmaciones: {node.chain.balance(address, 6)} leonelcoin")
    elif command in ("/cadena", "/ganadores"):
        if len(arguments) > 1:
            raise ValueError(f"Uso: {command} [cantidad]")
        try:
            count = int(arguments[0]) if arguments else 10
        except ValueError as exc:
            raise ValueError("La cantidad debe ser un entero entre 1 y 100") from exc
        if not 1 <= count <= 100:
            raise ValueError("La cantidad debe estar entre 1 y 100")
        blocks = node.chain.recent(count)
        if console.json_output:
            console.emit("chain", {"blocks": [b.to_dict() for b in blocks], "height": node.chain.head.height, "hash": node.chain.head.hash})
        else:
            text = "\n".join(f"#{b.height} | {b.miner_name} | +{b.reward} leonelcoin | nonce={b.nonce}\n  Hash: {b.hash}\n  Padre: {b.previous_hash}" for b in blocks)
            if not blocks:
                text = f"Solo existe el génesis: {node.chain.head.hash}"
    elif command == "/conectar":
        if len(arguments) != 1:
            raise ValueError("Uso: /conectar IP:PUERTO")
        node.network.connect(parse_endpoint(arguments[0]))
        text = f"Par agregado: {arguments[0]}. Conectando..."
    else:
        raise ValueError("Comando desconocido. Usa /ayuda")
    if text:
        console.emit("response", {"text": text})
    return True


def read_input(loop: asyncio.AbstractEventLoop, inbox: asyncio.Queue[str | None]) -> None:
    def enqueue(value: str | None) -> bool:
        try:
            loop.call_soon_threadsafe(inbox.put_nowait, value)
            return True
        except RuntimeError:
            return False
    try:
        for line in sys.stdin:
            if not enqueue(line):
                return
    except (OSError, UnicodeError):
        pass
    enqueue(None)


async def run(args: argparse.Namespace) -> None:
    console = Console(args.json)
    consensus = Consensus(network=args.network, difficulty=args.difficulty, reward=args.reward)
    if args.advertise and not valid_advertised_host(args.advertise):
        raise ValueError("--advertise requiere una IP o DNS accesible a los demás nodos")
    seeds = [parse_endpoint(value) for value in args.peer]
    node = Node(data_dir=Path(args.data_dir), name=args.name, host=args.host,
                port=args.port, advertise=args.advertise, consensus=consensus,
                workers=args.workers, emit=console.emit)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stopped.set)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        await node.start(seeds, mine=args.mine)
        if args.no_input:
            await stopped.wait()
            return
        inbox: asyncio.Queue[str | None] = asyncio.Queue()
        threading.Thread(target=read_input, args=(loop, inbox), daemon=True, name="terminal").start()
        stop_waiter = asyncio.create_task(stopped.wait())
        try:
            while not stopped.is_set():
                line_waiter = asyncio.create_task(inbox.get())
                try:
                    done, _ = await asyncio.wait((line_waiter, stop_waiter), return_when=asyncio.FIRST_COMPLETED)
                    if stop_waiter in done:
                        break
                    line = line_waiter.result()
                    if line is None:
                        break
                    try:
                        if not handle_command(node, line, console):
                            break
                    except ValueError as exc:
                        console.emit("error", {"message": str(exc)})
                finally:
                    line_waiter.cancel()
                    await asyncio.gather(line_waiter, return_exceptions=True)
        finally:
            stop_waiter.cancel()
            await asyncio.gather(stop_waiter, return_exceptions=True)
    finally:
        await node.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nodo P2P de SocketBlock: chat TCP y minería de leonelcoin")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--name", help="Nombre visible del usuario; se guarda entre reinicios")
    parser.add_argument("--host", default="0.0.0.0", help="Interfaz donde escuchar (predeterminado: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=6000, help="Puerto TCP (predeterminado: 6000)")
    parser.add_argument("--advertise", help="IP o DNS que otros nodos pueden usar para conectarse a ti")
    parser.add_argument("--peer", action="append", default=[], metavar="IP:PUERTO", help="Par inicial; puedes repetir esta opción")
    parser.add_argument("--data-dir", default="data/default", help="Carpeta exclusiva para la identidad y cadena de este nodo")
    parser.add_argument("--network", default="leonelcoin-v1", help="Nombre de red; debe coincidir en todo el salón")
    parser.add_argument("--difficulty", type=int, default=6, help="Ceros hexadecimales del PoW (1 a 7, predeterminado: 6)")
    parser.add_argument("--reward", type=int, default=50, help="Premio por bloque en leonelcoin (predeterminado: 50)")
    parser.add_argument("--workers", type=int, default=1, help="Procesos de minería por nodo (predeterminado: 1)")
    parser.add_argument("--mine", action="store_true", help="Inicia tu minería local al arrancar")
    parser.add_argument("--no-input", action="store_true", help="Ejecuta hasta Ctrl+C sin leer comandos de stdin")
    parser.add_argument("--json", action="store_true", help="Emite eventos JSON por línea para automatización")
    return parser


def main() -> None:
    multiprocessing.freeze_support()
    parser = build_parser()
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port debe estar entre 1 y 65535")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")
