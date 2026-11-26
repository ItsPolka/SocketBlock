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
from .models import (MAX_CHAT_LENGTH, MAX_FUTURE_MS, ROUND_TARGET_MS, Block,
                     Consensus, Offer, hash_target, is_integer, mining_template,
                     now_ms, valid_address, valid_name, valid_text)
from .network import Network, Peer, format_endpoint, parse_endpoint
from .storage import DataLock, load_identity

SYNC_BATCH = 50
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
        self.rounds: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.template: dict[str, Any] | None = None
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
        self.emit("ready", self.status())
        if mine:
            try:
                self.start_mining()
            except ValueError as exc:
                self.emit("error", {"message": str(exc)})

    def _remember_message(self, message_id: str) -> bool:
        if message_id in self.seen:
            return False
        self.seen[message_id] = None
        if len(self.seen) > 10_000:
            self.seen.popitem(last=False)
        return True

    def _save_offer(self, offer: Offer, source: Peer | None = None) -> None:
        if not self.chain.add_offer(offer):
            return
        self.emit("offer", {"id": offer.id, **offer.to_dict()})
        self.network.broadcast(dict(type="offer", offer=offer.to_dict()), exclude=source.address if source else None)

    def propose(self, text: str) -> None:
        offer = Offer.from_dict(dict(author=self.identity.address, name=self.identity.name,
                                     text=text, timestamp=now_ms()))
        self._save_offer(offer)

    def _select_offer(self, offer_id: str | None) -> Offer:
        for pending in self.chain.pending_offers():
            if offer_id is None or pending["id"] == offer_id:
                return self.chain.offers[pending["id"]]
        if offer_id is not None:
            raise ValueError("No se encontró esa oferta pendiente")
        raise ValueError("No hay ofertas pendientes. Crea una con /ofrecer")

    def _new_round(self, offer: Offer) -> dict[str, Any]:
        return dict(
            type="mining_start", id=uuid.uuid4().hex,
            timestamp=max(now_ms(), self.chain.head.timestamp + 1, offer.timestamp),
            sender=self.identity.address, name=self.identity.name,
            previous_hash=self.chain.head.hash, offer=offer.to_dict(),
        )

    def _begin_round(self, message: dict[str, Any], offer: Offer) -> None:
        self.miner.stop()
        self.template = mining_template(
            self.chain.head, self.chain.consensus, self.identity.address, self.identity.name,
            offer, message["timestamp"], self.chain.next_difficulty(),
        )
        self.miner.start(self.template)
        self.emit("mining_started", {"height": self.template["height"], "workers": self.miner.workers,
                                     "template": self.template})

    def start_mining(self, offer_id: str | None = None) -> None:
        if self.miner.running:
            raise ValueError("Ya estás minando una oferta")
        classroom = self.rounds.get(self.chain.head.hash)
        if classroom:
            offer = Offer.from_dict(classroom["offer"])
            if offer_id is not None and offer_id != offer.id:
                raise ValueError("El salón ya está minando otra oferta")
            self._begin_round(classroom, offer)
            return
        offer = self._select_offer(offer_id)
        self._begin_round(self._new_round(offer), offer)

    def start_classroom(self, offer_id: str | None = None) -> None:
        if self.chain.head.hash in self.rounds:
            raise ValueError("Ya hay una ronda del salón en curso")
        offer = self._select_offer(offer_id)
        message = self._new_round(offer)
        self._remember_message(message["id"])
        self.rounds[self.chain.head.hash] = message
        self._join_classroom()
        self.network.broadcast(message)

    def _join_classroom(self) -> None:
        message = self.rounds.get(self.chain.head.hash)
        if message is None:
            return
        offer = Offer.from_dict(message["offer"])
        if offer.id in self.chain.main_offer_ids or message["timestamp"] <= self.chain.head.timestamp:
            self.rounds.pop(self.chain.head.hash)
            return
        self._begin_round(message, offer)
        self.emit("classroom_started", {"name": message["name"], "offer": offer.text})

    def _stop_mining(self) -> None:
        self.miner.stop()
        self.template = None

    def pause_mining(self) -> None:
        self._stop_mining()
        self.emit("mining_paused", {})

    def chat(self, text: str, recipient: str | None = None) -> None:
        if not valid_text(text, MAX_CHAT_LENGTH):
            raise ValueError(f"El mensaje debe tener entre 1 y {MAX_CHAT_LENGTH} caracteres imprimibles")
        message = dict(type="chat", id=uuid.uuid4().hex, sender=self.identity.address,
                       name=self.identity.name, timestamp=now_ms(), text=text)
        if recipient is None:
            self._remember_message(message["id"])
            self.network.broadcast(message)
            self.emit("chat", {**message, "local": True})
            return
        peer = self.network.peers.get(recipient)
        if not peer:
            matches = [p for p in self.network.peers.values() if p.name.casefold() == recipient.casefold()]
            if len(matches) != 1:
                raise ValueError("Indica el nombre único o la dirección de un usuario conectado")
            peer = matches[0]
        message.update(type="direct_chat", recipient=peer.address)
        self._remember_message(message["id"])
        peer.send(message)
        self.emit("chat", {**message, "recipient_name": peer.name, "local": True})

    async def _on_peer(self, peer: Peer) -> None:
        self._request_sync(peer)
        peer.send(dict(type="get_offers", after=""))
        classroom = self.rounds.get(self.chain.head.hash)
        if classroom:
            peer.send(classroom)

    def _request_sync(self, peer: Peer, continuation: str | None = None) -> None:
        pending = self.pending_sync.get(peer.address)
        if pending and time.monotonic() - pending[1] < 10:
            return
        request_id = uuid.uuid4().hex
        self.pending_sync[peer.address] = (request_id, time.monotonic())
        locator = self.chain.locator()
        if continuation:
            locator.insert(0, continuation)
        peer.send(dict(type="get_blocks", request_id=request_id, locator=locator))

    @staticmethod
    def _validate_gossip(message: dict[str, Any]) -> None:
        if not isinstance(message.get("id"), str) or len(message["id"]) != 32 or any(c not in "0123456789abcdef" for c in message["id"]):
            raise ValueError("ID de mensaje inválido")
        if not valid_address(message.get("sender")) or not valid_name(message.get("name")):
            raise ValueError("Remitente inválido")
        if not is_integer(message.get("timestamp"), 0, now_ms() + MAX_FUTURE_MS):
            raise ValueError("Fecha de mensaje inválida")

    async def _on_message(self, peer: Peer, message: dict[str, Any]) -> None:
        kind = message["type"]
        if kind in ("chat", "direct_chat"):
            self._validate_gossip(message)
            if not valid_text(message.get("text"), MAX_CHAT_LENGTH):
                raise ValueError("Texto de chat inválido")
            payload = {key: message[key] for key in ("type", "id", "sender", "name", "timestamp", "text")}
            if kind == "direct_chat":
                if message.get("recipient") != self.identity.address or message["sender"] != peer.address:
                    raise ValueError("Remitente o destinatario de chat directo inválido")
                payload.update(name=peer.name, recipient=self.identity.address, recipient_name=self.identity.name)
            if self._remember_message(payload["id"]):
                if kind == "chat":
                    self.network.broadcast(payload, exclude=peer.address)
                self.emit("chat", {**payload, "local": False})
        elif kind == "offer":
            self._save_offer(Offer.from_dict(message.get("offer")), peer)
        elif kind == "get_offers":
            after = message.get("after")
            if after != "" and not valid_address(after):
                raise ValueError("Cursor de ofertas inválido")
            ids = sorted(key for key in self.chain.offers.keys() - self.chain.main_offer_ids if key > after)[:SYNC_BATCH]
            peer.send(dict(type="offers", offers=[self.chain.offers[key].to_dict() for key in ids]))
        elif kind == "offers":
            offers = message.get("offers")
            if not isinstance(offers, list) or len(offers) > SYNC_BATCH:
                raise ValueError("Lote de ofertas inválido")
            last = ""
            for data in offers:
                offer = Offer.from_dict(data)
                self._save_offer(offer, peer)
                last = offer.id
            if len(offers) == SYNC_BATCH:
                peer.send(dict(type="get_offers", after=last))
        elif kind == "mining_start":
            self._validate_gossip(message)
            parent = message.get("previous_hash")
            offer = Offer.from_dict(message.get("offer"))
            if not valid_address(parent) or message["timestamp"] < offer.timestamp:
                raise ValueError("Ronda de minería inválida")
            if parent in self.chain.blocks and parent != self.chain.head.hash:
                return
            if parent == self.chain.head.hash and (
                message["timestamp"] <= self.chain.head.timestamp or offer.id in self.chain.main_offer_ids
            ):
                return
            if not self._remember_message(message["id"]):
                return
            current = self.rounds.get(parent)
            if current and (current["timestamp"], current["id"]) <= (message["timestamp"], message["id"]):
                return
            message = {key: message[key] for key in ("type", "id", "timestamp", "sender", "name", "previous_hash", "offer")}
            self._save_offer(offer, peer)
            self.rounds[parent] = message
            if len(self.rounds) > MAX_ORPHANS:
                self.rounds.popitem(last=False)
            self.network.broadcast(message, exclude=peer.address)
            if parent == self.chain.head.hash:
                self._join_classroom()
        elif kind == "block":
            previous = self.chain.head
            block = Block.from_dict(message.get("block"))
            self._accept_block(block, source=peer)
            self._drain_orphans()
            if self.chain.head != previous:
                self._join_classroom()
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
            previous = self.chain.head
            for data in blocks:
                block = Block.from_dict(data)
                if block.previous_hash not in self.chain.blocks:
                    raise ValueError("La cadena recibida está incompleta")
                self._accept_block(block, source=peer, relay=False)
            self._drain_orphans()
            if self.chain.head != previous:
                self.network.broadcast(self._head_message())
                self._join_classroom()
            if blocks:
                self.emit("sync", {"name": peer.name, "received": len(blocks), "height": self.chain.head.height, "hash": self.chain.head.hash})
                if peer.head_hash not in self.chain.blocks:
                    self._request_sync(peer, blocks[-1]["hash"])
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
            self.rounds.pop(previous.hash, None)
            self._stop_mining()
            if relay:
                self.network.broadcast(self._head_message())
            self.emit("winner", dict(
                height=block.height, hash=block.hash, name=block.miner_name, address=block.miner,
                reward=block.reward, local=block.miner == self.identity.address,
                reorganization=result.reorganization, previous_hash=previous.hash,
                balance=self.chain.balance(self.identity.address), mining=False,
                block=block.to_dict(), offer_id=block.offer.id if block.offer else None,
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
        while not self.closing:
            if self.miner.running:
                data = self.miner.poll()
                stopped = data is None and all(not process.is_alive() for process in self.miner.processes)
                if stopped:
                    data = self.miner.poll()
                if data is not None:
                    self._accept_block(Block.from_dict(data))
                elif stopped:
                    self.pause_mining()
                    self.emit("error", {"message": "Los procesos de minería terminaron sin resultado. Usa /minar para reiniciar"})
            await asyncio.sleep(0.01 if self.miner.running else 0.05)

    async def _sync_loop(self) -> None:
        while not self.closing:
            self.network.broadcast(self._head_message())
            for peer in list(self.network.peers.values()):
                if peer.head_hash not in self.chain.blocks:
                    self._request_sync(peer)
            await asyncio.sleep(5)

    def status(self) -> dict[str, Any]:
        difficulty = self.chain.next_difficulty()
        return dict(
            name=self.identity.name, address=self.identity.address, host=self.network.host,
            port=self.network.port, network=self.chain.consensus.network,
            network_id=self.chain.consensus.network_id, difficulty=difficulty, target=hash_target(difficulty),
            fixed_difficulty=self.chain.consensus.difficulty, round_target_seconds=ROUND_TARGET_MS // 1000,
            template=self.template, classroom=self.chain.head.hash in self.rounds,
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
        await self.miner.close()
        self.chain.close()
        self.lock.close()
        self.closed = True
