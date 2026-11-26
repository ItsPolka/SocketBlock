"""Árbol de bloques persistente y selección determinista de la cadena principal."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import (MAX_DIFFICULTY, MIN_DIFFICULTY, ROUND_TARGET_MS, Block,
                     Consensus, Offer, canonical_json, genesis, valid_address, validate_work)

DIFFICULTY_WINDOW = 12
INITIAL_BALANCE = 100


@dataclass(frozen=True)
class AddResult:
    accepted: bool
    head_changed: bool = False
    missing_parent: bool = False
    reorganization: bool = False


class Blockchain:
    def __init__(self, consensus: Consensus, path: Path | str = ":memory:") -> None:
        self.consensus = consensus
        self.db = sqlite3.connect(str(path))
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS blocks (hash TEXT PRIMARY KEY, height INTEGER NOT NULL, payload TEXT NOT NULL)")
            row = self.db.execute("SELECT value FROM metadata WHERE key='network_id'").fetchone()
            if row and row[0] != consensus.network_id:
                raise ValueError("La carpeta de datos pertenece a otra red. Usa otra carpeta o la configuración original")
            self.db.execute("CREATE TABLE IF NOT EXISTS offers (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            self.offers: dict[str, Offer] = {
                offer_id: Offer.from_dict(json.loads(payload))
                for offer_id, payload in self.db.execute("SELECT id, payload FROM offers")
            }
            self.db.execute("CREATE TABLE IF NOT EXISTS participants (address TEXT PRIMARY KEY)")
            self.participants = {address for (address,) in self.db.execute("SELECT address FROM participants")}
            self.participants.update(offer.author for offer in self.offers.values())
            first = genesis(consensus)
            self.blocks: dict[str, Block] = {first.hash: first}
            self.work: dict[str, int] = {first.hash: 0}
            self.offer_uses: dict[str, set[str]] = {}
            self.head = first
            for (payload,) in self.db.execute("SELECT payload FROM blocks ORDER BY height, hash"):
                block = Block.from_dict(json.loads(payload))
                if block == first:
                    continue
                validate_work(block, self.consensus)
                self._validate_child(block)
                self._index_block(block)
                if self._better(block, self.head):
                    self.head = block
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('network_id', ?)", (consensus.network_id,))
                self._persist(first)
            self._rebuild_main()
        except BaseException:
            self.db.close()
            raise

    def _better(self, candidate: Block, current: Block) -> bool:
        candidate_work, current_work = self.work[candidate.hash], self.work[current.hash]
        return candidate_work > current_work or (candidate_work == current_work and candidate.hash < current.hash)

    def next_difficulty(self, parent: Block | None = None) -> int:
        if parent is None:
            parent = self.head
        if self.consensus.difficulty is not None or parent.height == 0:
            return self.consensus.initial_difficulty
        current = parent
        expected_hashes = elapsed = 0
        for _ in range(min(current.height, DIFFICULTY_WINDOW)):
            expected_hashes += current.difficulty
            elapsed += max(1000, current.timestamp - current.started_at)
            current = self.blocks[current.previous_hash]
        estimate = expected_hashes * ROUND_TARGET_MS // elapsed
        return min(MAX_DIFFICULTY, parent.difficulty * 2,
                   max(MIN_DIFFICULTY, parent.difficulty // 2, estimate))

    def add_offer(self, offer: Offer) -> bool:
        offer_id = offer.id
        if offer_id in self.offers:
            return False
        with self.db:
            self._persist_offer(offer_id, offer)
        self.offers[offer_id] = offer
        self.participants.add(offer.author)
        return True

    def register_participant(self, address: str) -> None:
        if not valid_address(address):
            raise ValueError("Dirección de participante inválida")
        if address in self.participants:
            return
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO participants VALUES (?)", (address,))
        self.participants.add(address)

    def _persist_offer(self, offer_id: str, offer: Offer) -> None:
        self.db.execute("INSERT OR IGNORE INTO offers VALUES (?, ?)", (offer_id, canonical_json(offer.to_dict()).decode()))

    def pending_offers(self) -> list[dict[str, Any]]:
        ids = self.offers.keys() - self.main_offer_ids
        return [{"id": offer_id, **self.offers[offer_id].to_dict()}
                for offer_id in sorted(ids, key=lambda key: (self.offers[key].timestamp, key))]

    def _index_block(self, block: Block) -> None:
        assert block.offer is not None
        offer_id = block.offer.id
        self.blocks[block.hash] = block
        self.work[block.hash] = self.work[block.previous_hash] + block.difficulty
        self.offers[offer_id] = block.offer
        self.participants.update((block.miner, block.offer.author))
        self.offer_uses.setdefault(offer_id, set()).add(block.hash)

    def _persist(self, block: Block) -> None:
        self.db.execute("INSERT OR IGNORE INTO blocks VALUES (?, ?, ?)", (block.hash, block.height, canonical_json(block.to_dict()).decode()))

    def _validate_child(self, block: Block) -> None:
        parent = self.blocks.get(block.previous_hash)
        if parent is None:
            raise ValueError("No se conoce el bloque padre")
        if block.height != parent.height + 1 or block.started_at <= parent.timestamp:
            raise ValueError("Altura o fecha incompatible con el bloque padre")
        if block.difficulty != self.next_difficulty(parent):
            raise ValueError("Dificultad incompatible con la cadena")
        assert block.offer is not None
        uses = self.offer_uses.get(block.offer.id)
        while uses and parent.height:
            if parent.hash in uses:
                raise ValueError("La oferta ya está incluida en esta rama")
            parent = self.blocks[parent.previous_hash]

    def add(self, block: Block) -> AddResult:
        if block.hash in self.blocks:
            return AddResult(False)
        validate_work(block, self.consensus)
        if block.previous_hash not in self.blocks:
            return AddResult(False, missing_parent=True)
        self._validate_child(block)
        assert block.offer is not None
        previous = self.head
        with self.db:
            self._persist(block)
            self._persist_offer(block.offer.id, block.offer)
        self._index_block(block)
        changed = self._better(block, previous)
        if changed:
            self.head = block
            self._rebuild_main()
        return AddResult(True, changed, reorganization=changed and block.previous_hash != previous.hash)

    def _rebuild_main(self) -> None:
        reverse = []
        current = self.head
        while current.height:
            reverse.append(current.hash)
            current = self.blocks[current.previous_hash]
        reverse.append(current.hash)
        self.main_hashes = list(reversed(reverse))
        self.main_set = set(self.main_hashes)
        self.main_offer_ids: set[str] = set()
        self.balances: dict[str, int] = {}
        for block_hash in self.main_hashes[1:]:
            block = self.blocks[block_hash]
            assert block.offer is not None
            self.main_offer_ids.add(block.offer.id)
            self.balances[block.miner] = self.balances.get(block.miner, 0) + block.reward

    def balance(self, address: str, confirmations: int = 1) -> int:
        initial = INITIAL_BALANCE if address in self.participants else 0
        if confirmations <= 1:
            return initial + self.balances.get(address, 0)
        end = max(1, len(self.main_hashes) - confirmations + 1)
        return initial + sum(self.blocks[h].reward for h in self.main_hashes[1:end] if self.blocks[h].miner == address)

    def recent(self, count: int = 10) -> list[Block]:
        return [self.blocks[h] for h in self.main_hashes[max(1, len(self.main_hashes) - count):]]

    def history(self) -> list[Block]:
        return [self.blocks[h] for h in self.main_hashes]

    def locator(self) -> list[str]:
        # Retrocede exponencialmente para sincronizar bifurcaciones de cualquier longitud.
        index = self.head.height
        step = 1
        result = []
        while index > 0:
            result.append(self.main_hashes[index])
            if len(result) >= 10:
                step *= 2
            index = max(0, index - step)
        result.append(self.main_hashes[0])
        return result

    def after_locator(self, locator: list[str], limit: int = 100) -> list[dict[str, Any]]:
        common = next((self.blocks[h].height for h in locator if h in self.main_set), 0)
        return [self.blocks[h].to_dict() for h in self.main_hashes[common + 1:common + 1 + limit]]

    def close(self) -> None:
        self.db.close()
