import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from socketblock.chain import Blockchain
from socketblock.models import Block, Consensus, Offer, genesis, now_ms
from socketblock.storage import DataLock, load_identity
from tests.helpers import mine


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.consensus = Consensus(difficulty=1)
        self.chain = Blockchain(self.consensus)
        self.addCleanup(self.chain.close)

    def test_genesis_is_shared_and_network_rules_change_its_hash(self):
        self.assertEqual(self.chain.head, genesis(self.consensus))
        self.assertNotEqual(self.chain.head.hash, genesis(Consensus(difficulty=2)).hash)
        self.assertNotEqual(self.chain.head.hash, genesis(Consensus(difficulty=1, reward=51)).hash)

    def test_work_rewards_and_duplicate_blocks(self):
        block = mine(self.chain.head, self.consensus)
        self.assertTrue(self.chain.add(block).head_changed)
        self.assertFalse(self.chain.add(block).accepted)
        self.assertEqual(self.chain.balance("a" * 64), 150)
        self.assertEqual(self.chain.balance("a" * 64, 6), 100)
        for _ in range(5):
            self.chain.add(mine(self.chain.head, self.consensus))
        self.assertEqual(self.chain.balance("a" * 64), 400)
        self.assertEqual(self.chain.balance("a" * 64, 6), 150)

    def test_rejects_tampering_and_invalid_fields(self):
        good = mine(self.chain.head, self.consensus)
        variants = [dict(hash="f" * 64), dict(reward=999), dict(difficulty=2),
                    dict(height=8), dict(timestamp=now_ms() + 180_000), dict(nonce=True),
                    dict(miner_name="\x1b[31m"), dict(previous_hash="oops")]
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.chain.add(dataclasses.replace(good, **changes))
        self.assertEqual(self.chain.head.height, 0)

    def test_unknown_parent_requires_sync(self):
        first = mine(self.chain.head, self.consensus)
        second = mine(first, self.consensus)
        self.assertTrue(self.chain.add(second).missing_parent)
        self.assertEqual(self.chain.balance("a" * 64), 0)
        self.chain.add(first)
        self.assertTrue(self.chain.add(second).accepted)

    def test_forks_converge_independent_of_arrival_and_recalculate_rewards(self):
        first = mine(self.chain.head, self.consensus, "a" * 64, "Ana")
        other = mine(self.chain.head, self.consensus, "b" * 64, "Beto")
        alternate = Blockchain(self.consensus)
        self.addCleanup(alternate.close)
        for block in (first, other):
            self.chain.add(block)
        for block in (other, first):
            alternate.add(block)
        self.assertEqual(self.chain.head.hash, min(first.hash, other.hash))
        self.assertEqual(self.chain.head.hash, alternate.head.hash)
        loser = max((first, other), key=lambda b: b.hash)
        extended = mine(loser, self.consensus, loser.miner, loser.miner_name)
        self.assertTrue(self.chain.add(extended).reorganization)
        alternate.add(extended)
        self.assertEqual(self.chain.main_hashes, alternate.main_hashes)
        self.assertEqual(self.chain.balance(loser.miner), 200)
        winner_before = first if loser == other else other
        self.assertEqual(self.chain.balance(winner_before.miner), 100)

    def test_persistence_and_consensus_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chain.sqlite3"
            saved = Blockchain(self.consensus, path)
            participant = "b" * 64
            self.assertEqual(saved.balance(participant), 0)
            saved.register_participant(participant)
            saved.register_participant(participant)
            self.assertEqual(saved.balance(participant, 6), 100)
            block = mine(saved.head, self.consensus)
            saved.add(block)
            saved.close()
            reopened = Blockchain(self.consensus, path)
            self.assertEqual(reopened.head, block)
            self.assertEqual(reopened.balance(participant), 100)
            self.assertEqual(reopened.balance(block.miner), 150)
            reopened.close()
            with self.assertRaisesRegex(ValueError, "otra red"):
                Blockchain(Consensus(difficulty=2), path)

    def test_paginated_locator_finds_long_fork(self):
        branch_point = self.chain.head
        for _ in range(250):
            self.chain.add(mine(self.chain.head, self.consensus))
        self.assertEqual(self.chain.locator()[-1], branch_point.hash)
        other = Blockchain(self.consensus)
        self.addCleanup(other.close)
        for _ in range(30):
            other.add(mine(other.head, self.consensus, "b" * 64, "Beto"))
        batch = self.chain.after_locator(other.locator())
        self.assertEqual(len(batch), 100)
        self.assertEqual(batch[0]["previous_hash"], branch_point.hash)
        while other.head.hash != self.chain.head.hash:
            for payload in self.chain.after_locator(other.locator()):
                other.add(Block.from_dict(payload))
        self.assertEqual(other.main_hashes, self.chain.main_hashes)

    def test_invalid_consensus_types(self):
        for values in (dict(difficulty=True), dict(reward=0), dict(network="")):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Consensus(**values)

    def test_rejects_reused_offer_and_keeps_losing_offer_pending(self):
        first = mine(self.chain.head, self.consensus)
        other = mine(self.chain.head, self.consensus, "b" * 64, "Beto")
        self.chain.add(first)
        self.chain.add(other)
        winner = self.chain.head
        loser = other if winner == first else first
        self.assertEqual([offer["id"] for offer in self.chain.pending_offers()], [loser.offer.id])
        with self.assertRaisesRegex(ValueError, "ya está incluida"):
            self.chain.add(mine(winner, self.consensus, offer=winner.offer))
        extended = mine(loser, self.consensus)
        self.chain.add(extended)
        self.assertEqual([offer["id"] for offer in self.chain.pending_offers()], [winner.offer.id])

    def test_adaptive_difficulty_uses_mining_duration_and_validates_on_every_branch(self):
        with patch("socketblock.models.INITIAL_DIFFICULTY", 64):
            consensus = Consensus()
            chain = Blockchain(consensus)
            self.addCleanup(chain.close)
            first_offer = Offer("a" * 64, "Ana", "Ronda rápida", now_ms() - 400_000)
            slow_offer = Offer("b" * 64, "Beto", "Ronda lenta", now_ms() - 400_000)
            first = mine(chain.head, consensus, offer=first_offer,
                         started_at=now_ms() - 300_000, duration=30_000)
            slow = mine(chain.head, consensus, offer=slow_offer,
                        started_at=now_ms() - 300_000, duration=240_000)
            chain.add(first)
            chain.add(slow)
            self.assertEqual(chain.next_difficulty(first), 128)
            self.assertEqual(chain.next_difficulty(slow), 32)
            wrong = mine(first, consensus, difficulty=32)
            with self.assertRaisesRegex(ValueError, "Dificultad incompatible"):
                chain.add(wrong)
            second = mine(first, consensus, difficulty=128)
            chain.add(second)
            parent = slow
            for _ in range(2):
                parent = mine(parent, consensus, difficulty=chain.next_difficulty(parent))
                chain.add(parent)
            self.assertGreater(parent.height, second.height)
            self.assertEqual(chain.head, second)

    def test_adaptive_difficulty_converges_to_target_after_hashrate_change(self):
        with patch("socketblock.models.INITIAL_DIFFICULTY", 64):
            consensus = Consensus()
            chain = Blockchain(consensus)
            self.addCleanup(chain.close)
            started_at = now_ms() - 180_000_000
            for hashrate in (2, 4):
                for _ in range(16):
                    difficulty = chain.next_difficulty()
                    offer = Offer("a" * 64, "Ana", f"Oferta {started_at}", started_at)
                    block = mine(chain.head, consensus, offer=offer, started_at=started_at,
                                 duration=difficulty * 1000 // hashrate, difficulty=difficulty)
                    chain.add(block)
                    started_at = block.timestamp + 3_600_000
                self.assertEqual(chain.next_difficulty(), hashrate * 120)


class StorageTests(unittest.TestCase):
    def test_persistent_identity_and_exclusive_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            lock = DataLock(path)
            try:
                first = load_identity(path, "Ana")
                self.assertEqual(load_identity(path, None), first)
                renamed = load_identity(path, "Ana 2")
                self.assertEqual(renamed.address, first.address)
                with self.assertRaisesRegex(ValueError, "Otro nodo"):
                    DataLock(path)
            finally:
                lock.close()
            DataLock(path).close()

    def test_name_required_for_new_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                load_identity(Path(directory), None)


if __name__ == "__main__":
    unittest.main()
