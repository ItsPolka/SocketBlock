"""Formato canónico de bloques y reglas compartidas por toda la red."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

PROTOCOL_VERSION = 1
MAX_USERS = 20
MAX_CHAT_LENGTH = 2000
MAX_FUTURE_MS = 120_000
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


def valid_name(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 32 and value.isprintable() and bool(value.strip())


@dataclass(frozen=True)
class Consensus:
    network: str = "leonelcoin-v1"
    difficulty: int = 6
    reward: int = 50

    def __post_init__(self) -> None:
        if not isinstance(self.network, str) or not 1 <= len(self.network) <= 64 or not self.network.isprintable():
            raise ValueError("La red debe tener entre 1 y 64 caracteres imprimibles")
        if not is_integer(self.difficulty, 1, 7):
            raise ValueError("La dificultad debe estar entre 1 y 7 ceros hexadecimales")
        if not is_integer(self.reward, 1, 1_000_000):
            raise ValueError("La recompensa debe ser un entero positivo de hasta 1000000")

    @property
    def network_id(self) -> str:
        return hashlib.sha256(canonical_json({"protocol": PROTOCOL_VERSION, **asdict(self)})).hexdigest()


@dataclass(frozen=True)
class Block:
    network_id: str
    height: int
    previous_hash: str
    timestamp: int
    miner: str
    miner_name: str
    reward: int
    difficulty: int
    nonce: int
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
            ("height", 0, 2**53 - 1), ("timestamp", 0, 2**53 - 1),
            ("reward", 0, 1_000_000), ("difficulty", 1, 7), ("nonce", 0, 2**64 - 1),
        ):
            if not is_integer(data[key], lower, upper):
                raise ValueError(f"Campo de bloque inválido: {key}")
        return cls(**data)


def genesis(consensus: Consensus) -> Block:
    fields = dict(
        network_id=consensus.network_id, height=0, previous_hash="0" * 64,
        timestamp=GENESIS_TIME, miner="0" * 64, miner_name="Genesis",
        reward=0, difficulty=consensus.difficulty, nonce=0,
    )
    return Block(**fields, hash=hashlib.sha256(canonical_json(fields)).hexdigest())


def validate_work(block: Block, consensus: Consensus, *, clock_ms: int | None = None) -> None:
    # Revisa también instancias creadas directamente dentro del proceso.
    Block.from_dict(block.to_dict())
    if block.height < 1 or block.network_id != consensus.network_id:
        raise ValueError("El bloque pertenece a otra red o pretende reemplazar el génesis")
    if block.difficulty != consensus.difficulty or block.reward != consensus.reward:
        raise ValueError("Dificultad o recompensa incorrecta")
    if block.hash != block.calculate_hash() or not block.hash.startswith("0" * consensus.difficulty):
        raise ValueError("Prueba de trabajo inválida")
    if block.timestamp > (now_ms() if clock_ms is None else clock_ms) + MAX_FUTURE_MS:
        raise ValueError("El bloque tiene una fecha demasiado futura")


def mining_template(parent: Block, consensus: Consensus, address: str, name: str) -> dict[str, Any]:
    return dict(
        network_id=consensus.network_id, height=parent.height + 1,
        previous_hash=parent.hash, timestamp=max(now_ms(), parent.timestamp + 1),
        miner=address, miner_name=name, reward=consensus.reward,
        difficulty=consensus.difficulty, nonce=0,
    )
