"""Sockets TCP/IP bidireccionales, descubrimiento de pares y mensajes JSON."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .models import MAX_USERS, PROTOCOL_VERSION, canonical_json, is_integer, valid_address, valid_name
from .storage import Identity

MAX_FRAME = 128 * 1024
MAX_CONNECTIONS = MAX_USERS - 1
MAX_CANDIDATES = 256
HANDSHAKE_TIMEOUT = 8
HEARTBEAT_INTERVAL = 10
PEER_TIMEOUT = 45


def valid_host(host: Any) -> bool:
    return isinstance(host, str) and 0 < len(host) <= 253 and all(c.isalnum() or c in ".-_:" for c in host)


def parse_endpoint(value: str) -> tuple[str, int]:
    try:
        if value.startswith("["):
            host, port_text = value[1:].split("]:", 1)
        else:
            host, port_text = value.rsplit(":", 1)
            if ":" in host:
                raise ValueError("IPv6 requiere [dirección]:puerto")
        port = int(port_text)
        if not valid_host(host) or not 1 <= port <= 65535:
            raise ValueError("Dirección o puerto inválido")
        return host, port
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Par inválido: {value!r}. Usa IP:PUERTO o [IPv6]:PUERTO") from exc


def format_endpoint(endpoint: tuple[str, int]) -> str:
    host, port = endpoint
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def valid_advertised_host(host: str) -> bool:
    if not valid_host(host) or host.lower() in ("localhost", "0.0.0.0", "::"):
        return False
    try:
        address = ipaddress.ip_address(host)
        return not address.is_unspecified and not address.is_multicast
    except ValueError:
        return True  # Los nombres DNS son útiles en VPN y redes con DNS local.


async def read_message(reader: asyncio.StreamReader, timeout: float) -> dict[str, Any]:
    try:
        line = await asyncio.wait_for(reader.readline(), timeout)
    except (ValueError, asyncio.LimitOverrunError) as exc:
        raise ValueError("Mensaje demasiado grande") from exc
    if not line:
        raise ConnectionError("El par cerró la conexión")
    if len(line) > MAX_FRAME or not line.endswith(b"\n"):
        raise ValueError("Trama TCP inválida o demasiado grande")
    try:
        message = json.loads(line)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("JSON inválido") from exc
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ValueError("Mensaje sin tipo")
    return message


@dataclass(eq=False)
class Peer:
    address: str
    name: str
    endpoint: tuple[str, int]
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    outbound: bool
    head_hash: str
    height: int
    last_seen: float = field(default_factory=time.monotonic)
    outbox: asyncio.Queue[bytes] = field(default_factory=lambda: asyncio.Queue(maxsize=128))

    def send(self, message: dict[str, Any]) -> None:
        encoded = canonical_json(message) + b"\n"
        if len(encoded) > MAX_FRAME:
            raise ValueError("El mensaje excede el límite de trama")
        try:
            self.outbox.put_nowait(encoded)
        except asyncio.QueueFull:
            self.writer.close()  # Un par lento no bloquea la minería ni a los demás.


class Network:
    def __init__(
        self, identity: Identity, network_id: str, host: str, port: int,
        advertise: str | None, get_head: Callable[[], tuple[str, int]],
        on_message: Callable[[Peer, dict[str, Any]], Awaitable[None]],
        on_peer: Callable[[Peer], Awaitable[None]], emit: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self.identity = identity
        self.network_id = network_id
        self.host, self.port, self.advertise = host, port, advertise
        self.get_head, self.on_message, self.on_peer, self.emit = get_head, on_message, on_peer, emit
        self.peers: dict[str, Peer] = {}
        self.candidates: dict[tuple[str, int], float] = {}
        self.attempts: dict[tuple[str, int], int] = {}
        self.endpoint_addresses: dict[tuple[str, int], str] = {}
        self.dialing: set[tuple[str, int]] = set()
        self.connections: set[asyncio.StreamWriter] = set()
        self.tasks: set[asyncio.Task[Any]] = set()
        self.server: asyncio.Server | None = None
        self.closing = False

    def _spawn(self, coroutine: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task[Any]) -> None:
        self.tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            self.emit("error", {"message": f"Error de red: {error}"})

    async def start(self, seeds: list[tuple[str, int]]) -> None:
        self.server = await asyncio.start_server(self._accept, self.host, self.port, limit=MAX_FRAME)
        self.port = self.server.sockets[0].getsockname()[1]
        for endpoint in seeds:
            self.remember(endpoint)
        self._spawn(self._maintain())

    def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.closing or len(self.connections) >= MAX_CONNECTIONS * 2 or len(self.peers) >= MAX_CONNECTIONS:
            writer.close()
            return
        self.connections.add(writer)
        self._spawn(self._connection(reader, writer, False))

    def remember(self, endpoint: tuple[str, int]) -> None:
        host, port = endpoint
        if not valid_host(host) or not is_integer(port, 1, 65535):
            return
        if port == self.port and host in (self.host, self.advertise):
            return
        if endpoint not in self.candidates and len(self.candidates) < MAX_CANDIDATES:
            self.candidates[endpoint] = 0

    def connect(self, endpoint: tuple[str, int]) -> None:
        self.remember(endpoint)
        if endpoint in self.candidates:
            self.candidates[endpoint] = 0

    async def _dial(self, endpoint: tuple[str, int]) -> None:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(*endpoint, limit=MAX_FRAME), HANDSHAKE_TIMEOUT)
            self.connections.add(writer)
            await self._connection(reader, writer, True, endpoint)
        except (OSError, asyncio.TimeoutError) as exc:
            count = self.attempts.get(endpoint, 0) + 1
            self.attempts[endpoint] = count
            if count == 1:
                self.emit("connection_retry", {"endpoint": format_endpoint(endpoint), "message": str(exc)})
        finally:
            self.dialing.discard(endpoint)
            delay = min(30, 2 ** min(self.attempts.get(endpoint, 1), 5))
            if endpoint in self.candidates:
                self.candidates[endpoint] = time.monotonic() + delay + random.random()

    def _hello(self) -> dict[str, Any]:
        head_hash, height = self.get_head()
        return dict(type="hello", version=PROTOCOL_VERSION, network_id=self.network_id,
                    address=self.identity.address, name=self.identity.name,
                    host=self.advertise, port=self.port, head_hash=head_hash, height=height)

    async def _connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, outbound: bool,
                          dialed: tuple[str, int] | None = None) -> None:
        peer = None
        sender = None
        try:
            writer.write(canonical_json(self._hello()) + b"\n")
            await asyncio.wait_for(writer.drain(), HANDSHAKE_TIMEOUT)
            hello = await read_message(reader, HANDSHAKE_TIMEOUT)
            if dialed:
                self.dialing.discard(dialed)
            if hello.get("type") != "hello" or hello.get("version") != PROTOCOL_VERSION:
                raise ValueError("Versión de protocolo incompatible")
            if hello.get("network_id") != self.network_id:
                raise ValueError("Otra red: revisa --network, --difficulty y --reward")
            if not valid_address(hello.get("address")) or not valid_name(hello.get("name")):
                raise ValueError("Identidad de par inválida")
            if not valid_address(hello.get("head_hash")) or not is_integer(hello.get("height"), 0, 2**53 - 1):
                raise ValueError("Punta de cadena inválida")
            if not is_integer(hello.get("port"), 1, 65535):
                raise ValueError("Puerto anunciado inválido")
            address = hello["address"]
            if address == self.identity.address:
                if dialed:
                    self.candidates.pop(dialed, None)
                return
            if dialed:
                self.endpoint_addresses[dialed] = address
            existing = self.peers.get(address)
            if existing:
                # Si ambos marcan a la vez, ambos conservan la misma conexión.
                preferred_outbound = self.identity.address < address
                if existing.outbound == preferred_outbound or outbound != preferred_outbound:
                    return
                existing.writer.close()
            elif len(self.peers) >= MAX_CONNECTIONS:
                return
            advertised = hello.get("host")
            if advertised is not None and (not isinstance(advertised, str) or not valid_advertised_host(advertised)):
                raise ValueError("Host anunciado inválido")
            host = advertised or (dialed[0] if dialed else writer.get_extra_info("peername")[0])
            peer = Peer(address, hello["name"], (host, hello["port"]), reader, writer, outbound, hello["head_hash"], hello["height"])
            self.peers[address] = peer
            self.remember(peer.endpoint)
            if dialed:
                self.attempts.pop(dialed, None)
            sender = asyncio.create_task(self._write(peer))
            peer.send(self._peer_list())
            self.broadcast(self._peer_list(), exclude=address)
            self.emit("peer_connected", {"name": peer.name, "address": address, "endpoint": format_endpoint(peer.endpoint), "peers": len(self.peers)})
            await self.on_peer(peer)
            while not self.closing:
                message = await read_message(reader, PEER_TIMEOUT)
                peer.last_seen = time.monotonic()
                kind = message["type"]
                if kind == "ping":
                    peer.send({"type": "pong"})
                elif kind == "pong":
                    pass
                elif kind == "get_peers":
                    peer.send(self._peer_list())
                elif kind == "peers":
                    self._learn_peers(message)
                else:
                    await self.on_message(peer, message)
        except (OSError, ConnectionError, asyncio.TimeoutError, ValueError, RecursionError) as exc:
            if not self.closing:
                self.emit("peer_error", {"name": peer.name if peer else "desconocido", "message": str(exc)})
        finally:
            if sender:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, asyncio.TimeoutError):
                pass
            self.connections.discard(writer)
            if peer and self.peers.get(peer.address) is peer:
                del self.peers[peer.address]
                self.emit("peer_disconnected", {"name": peer.name, "address": peer.address, "peers": len(self.peers)})

    async def _write(self, peer: Peer) -> None:
        try:
            while True:
                encoded = await peer.outbox.get()
                peer.writer.write(encoded)
                await asyncio.wait_for(peer.writer.drain(), 5)
        except (OSError, asyncio.TimeoutError):
            peer.writer.close()

    def _peer_list(self) -> dict[str, Any]:
        entries = [dict(address=p.address, name=p.name, host=p.endpoint[0], port=p.endpoint[1]) for p in self.peers.values()]
        return {"type": "peers", "peers": entries}

    def _learn_peers(self, message: dict[str, Any]) -> None:
        peers = message.get("peers")
        if not isinstance(peers, list) or len(peers) > MAX_CONNECTIONS:
            raise ValueError("Lista de pares inválida")
        for data in peers:
            if not isinstance(data, dict) or not valid_address(data.get("address")) or not valid_name(data.get("name")):
                raise ValueError("Identidad anunciada inválida")
            if not valid_host(data.get("host")) or not is_integer(data.get("port"), 1, 65535):
                raise ValueError("Dirección anunciada inválida")
            if data["address"] != self.identity.address:
                self.remember((data["host"], data["port"]))

    def broadcast(self, message: dict[str, Any], exclude: str | None = None) -> None:
        for address, peer in list(self.peers.items()):
            if address != exclude:
                peer.send(message)

    async def _maintain(self) -> None:
        last_heartbeat = 0.0
        while not self.closing:
            clock = time.monotonic()
            if clock - last_heartbeat >= HEARTBEAT_INTERVAL:
                for peer in list(self.peers.values()):
                    peer.send({"type": "ping"})
                    peer.send({"type": "get_peers"})
                last_heartbeat = clock
            connected = {peer.endpoint for peer in self.peers.values()}
            for endpoint, retry_at in list(self.candidates.items()):
                if len(self.peers) + len(self.dialing) >= MAX_CONNECTIONS or len(self.dialing) >= 4:
                    break
                already_connected = self.endpoint_addresses.get(endpoint) in self.peers
                if not already_connected and endpoint not in connected and endpoint not in self.dialing and clock >= retry_at:
                    self.dialing.add(endpoint)
                    self._spawn(self._dial(endpoint))
            await asyncio.sleep(0.5)

    async def close(self) -> None:
        self.closing = True
        if self.server:
            self.server.close()
        for writer in list(self.connections):
            writer.close()
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
        # Python reciente espera también los transports de clientes. Cerrarlos
        # primero evita esperar al siguiente heartbeat o al timeout de lectura.
        if self.server:
            await self.server.wait_closed()
