from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from socketblock.models import Consensus, canonical_json
from socketblock.network import MAX_FRAME, parse_endpoint, read_message
from socketblock.node import Node
from tests.helpers import mine


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def test_ipv4_dns_and_ipv6_endpoints(self):
        self.assertEqual(parse_endpoint("192.168.1.8:6000"), ("192.168.1.8", 6000))
        self.assertEqual(parse_endpoint("salon.local:6000"), ("salon.local", 6000))
        self.assertEqual(parse_endpoint("[::1]:6000"), ("::1", 6000))
        for text in ("oops", "host:0", "host:99999", "::1:6000", "bad host:8"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_endpoint(text)

    async def test_tcp_framing_fragmentation_and_multiple_messages(self):
        reader = asyncio.StreamReader(limit=MAX_FRAME)
        reader.feed_data(b'{"type": "pi')
        task = asyncio.create_task(read_message(reader, 1))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        reader.feed_data(b'ng"}\n{"type":"pong"}\n')
        self.assertEqual(await task, {"type": "ping"})
        self.assertEqual(await read_message(reader, 1), {"type": "pong"})

    async def test_rejects_large_invalid_or_partial_frames(self):
        for raw in (b"x" * (MAX_FRAME + 1) + b"\n", b"[]\n", b"{oops}\n", b'{"type":"ping"}'):
            reader = asyncio.StreamReader(limit=MAX_FRAME)
            reader.feed_data(raw)
            reader.feed_eof()
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                await read_message(reader, 1)


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.nodes: list[Node] = []
        self.events: dict[int, list[tuple[str, dict]]] = {}

    async def asyncTearDown(self):
        for node in reversed(self.nodes):
            await node.close()
        self.temporary.cleanup()

    async def make_node(self, seeds=None, *, difficulty=2):
        index = len(self.nodes)
        self.events[index] = []
        node = Node(data_dir=Path(self.temporary.name) / str(index), name=f"Alumno {index + 1}",
                    host="127.0.0.1", port=0, consensus=Consensus(difficulty=difficulty),
                    emit=lambda event, data: self.events[index].append((event, data)))
        self.nodes.append(node)
        await node.start(seeds)
        return node

    async def until(self, condition, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            await asyncio.sleep(0.05)
        summary = [{"peers": len(n.network.peers), "height": n.chain.head.height, "hash": n.chain.head.hash} for n in self.nodes]
        self.fail(f"La condición no se cumplió en {timeout}s. Nodos: {summary}")

    async def test_twenty_nodes_discover_everyone_chat_and_keep_network_without_seed(self):
        first = await self.make_node()
        seed = [("127.0.0.1", first.network.port)]
        for _ in range(19):
            await self.make_node(seed)
        await self.until(lambda: all(len(n.network.peers) == 19 for n in self.nodes), timeout=25)
        self.nodes[-1].chat("¡Hola a todo el salón!")
        await self.until(lambda: all(any(e == "chat" for e, _ in self.events[i]) for i in range(20)))
        await asyncio.sleep(0.2)
        for index in range(20):
            chats = [d for e, d in self.events[index] if e == "chat"]
            self.assertEqual(len(chats), 1, f"Chat duplicado en nodo {index}")
        # El primer nodo solo fue un punto de entrada; la red sigue sin él.
        await first.close()
        await self.until(lambda: all(len(n.network.peers) == 18 for n in self.nodes[1:]))
        self.nodes[1].chat("Seguimos sin servidor central")
        await self.until(lambda: all(sum(e == "chat" for e, _ in self.events[i]) == 2 for i in range(1, 20)))
        block = mine(self.nodes[1].chain.head, self.nodes[1].chain.consensus)
        self.nodes[1]._accept_block(block)
        await self.until(lambda: all(n.chain.head.hash == block.hash for n in self.nodes[1:]))

    async def test_classroom_mines_selected_offer_and_stops_after_winner(self):
        first = await self.make_node(difficulty=3)
        seed = [("127.0.0.1", first.network.port)]
        second = await self.make_node(seed, difficulty=3)
        third = await self.make_node(seed, difficulty=3)
        await self.until(lambda: all(len(n.network.peers) == 2 for n in self.nodes))
        for node in self.nodes:
            self.assertEqual([node.chain.balance(peer.identity.address) for peer in self.nodes], [100, 100, 100])
        with self.assertRaisesRegex(ValueError, "No hay ofertas"):
            first.start_classroom()
        self.assertTrue(all(n.chain.head.height == 0 and not n.miner.running for n in self.nodes))

        first.propose("Primera oferta")
        second.propose("Elegir esta oferta")
        await self.until(lambda: all(len(n.chain.pending_offers()) == 2 for n in self.nodes))
        selected = next(o["id"] for o in second.chain.pending_offers() if o["text"] == "Elegir esta oferta")
        first.start_classroom(selected)
        third.chat("El chat funciona durante la ronda")
        second.chat("Solo para el primer nodo", recipient=first.identity.address)
        await self.until(lambda: all(n.chain.head.height == 1 and not n.miner.running for n in self.nodes))
        await self.until(lambda: all(any(e == "chat" for e, _ in self.events[i]) for i in range(3)))
        await self.until(lambda: any(d.get("recipient") for e, d in self.events[0] if e == "chat"))
        await asyncio.sleep(0.25)
        for index, node in enumerate(self.nodes):
            self.assertEqual(node.chain.main_hashes, first.chain.main_hashes)
            self.assertEqual(node.chain.head.offer.id, selected)
            self.assertEqual(sum(node.chain.balances.values()), 50)
            self.assertEqual([o["text"] for o in node.chain.pending_offers()], ["Primera oferta"])
            self.assertFalse(node.miner.running)
            self.assertTrue(any(e == "mining_started" for e, _ in self.events[index]))
            winners = [d for e, d in self.events[index] if e == "winner"]
            self.assertEqual(winners[-1]["hash"], node.chain.head.hash)
            self.assertFalse(winners[-1]["mining"])
        direct = [[d for e, d in self.events[i] if e == "chat" and d.get("recipient")] for i in range(3)]
        self.assertEqual([len(messages) for messages in direct], [1, 1, 0])
        self.assertEqual(direct[0][0]["text"], "Solo para el primer nodo")

        first.start_mining()
        await self.until(lambda: all(n.chain.head.height == 2 and not n.miner.running for n in self.nodes))
        self.assertTrue(all(not n.chain.pending_offers() for n in self.nodes))

    async def test_late_join_syncs_multiple_batches_and_restores_after_restart(self):
        first = await self.make_node(difficulty=1)
        for _ in range(205):
            first.chain.add(mine(first.chain.head, first.chain.consensus))
        for index in range(58):
            first.propose(f"Oferta pendiente {index}")
        second = await self.make_node([("127.0.0.1", first.network.port)], difficulty=1)
        await self.until(lambda: second.chain.head.hash == first.chain.head.hash)
        await self.until(lambda: second.chain.pending_offers() == first.chain.pending_offers())
        self.assertEqual(second.chain.main_hashes, first.chain.main_hashes)
        address = second.identity.address
        path = second.data_dir
        await second.close()
        restored = Node(data_dir=path, host="127.0.0.1", port=0, consensus=Consensus(difficulty=1))
        self.nodes.append(restored)
        await restored.start()
        self.assertEqual(restored.identity.address, address)
        self.assertEqual(restored.chain.head.hash, first.chain.head.hash)
        self.assertEqual(restored.chain.pending_offers(), first.chain.pending_offers())
        await self.until(lambda: len(restored.network.peers) == 1)

    async def test_network_mismatch_is_rejected(self):
        first = await self.make_node(difficulty=1)
        await self.make_node([("127.0.0.1", first.network.port)], difficulty=2)
        await self.until(lambda: any(e == "peer_error" for e, _ in self.events[0]))
        self.assertEqual(len(first.network.peers), 0)
        self.assertEqual(len(self.nodes[1].network.peers), 0)

    async def test_orphan_recovery_and_partition_convergence(self):
        first = await self.make_node(difficulty=1)
        second = await self.make_node(difficulty=1)
        left = mine(first.chain.head, first.chain.consensus, first.identity.address, first.identity.name)
        right = mine(second.chain.head, second.chain.consensus, second.identity.address, second.identity.name)
        first._accept_block(left)
        second._accept_block(right)
        child = mine(right, second.chain.consensus, second.identity.address, second.identity.name)
        second._accept_block(child)
        first.network.connect(("127.0.0.1", second.network.port))
        await self.until(lambda: first.chain.head.hash == second.chain.head.hash and first.chain.head.height == 2)
        self.assertEqual(first.chain.balance(first.identity.address), 100)
        self.assertEqual(first.chain.balance(second.identity.address), 200)
        parent = mine(second.chain.head, second.chain.consensus)
        grandchild = mine(parent, second.chain.consensus)
        second.chain.add(parent)
        second.chain.add(grandchild)
        second.network.broadcast({"type": "block", "block": grandchild.to_dict()})
        await self.until(lambda: first.chain.head.hash == grandchild.hash)
        self.assertEqual(len(first.orphans), 0)

    async def test_malformed_peer_does_not_break_server(self):
        node = await self.make_node()
        reader, writer = await asyncio.open_connection("127.0.0.1", node.network.port)
        await reader.readline()
        writer.write(canonical_json({"type": "hello", "version": 1}) + b"\n")
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.read(), 3), b"")
        writer.close()
        await writer.wait_closed()
        await self.make_node([("127.0.0.1", node.network.port)])
        await self.until(lambda: len(node.network.peers) == 1)

    async def test_shutdown_closes_idle_connections_promptly(self):
        first = await self.make_node()
        await self.make_node([("127.0.0.1", first.network.port)])
        await self.until(lambda: len(first.network.peers) == 1)
        await asyncio.sleep(0.2)
        await asyncio.wait_for(first.close(), timeout=2)
        self.assertTrue(first.closed)


if __name__ == "__main__":
    unittest.main()
