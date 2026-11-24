"""Identidad local y exclusión mutua de la carpeta de datos."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import valid_address, valid_name


@dataclass(frozen=True)
class Identity:
    address: str
    name: str


def load_identity(directory: Path, name: str | None) -> Identity:
    path = directory / "identity.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    address = data.get("address", secrets.token_hex(32))
    chosen_name = name if name is not None else data.get("name")
    if not valid_address(address):
        raise ValueError("La identidad guardada no contiene una dirección válida")
    if not valid_name(chosen_name):
        raise ValueError("Indica --name con un nombre de 1 a 32 caracteres imprimibles")
    identity = Identity(address, chosen_name)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(identity), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return identity


class DataLock:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / ".lock").open("a+b")
        self.windows = os.name == "nt"
        try:
            if self.windows:
                import msvcrt
                self.file.seek(0)
                self.file.write(b"0")
                self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise ValueError("Otro nodo está usando esta carpeta. Usa un --data-dir diferente") from exc

    def close(self) -> None:
        if not self.file.closed:
            if self.windows:
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
