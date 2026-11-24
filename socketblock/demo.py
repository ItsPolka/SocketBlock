"""Demostración reproducible del salón en una sola computadora.

Ejecutar: python -m socketblock.demo --nodes 20 --blocks 5
Cada nodo tiene identidad, cadena y puerto TCP propios; cada minero es un proceso.
"""

from __future__ import annotations

import argparse
import asyncio
import multiprocessing
import tempfile
import time
from pathlib import Path
from typing import Callable

from .models import Consensus
from .node import Node


async def wait_for(condition: Callable[[], bool], description: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.1)
    raise RuntimeError(f"Se agotó el tiempo esperando: {description}")


async def demonstrate(count: int, blocks: int, difficulty: int, timeout: float) -> None:
    nodes: list[Node] = []
    chats: set[int] = set()
    reported: set[str] = set()

    def event(index, kind, data):
        if kind == "chat":
            chats.add(index)
        elif kind == "winner" and data["hash"] not in reported:
            reported.add(data["hash"])
            print(f"  Bloque #{data['height']}: {data['name']} | {data['hash']}", flush=True)

    with tempfile.TemporaryDirectory(prefix="socketblock-demo-") as directory:
        try:
            print(f"Creando {count} nodos con sockets TCP independientes...", flush=True)
            for index in range(count):
                node = Node(data_dir=Path(directory) / str(index), name=f"Alumno {index + 1:02}",
                            host="127.0.0.1", port=0, consensus=Consensus(difficulty=difficulty),
                            emit=lambda kind, data, i=index: event(i, kind, data))
                nodes.append(node)
                await node.start([("127.0.0.1", nodes[0].network.port)] if index else [])
            await wait_for(lambda: all(len(n.network.peers) == count - 1 for n in nodes), "descubrimiento de todos los pares", timeout)
            print(f"OK: {count}/{count} usuarios; cada uno ve {count - 1} pares.", flush=True)
            nodes[0].chat("El salón está conectado y listo para minar")
            await wait_for(lambda: len(chats) == count, "distribución del chat", timeout)
            print(f"OK: chat recibido en los {count} nodos, sin servidor central.", flush=True)
            nodes[0].start_classroom()
            await wait_for(lambda: all(n.miner.running for n in nodes), "inicio de todos los mineros", timeout)
            print(f"OK: {count} mineros activos al mismo tiempo.", flush=True)
            await wait_for(lambda: all(n.chain.head.height >= blocks for n in nodes), f"{blocks} bloques", timeout)
            # Pausa local para comparar una instantánea inmóvil de las cadenas.
            for node in nodes:
                node.pause_mining()
            await wait_for(lambda: len({n.chain.head.hash for n in nodes}) == 1, "convergencia de la cadena", timeout)
            first = nodes[0]
            if not all(n.chain.main_hashes == first.chain.main_hashes and n.chain.balances == first.chain.balances for n in nodes):
                raise RuntimeError("Las cadenas o los saldos difieren")
            if sum(first.chain.balances.values()) != first.chain.head.height * first.chain.consensus.reward:
                raise RuntimeError("La emisión de leonelcoin no coincide con las recompensas")
            print(f"OK: {count}/{count} cadenas y saldos idénticos en altura {first.chain.head.height}.", flush=True)
            print(f"Hash final: {first.chain.head.hash}", flush=True)
            print(f"Leonelcoin emitidas: {sum(first.chain.balances.values())}", flush=True)
            print("Demostración completada. Los datos temporales se eliminan al cerrar.", flush=True)
        finally:
            for node in reversed(nodes):
                await node.close()


def main() -> None:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=20)
    parser.add_argument("--blocks", type=int, default=5)
    parser.add_argument("--difficulty", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if not 2 <= args.nodes <= 20 or not 1 <= args.blocks <= 1000 or args.timeout <= 0:
        parser.error("Usa 2 a 20 nodos, 1 a 1000 bloques y un timeout positivo")
    try:
        Consensus(difficulty=args.difficulty)
        asyncio.run(demonstrate(args.nodes, args.blocks, args.difficulty, args.timeout))
    except (RuntimeError, OSError, ValueError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
