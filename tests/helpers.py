from __future__ import annotations

import hashlib

from socketblock.models import Block, Consensus, canonical_json, mining_template


def mine(parent: Block, consensus: Consensus, address: str = "a" * 64, name: str = "Ana") -> Block:
    template = mining_template(parent, consensus, address, name)
    nonce = 0
    while True:
        template["nonce"] = nonce
        digest = hashlib.sha256(canonical_json(template)).hexdigest()
        if digest.startswith("0" * consensus.difficulty):
            return Block(**template, hash=digest)
        nonce += 1
