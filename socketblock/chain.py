"""Árbol de bloques persistente y selección determinista de la cadena principal."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Block, Consensus, canonical_json, genesis, validate_work


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
            first = genesis(consensus)
            self.blocks: dict[str, Block] = {first.hash: first}
            self.head = first
            for (payload,) in self.db.execute("SELECT payload FROM blocks ORDER BY height, hash"):
                block = Block.from_dict(json.loads(payload))
                if block == first:
                    continue
                self._validate_child(block)
                self.blocks[block.hash] = block
                if self._better(block, self.head):
                    self.head = block
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('network_id', ?)", (consensus.network_id,))
                self._persist(first)
            self._rebuild_main()
        except BaseException:
            self.db.close()
            raise

    @staticmethod
    def _better(candidate: Block, current: Block) -> bool:
        # La dificultad es fija: mayor altura equivale a mayor trabajo acumulado.
        return candidate.height > current.height or (candidate.height == current.height and candidate.hash < current.hash)

    def _persist(self, block: Block) -> None:
        self.db.execute("INSERT OR IGNORE INTO blocks VALUES (?, ?, ?)", (block.hash, block.height, canonical_json(block.to_dict()).decode()))

    def _validate_child(self, block: Block) -> None:
        validate_work(block, self.consensus)
        parent = self.blocks.get(block.previous_hash)
        if parent is None:
            raise ValueError("No se conoce el bloque padre")
        if block.height != parent.height + 1 or block.timestamp <= parent.timestamp:
            raise ValueError("Altura o fecha incompatible con el bloque padre")

    def add(self, block: Block) -> AddResult:
        if block.hash in self.blocks:
            return AddResult(False)
        validate_work(block, self.consensus)
        if block.previous_hash not in self.blocks:
            return AddResult(False, missing_parent=True)
        self._validate_child(block)
        previous = self.head
        with self.db:
            self._persist(block)
        self.blocks[block.hash] = block
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
        self.balances: dict[str, int] = {}
        for block_hash in self.main_hashes[1:]:
            block = self.blocks[block_hash]
            self.balances[block.miner] = self.balances.get(block.miner, 0) + block.reward

    def balance(self, address: str, confirmations: int = 1) -> int:
        if confirmations <= 1:
            return self.balances.get(address, 0)
        end = max(1, len(self.main_hashes) - confirmations + 1)
        return sum(self.blocks[h].reward for h in self.main_hashes[1:end] if self.blocks[h].miner == address)

    def recent(self, count: int = 10) -> list[Block]:
        return [self.blocks[h] for h in self.main_hashes[max(1, len(self.main_hashes) - count):]]

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
