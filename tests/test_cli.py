"""Prueba de extremo a extremo con terminales en procesos independientes."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path


class CliTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.processes = []
        self.collectors = []
        self.events = []

    async def asyncTearDown(self):
        for process in self.processes:
            if process.returncode is None:
                try:
                    process.stdin.write(b"/salir\n")
                    await process.stdin.drain()
                except (OSError, ConnectionError):
                    pass
        for process in self.processes:
            try:
                await asyncio.wait_for(process.wait(), 10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        await asyncio.gather(*self.collectors, return_exceptions=True)
        self.temporary.cleanup()

    async def spawn(self, name, peer=None):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        arguments = [sys.executable, "-m", "socketblock", "--name", name, "--host", "127.0.0.1",
                     "--port", str(port), "--difficulty", "3", "--json",
                     "--data-dir", str(Path(self.temporary.name) / name)]
        if peer:
            arguments.extend(["--peer", f"127.0.0.1:{peer}"])
        process = await asyncio.create_subprocess_exec(*arguments, stdin=asyncio.subprocess.PIPE,
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.processes.append(process)
        events = []
        self.events.append(events)

        async def collect():
            async for line in process.stdout:
                events.append(json.loads(line))

        self.collectors.append(asyncio.create_task(collect()))
        return process, port, events

    async def until(self, condition, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            await asyncio.sleep(0.05)
        self.fail(f"No se obtuvo el evento de consola esperado: {self.events}")

    async def test_two_terminals_share_chat_winners_chain_and_exit_cleanly(self):
        first, port, first_events = await self.spawn("Ana")
        await self.until(lambda: any(e["event"] == "ready" for e in first_events))
        second, _, second_events = await self.spawn("Beto", port)
        await self.until(lambda: all(any(e["event"] == "peer_connected" for e in events) for events in self.events))
        first.stdin.write(b"/iniciar\n")
        await first.stdin.drain()
        await self.until(lambda: all(any(e["event"] == "winner" and e["height"] >= 3 for e in events) for events in self.events))
        second.stdin.write("El salón mina por TCP\n".encode("utf-8"))
        await second.stdin.drain()
        await self.until(lambda: all(any(e["event"] == "chat" for e in events) for events in self.events))
        for process in (first, second):
            process.stdin.write(b"/pausar\n")
            await process.stdin.drain()
        await self.until(lambda: all(any(e["event"] == "mining_paused" for e in events) for events in self.events))
        for process in (first, second):
            process.stdin.write(b"/estado\n")
            await process.stdin.drain()
        await self.until(lambda: all(any(e["event"] == "status" for e in events) for events in self.events))
        statuses = [next(e for e in reversed(events) if e["event"] == "status") for events in self.events]
        self.assertEqual(statuses[0]["hash"], statuses[1]["hash"])
        self.assertEqual(statuses[0]["height"], statuses[1]["height"])
        self.assertEqual(statuses[0]["balance"] + statuses[1]["balance"], statuses[0]["height"] * 50)
        for process in (first, second):
            process.stdin.write(b"/salir\n")
            await process.stdin.drain()
        for process in (first, second):
            await asyncio.wait_for(process.wait(), 10)
            stderr = (await process.stderr.read()).decode("utf-8", errors="replace")
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stderr, "")


if __name__ == "__main__":
    unittest.main()
