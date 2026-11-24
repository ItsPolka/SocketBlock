"""Coordinación de minería, consenso, sincronización y chat del salón."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from .chain import Blockchain
from .mining import Miner
from .models import (MAX_CHAT_LENGTH, Block, Consensus, is_integer, mining_template,
                     now_ms, valid_address, valid_name)
from .network import Network, Peer, format_endpoint, parse_endpoint
from .storage import DataLock, load_identity

SYNC_BATCH = 100
MAX_ORPHANS = 256


class Node:
    def __init__(
        self, *, data_dir: Path, name: str | None = None, host: str = "0.0.0.0",
        port: int = 6000, advertise: str | None = None, consensus: Consensus | None = None,
        workers: int = 1, emit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        if not is_integer(workers, 1, 64):
            raise ValueError("El número de procesos de minería debe estar entre 1 y 64")
        self.data_dir = data_dir
        self.lock = DataLock(data_dir)
        try:
            self.identity = load_identity(data_dir, name)
            self.chain = Blockchain(consensus or Consensus(), data_dir / "chain.sqlite3")
        except BaseException:
            self.lock.close()
            raise
        self.emit = emit or (lambda _event, _data: None)
        self.miner = Miner(workers)
        self.network = Network(
            self.identity, self.chain.consensus.network_id, host, port, advertise,
            lambda: (self.chain.head.hash, self.chain.head.height),
            self._on_message, self._on_peer, self.emit,
        )
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.orphans: OrderedDict[str, Block] = OrderedDict()
        self.pending_sync: dict[str, tuple[str, float]] = {}
        self.mining_session: dict[str, Any] | None = None
        self.tasks: list[asyncio.Task[Any]] = []
        self.closing = False
        self.closed = False

    async def start(self, seeds: list[tuple[str, int]] | None = None, *, mine: bool = False) -> None:
        saved = []
        path = self.data_dir / "peers.json"
        if path.exists():
            try:
                values = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(values, list) or len(values) > 256:
                    raise ValueError("Lista de pares guardada inválida")
                saved = [parse_endpoint(value) for value in values]
            except (ValueError, TypeError, OSError) as exc:
                self.emit("error", {"message": f"No se pudieron recuperar pares: {exc}"})
        await self.network.start(list(dict.fromkeys((seeds or []) + saved)))
        self.tasks = [asyncio.create_task(self._mine_loop()), asyncio.create_task(self._sync_loop())]
        if mine:
            self.start_mining()
        self.emit("ready", self.status())

    def _remember_message(self, message_id: str) -> bool:
        if message_id in self.seen:
            return False
        self.seen[message_id] = None
        if len(self.seen) > 10_000:
            self.seen.popitem(last=False)
        return True

    def start_mining(self) -> None:
        already_running = self.miner.running
        self.miner.start(mining_template(self.chain.head, self.chain.consensus, self.identity.address, self.identity.name))
        if not already_running:
            self.emit("mining_started", {"height": self.chain.head.height + 1, "workers": self.miner.workers})

    def start_classroom(self) -> None:
        message = dict(type="mining_start", id=uuid.uuid4().hex, timestamp=now_ms(),
                       sender=self.identity.address, name=self.identity.name)
        self._remember_message(message["id"])
        self.start_mining()
        self.mining_session = message
        self.network.broadcast(message)
        self.emit("classroom_started", {"name": self.identity.name})

    def pause_mining(self) -> None:
        self.mining_session = None
        self.miner.stop()
        self.emit("mining_paused", {})

    def chat(self, text: str) -> None:
        if not isinstance(text, str) or not 1 <= len(text) <= MAX_CHAT_LENGTH or not text.isprintable() or not text.strip():
            raise ValueError(f"El mensaje debe tener entre 1 y {MAX_CHAT_LENGTH} caracteres imprimibles")
        message = dict(type="chat", id=uuid.uuid4().hex, sender=self.identity.address,
                       name=self.identity.name, timestamp=now_ms(), text=text)
        self._remember_message(message["id"])
        self.network.broadcast(message)
        self.emit("chat", {**message, "local": True})

    async def _on_peer(self, peer: Peer) -> None:
        self._request_sync(peer)
        if self.mining_session and self.miner.running:
            peer.send(self.mining_session)

    def _request_sync(self, peer: Peer) -> None:
        pending = self.pending_sync.get(peer.address)
        if pending and time.monotonic() - pending[1] < 10:
            return
        request_id = uuid.uuid4().hex
        self.pending_sync[peer.address] = (request_id, time.monotonic())
        peer.send(dict(type="get_blocks", request_id=request_id, locator=self.chain.locator()))

    @staticmethod
    def _validate_gossip(message: dict[str, Any]) -> None:
        if not isinstance(message.get("id"), str) or len(message["id"]) != 32 or any(c not in "0123456789abcdef" for c in message["id"]):
            raise ValueError("ID de mensaje inválido")
        if not valid_address(message.get("sender")) or not valid_name(message.get("name")):
            raise ValueError("Remitente inválido")
        if not is_integer(message.get("timestamp"), 0, now_ms() + 120_000):
            raise ValueError("Fecha de mensaje inválida")

    async def _on_message(self, peer: Peer, message: dict[str, Any]) -> None:
        kind = message["type"]
        if kind in ("chat", "mining_start"):
            self._validate_gossip(message)
            if kind == "chat":
                text = message.get("text")
                if not isinstance(text, str) or not 1 <= len(text) <= MAX_CHAT_LENGTH or not text.isprintable() or not text.strip():
                    raise ValueError("Texto de chat inválido")
            if not self._remember_message(message["id"]):
                return
            self.network.broadcast(message, exclude=peer.address)
            if kind == "chat":
                self.emit("chat", {**message, "local": False})
            else:
                self.start_mining()
                self.mining_session = message
                self.emit("classroom_started", {"name": message["name"]})
        elif kind == "block":
            block = Block.from_dict(message.get("block"))
            self._accept_block(block, source=peer)
            self._drain_orphans()
        elif kind == "head":
            self._update_peer_head(peer, message)
            if peer.head_hash not in self.chain.blocks:
                self._request_sync(peer)
        elif kind == "get_blocks":
            locator = message.get("locator")
            if not isinstance(locator, list) or not 1 <= len(locator) <= 128 or not all(valid_address(h) for h in locator):
                raise ValueError("Localizador de cadena inválido")
            request_id = message.get("request_id")
            if not isinstance(request_id, str) or len(request_id) != 32:
                raise ValueError("Solicitud de cadena inválida")
            peer.send(dict(type="blocks", request_id=request_id,
                           blocks=self.chain.after_locator(locator, SYNC_BATCH),
                           head_hash=self.chain.head.hash, height=self.chain.head.height))
        elif kind == "blocks":
            pending = self.pending_sync.get(peer.address)
            if not pending or message.get("request_id") != pending[0]:
                return
            del self.pending_sync[peer.address]
            blocks = message.get("blocks")
            if not isinstance(blocks, list) or len(blocks) > SYNC_BATCH:
                raise ValueError("Lote de bloques inválido")
            self._update_peer_head(peer, message)
            progress = False
            for data in blocks:
                block = Block.from_dict(data)
                if block.previous_hash not in self.chain.blocks:
                    raise ValueError("La cadena recibida está incompleta")
                progress = self._accept_block(block, source=peer, relay=False) or progress
            self._drain_orphans()
            if blocks:
                self.emit("sync", {"name": peer.name, "received": len(blocks), "height": self.chain.head.height, "hash": self.chain.head.hash})
            if progress and peer.head_hash not in self.chain.blocks:
                self._request_sync(peer)
        else:
            raise ValueError(f"Tipo de mensaje no soportado: {kind[:40]!r}")

    @staticmethod
    def _update_peer_head(peer: Peer, message: dict[str, Any]) -> None:
        if not valid_address(message.get("head_hash")) or not is_integer(message.get("height"), 0, 2**53 - 1):
            raise ValueError("Anuncio de cadena inválido")
        peer.head_hash, peer.height = message["head_hash"], message["height"]

    def _accept_block(self, block: Block, source: Peer | None = None, *, relay: bool = True) -> bool:
        previous = self.chain.head
        result = self.chain.add(block)
        if result.missing_parent:
            self.orphans[block.hash] = block
            if len(self.orphans) > MAX_ORPHANS:
                self.orphans.popitem(last=False)
            if source:
                self._request_sync(source)
            return False
        if not result.accepted:
            return False
        if relay:
            self.network.broadcast({"type": "block", "block": block.to_dict()}, exclude=source.address if source else None)
        if result.head_changed:
            # Publicar un trabajo nuevo sustituye el del bloque anterior en todos
            # los procesos. El hilo de red sigue atendiendo chat y sincronización.
            self.miner.submit(mining_template(self.chain.head, self.chain.consensus, self.identity.address, self.identity.name))
            self.network.broadcast(self._head_message())
            self.emit("winner", dict(
                height=block.height, hash=block.hash, name=block.miner_name, address=block.miner,
                reward=block.reward, local=block.miner == self.identity.address,
                reorganization=result.reorganization, previous_hash=previous.hash,
                balance=self.chain.balance(self.identity.address), mining=self.miner.running,
            ))
        else:
            self.emit("fork", {"height": block.height, "hash": block.hash, "name": block.miner_name})
        return True

    def _drain_orphans(self) -> None:
        progress = True
        while progress:
            progress = False
            for block_hash, block in list(self.orphans.items()):
                if block.previous_hash in self.chain.blocks:
                    del self.orphans[block_hash]
                    try:
                        self._accept_block(block)
                    except ValueError as exc:
                        self.emit("error", {"message": f"Bloque huérfano descartado: {exc}"})
                    progress = True

    def _head_message(self) -> dict[str, Any]:
        return dict(type="head", head_hash=self.chain.head.hash, height=self.chain.head.height)

    async def _mine_loop(self) -> None:
        last_refresh = time.monotonic()
        while not self.closing:
            if self.miner.running:
                for data in self.miner.poll():
                    block = Block.from_dict(data)
                    # Un resultado que cruzó un aviso de ganador ya no participa.
                    if block.previous_hash == self.chain.head.hash:
                        self._accept_block(block)
                    self.miner.submit(mining_template(self.chain.head, self.chain.consensus, self.identity.address, self.identity.name))
                if time.monotonic() - last_refresh >= 2:
                    self.miner.submit(mining_template(self.chain.head, self.chain.consensus, self.identity.address, self.identity.name))
                    last_refresh = time.monotonic()
                if any(not process.is_alive() for process in self.miner.processes):
                    self.pause_mining()
                    self.emit("error", {"message": "Un proceso de minería terminó. Usa /minar para reiniciarlo"})
            await asyncio.sleep(0.05)

    async def _sync_loop(self) -> None:
        while not self.closing:
            self.network.broadcast(self._head_message())
            for peer in list(self.network.peers.values()):
                if peer.head_hash not in self.chain.blocks:
                    self._request_sync(peer)
            await asyncio.sleep(5)

    def status(self) -> dict[str, Any]:
        return dict(
            name=self.identity.name, address=self.identity.address, host=self.network.host,
            port=self.network.port, network=self.chain.consensus.network,
            network_id=self.chain.consensus.network_id, difficulty=self.chain.consensus.difficulty,
            reward=self.chain.consensus.reward, peers=len(self.network.peers),
            users=len(self.network.peers) + 1, height=self.chain.head.height, hash=self.chain.head.hash,
            balance=self.chain.balance(self.identity.address),
            confirmed_balance=self.chain.balance(self.identity.address, confirmations=6),
            mining=self.miner.running, workers=self.miner.workers,
            known_blocks=len(self.chain.blocks), data_dir=str(self.data_dir.resolve()),
        )

    def users(self) -> list[dict[str, Any]]:
        return [dict(name=self.identity.name, address=self.identity.address, endpoint=f"local:{self.network.port}",
                     height=self.chain.head.height, hash=self.chain.head.hash, local=True)] + [
            dict(name=p.name, address=p.address, endpoint=format_endpoint(p.endpoint), height=p.height,
                 hash=p.head_hash, local=False) for p in sorted(self.network.peers.values(), key=lambda p: (p.name, p.address))
        ]

    async def close(self) -> None:
        if self.closed:
            return
        self.closing = True
        try:
            endpoints = [format_endpoint(endpoint) for endpoint in self.network.candidates]
            temporary = self.data_dir / "peers.tmp"
            temporary.write_text(json.dumps(endpoints, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.data_dir / "peers.json")
        except OSError as exc:
            self.emit("error", {"message": f"No se pudieron guardar los pares: {exc}"})
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.network.close()
        self.miner.close()
        self.chain.close()
        self.lock.close()
        self.closed = True
