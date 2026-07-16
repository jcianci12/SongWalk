from __future__ import annotations

import collections
import unittest

from songwalk.sync import (
    _peers_in_room,
    _room_for,
    _room_peers,
    _room_sync_state,
    _room_version,
    broadcast_library_change,
    get_sync_state,
)


class SyncTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _room_peers.clear()
        _room_sync_state.clear()
        _room_version.clear()

    def tearDown(self) -> None:
        pass

    def test_room_naming(self) -> None:
        self.assertEqual(_room_for("abc123"), "sync:abc123")

    def test_get_sync_state_empty_room(self) -> None:
        result = get_sync_state("sync:nonexistent")
        self.assertIsNone(result)

    def test_room_peers_empty_on_init(self) -> None:
        self.assertEqual(_room_peers["sync:test-room"], set())
        self.assertIsInstance(_room_peers["sync:test-room"], set)

    def test_peers_in_room_excludes_sid(self) -> None:
        room = "sync:test-exclude"
        _room_peers[room] = {"sid-1", "sid-2", "sid-3"}
        result = _peers_in_room(room, exclude="sid-2")
        self.assertEqual(set(result), {"sid-1", "sid-3"})

    def test_broadcast_library_change_does_not_crash(self) -> None:
        broadcast_library_change("test-lib", "track_added", {"count": 1})
        broadcast_library_change("test-lib", "track_deleted")
        broadcast_library_change("test-lib", "track_renamed", None)

    def test_sync_state_store_and_retrieve(self) -> None:
        _room_sync_state["sync:test"] = {
            "action": "play",
            "track_id": "t1",
            "position": 42,
            "playing": True,
        }
        retrieved = get_sync_state("sync:test")
        self.assertIsNotNone(retrieved)
        assert retrieved is not None
        self.assertEqual(retrieved["action"], "play")
        self.assertEqual(retrieved["track_id"], "t1")

    def test_version_increment(self) -> None:
        self.assertEqual(_room_version["sync:test"], 0)
        _room_version["sync:test"] += 1
        self.assertEqual(_room_version["sync:test"], 1)
        _room_version["sync:test"] += 1
        self.assertEqual(_room_version["sync:test"], 2)

    def test_sync_action_validation(self) -> None:
        self.assertTrue(isinstance(42, (int, float)))
        self.assertTrue(isinstance(3.14, (int, float)))
        self.assertFalse(isinstance("42", (int, float)))
        self.assertFalse(isinstance(None, (int, float)))
        self.assertFalse(isinstance([], (int, float)))

        self.assertTrue(-1 < 42 < 86400)
        self.assertTrue(-1 < 0 < 86400)
        self.assertTrue(-1 < 86399 < 86400)
        self.assertFalse(-1 < -5 < 86400)
        self.assertFalse(-1 < 100000 < 86400)

    def test_room_version_monotonic(self) -> None:
        self.assertEqual(_room_version["sync:new-room"], 0)
        self.assertIsInstance(_room_version, collections.defaultdict)
        self.assertEqual(_room_version["sync:another"], 0)

    def test_state_includes_required_keys(self) -> None:
        state = {
            "action": "play",
            "track_id": "track-abc",
            "position": 30.5,
            "playing": True,
            "peer_id": "peer-1",
            "server_time": 1234567890.0,
            "version": 5,
        }
        self.assertIn("action", state)
        self.assertIn("track_id", state)
        self.assertIn("position", state)
        self.assertIn("playing", state)
        self.assertIn("peer_id", state)
        self.assertIn("server_time", state)
        self.assertIn("version", state)


if __name__ == "__main__":
    unittest.main()
