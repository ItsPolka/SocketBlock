from __future__ import annotations

import hashlib

from socketblock.models import Block, Consensus, Offer, canonical_json, hash_target, mining_template, now_ms


def mine(
    parent: Block, consensus: Consensus, address: str = "a" * 64, name: str = "Ana",
    *, offer: Offer | None = None, started_at: int | None = None, duration: int = 0,
    difficulty: int | None = None,
) -> Block:
    if offer is None:
        offer = Offer(address, name, f"Oferta para {parent.hash}", now_ms())
    if started_at is None:
        started_at = max(parent.timestamp + 1, offer.timestamp, now_ms())
    if difficulty is None:
        difficulty = consensus.initial_difficulty
    template = mining_template(parent, consensus, address, name, offer, started_at, difficulty)
    template["timestamp"] = started_at + duration
    target = hash_target(difficulty)
    nonce = 0
    while True:
        template["nonce"] = nonce
        digest = hashlib.sha256(canonical_json(template)).hexdigest()
        if digest <= target:
            return Block.from_dict({**template, "hash": digest})
        nonce += 1
