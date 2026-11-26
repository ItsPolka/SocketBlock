"""PoW en procesos independientes; el bucle de sockets nunca busca nonces."""

from __future__ import annotations

import asyncio
import hashlib
import multiprocessing as mp
import queue
import secrets
import time
from typing import Any

from .models import canonical_json, hash_target, now_ms


def _worker(template: dict[str, Any], results: Any, stop: Any) -> None:
    target = hash_target(template["difficulty"])
    nonce = secrets.randbits(64)
    while not stop.is_set():
        timestamp = max(template["started_at"], now_ms())
        # El orden canónico coloca nonce entre miner_name y offer.
        encoded = canonical_json({**template, "timestamp": timestamp})
        prefix, suffix = encoded.split(b'"nonce":0', 1)
        prefix += b'"nonce":'
        for _ in range(2048):
            digest = hashlib.sha256(prefix + str(nonce).encode("ascii") + suffix).hexdigest()
            if digest <= target:
                results.put({**template, "timestamp": timestamp, "nonce": nonce, "hash": digest})
                return
            nonce = (nonce + 1) & (2**64 - 1)


class Miner:
    def __init__(self, workers: int = 1) -> None:
        self.workers = workers
        self.processes: list[Any] = []
        self.ctx = mp.get_context("spawn")
        self.results: Any = None
        self.stop_event: Any = None
        self.cleanup: set[asyncio.Task[None]] = set()
        self.running = False

    def start(self, template: dict[str, Any]) -> None:
        self.stop_event = self.ctx.Event()
        self.results = self.ctx.Queue(maxsize=self.workers)
        try:
            for index in range(self.workers):
                process = self.ctx.Process(target=_worker, args=(template, self.results, self.stop_event),
                                           name=f"pow-{index + 1}", daemon=True)
                process.start()
                self.processes.append(process)
            self.running = True
        except BaseException:
            self.stop()
            raise

    def poll(self) -> dict[str, Any] | None:
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

    def stop(self) -> None:
        self.running = False
        if self.stop_event is None:
            return
        self.stop_event.set()
        # La señal detiene la búsqueda en el siguiente lote. Recogemos los
        # procesos fuera del bucle de sockets para difundir el ganador enseguida.
        cleanup = asyncio.create_task(asyncio.to_thread(self._join, self.processes, self.results, self.stop_event))
        self.cleanup.add(cleanup)
        cleanup.add_done_callback(self.cleanup.discard)
        self.processes = []
        self.results = self.stop_event = None

    @staticmethod
    def _join(processes: list[Any], results: Any, _stop_event: Any) -> None:
        # Conserva el semáforo mientras los hijos que siguen arrancando lo abren.
        deadline = time.monotonic() + 3
        for process in processes:
            process.join(timeout=max(0, deadline - time.monotonic()))
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
        results.close()

    async def close(self) -> None:
        self.stop()
        await asyncio.gather(*self.cleanup)
