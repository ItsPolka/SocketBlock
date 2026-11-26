"""Formato canónico de bloques y reglas compartidas por toda la red."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

PROTOCOL_VERSION = 2
DEFAULT_NETWORK = "leonelcoin-v2"
MAX_USERS = 20
MAX_CHAT_LENGTH = 2000
MAX_OFFER_LENGTH = 120
MAX_FUTURE_MS = 120_000
ROUND_TARGET_MS = 120_000
INITIAL_DIFFICULTY = 120_000_000
MIN_DIFFICULTY = 16
MAX_DIFFICULTY = 2**48
GENESIS_TIME = 1_704_067_200_000
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def is_integer(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def valid_address(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def valid_text(value: Any, maximum: int) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= maximum and value.isprintable() and bool(value.strip())


def valid_name(value: Any) -> bool:
    return valid_text(value, 32)


def hash_target(difficulty: int) -> str:
    return f"{(2**256 // difficulty) - 1:064x}"


@dataclass(frozen=True)
class Consensus:
    network: str = DEFAULT_NETWORK
    difficulty: int | None = None
    reward: int = 50

    def __post_init__(self) -> None:
        if not valid_text(self.network, 64):
            raise ValueError("La red debe tener entre 1 y 64 caracteres imprimibles")
        if self.difficulty is not None and not is_integer(self.difficulty, 1, 7):
            raise ValueError("La dificultad fija debe estar entre 1 y 7 ceros hexadecimales")
        if not is_integer(self.reward, 1, 1_000_000):
            raise ValueError("La recompensa debe ser un entero positivo de hasta 1000000")

    @property
    def initial_difficulty(self) -> int:
        return INITIAL_DIFFICULTY if self.difficulty is None else 16**self.difficulty

    @property
    def network_id(self) -> str:
        return hashlib.sha256(canonical_json({"protocol": PROTOCOL_VERSION, **asdict(self)})).hexdigest()


@dataclass(frozen=True)
class Offer:
    author: str
    name: str
    text: str
    timestamp: int

    @property
    def id(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self))).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Offer:
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Formato de oferta inválido")
        if not valid_address(data["author"]) or not valid_name(data["name"]):
            raise ValueError("Autor de oferta inválido")
        if not valid_text(data["text"], MAX_OFFER_LENGTH):
            raise ValueError(f"La oferta debe tener entre 1 y {MAX_OFFER_LENGTH} caracteres imprimibles")
        if not is_integer(data["timestamp"], GENESIS_TIME, now_ms() + MAX_FUTURE_MS):
            raise ValueError("Fecha de oferta inválida")
        return cls(**data)


@dataclass(frozen=True)
class Block:
    network_id: str
    height: int
    previous_hash: str
    timestamp: int
    started_at: int
    miner: str
    miner_name: str
    reward: int
    difficulty: int
    nonce: int
    offer: Offer | None
    hash: str

    def header(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if key != "hash"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def calculate_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.header())).hexdigest()

    @classmethod
    def from_dict(cls, data: Any) -> Block:
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Formato de bloque inválido")
        if not all(valid_address(data[key]) for key in ("network_id", "previous_hash", "miner", "hash")):
            raise ValueError("Hashes o dirección inválidos")
        if not valid_name(data["miner_name"]):
            raise ValueError("Nombre del minero inválido")
        for key, lower, upper in (
            ("height", 0, 2**53 - 1), ("timestamp", 0, 2**53 - 1), ("started_at", 0, 2**53 - 1),
            ("reward", 0, 1_000_000), ("difficulty", MIN_DIFFICULTY, MAX_DIFFICULTY), ("nonce", 0, 2**64 - 1),
        ):
            if not is_integer(data[key], lower, upper):
                raise ValueError(f"Campo de bloque inválido: {key}")
        offer = None if data["height"] == 0 and data["offer"] is None else Offer.from_dict(data["offer"])
        return cls(**{**data, "offer": offer})


def genesis(consensus: Consensus) -> Block:
    fields = dict(
        network_id=consensus.network_id, height=0, previous_hash="0" * 64,
        timestamp=GENESIS_TIME, started_at=GENESIS_TIME, miner="0" * 64, miner_name="Genesis",
        reward=0, difficulty=consensus.initial_difficulty, nonce=0, offer=None,
    )
    return Block(**fields, hash=hashlib.sha256(canonical_json(fields)).hexdigest())


def validate_work(block: Block, consensus: Consensus) -> None:
    Block.from_dict(block.to_dict())
    if block.height < 1 or block.network_id != consensus.network_id:
        raise ValueError("El bloque pertenece a otra red o pretende reemplazar el génesis")
    if block.reward != consensus.reward or (consensus.difficulty is not None and block.difficulty != consensus.initial_difficulty):
        raise ValueError("Dificultad o recompensa incorrecta")
    if block.hash != block.calculate_hash() or block.hash > hash_target(block.difficulty):
        raise ValueError("Prueba de trabajo inválida")
    if not block.offer or not block.offer.timestamp <= block.started_at <= block.timestamp <= now_ms() + MAX_FUTURE_MS:
        raise ValueError("Fechas de oferta, inicio o fin de minería inválidas")


def mining_template(
    parent: Block, consensus: Consensus, address: str, name: str,
    offer: Offer, started_at: int, difficulty: int,
) -> dict[str, Any]:
    return dict(
        network_id=consensus.network_id, height=parent.height + 1,
        previous_hash=parent.hash, timestamp=started_at, started_at=started_at,
        miner=address, miner_name=name, reward=consensus.reward,
        difficulty=difficulty, nonce=0, offer=offer.to_dict(),
    )
