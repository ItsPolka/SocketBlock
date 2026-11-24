"""PoW en procesos independientes; el bucle de sockets nunca busca nonces."""

from __future__ import annotations

import hashlib
import multiprocessing as mp
import queue
import secrets
import time
from typing import Any

from .models import canonical_json


def _worker(jobs: Any, results: Any, stop: Any) -> None:
    template = None
    while not stop.is_set():
        if template is None:
            try:
                template = jobs.get(timeout=0.25)
            except queue.Empty:
                continue
        else:
            try:
                template = jobs.get_nowait()
            except queue.Empty:
                pass
        if template is None:
            continue
        # El orden canónico coloca nonce entre miner_name y previous_hash.
        # Serializar solo el nonce por intento reduce trabajo repetido.
        encoded = canonical_json({**template, "nonce": 0})
        prefix, suffix = encoded.split(b'"nonce":0', 1)
        prefix += b'"nonce":'
        target = "0" * template["difficulty"]
        nonce = secrets.randbits(64)
        # Un lote pequeño permite cambiar de punta rápidamente al recibir bloques.
        for _ in range(2048):
            digest = hashlib.sha256(prefix + str(nonce).encode("ascii") + suffix).hexdigest()
            if digest.startswith(target):
                block = {**template, "nonce": nonce, "hash": digest}
                try:
                    results.put_nowait(block)
                except queue.Full:
                    pass
                template = None
                break
            nonce = (nonce + 1) & (2**64 - 1)


class Miner:
    def __init__(self, workers: int = 1) -> None:
        self.workers = workers
        self.processes: list[Any] = []
        self.jobs: list[Any] = []
        self.ctx = mp.get_context("spawn")
        self.results = self.ctx.Queue(maxsize=max(4, workers * 2))
        self.stop_event = self.ctx.Event()
        self.running = False
        self.started_at: float | None = None
        self.latest_template: dict[str, Any] | None = None

    def start(self, template: dict[str, Any]) -> None:
        if self.running:
            self.submit(template)
            return
        self.stop_event.clear()
        try:
            for index in range(self.workers):
                jobs = self.ctx.Queue(maxsize=2)
                process = self.ctx.Process(target=_worker, args=(jobs, self.results, self.stop_event), name=f"pow-{index + 1}", daemon=True)
                self.jobs.append(jobs)
                process.start()
                self.processes.append(process)
            self.running = True
            self.started_at = time.monotonic()
            self.submit(template)
        except BaseException:
            self.stop()
            raise

    def submit(self, template: dict[str, Any]) -> None:
        self.latest_template = template
        if not self.running:
            return
        for jobs in self.jobs:
            # Drena trabajos anteriores. Queue usa un feeder; si aún no están
            # visibles, el último trabajo se encola detrás y sustituye al anterior.
            while True:
                try:
                    jobs.get_nowait()
                except queue.Empty:
                    break
            try:
                jobs.put_nowait(template)
            except queue.Full:
                # La siguiente iteración del coordinador vuelve a intentarlo.
                pass

    def poll(self) -> list[dict[str, Any]]:
        found = []
        while True:
            try:
                found.append(self.results.get_nowait())
            except queue.Empty:
                return found

    def stop(self) -> None:
        self.running = False
        self.stop_event.set()
        deadline = time.monotonic() + 3
        for process in self.processes:
            process.join(timeout=max(0, deadline - time.monotonic()))
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
        for jobs in self.jobs:
            jobs.cancel_join_thread()
            jobs.close()
        self.jobs.clear()
        self.processes.clear()
        self.poll()

    def close(self) -> None:
        self.stop()
        self.results.cancel_join_thread()
        self.results.close()
