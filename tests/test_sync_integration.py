from __future__ import annotations

import unittest

from songwalk import create_app
from songwalk.sync import (
    _room_peers,
    _room_sync_state,
    _room_version,
    _room_for,
    get_sync_state,
    socketio,
)
from tests.test_app import new_test_dir


class SyncIntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _room_peers.clear()
        _room_sync_state.clear()
        _room_version.clear()
        self.temp_dir = new_test_dir()
        self.app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": self.temp_dir,
                "BASE_URL": "http://localhost:8080",
            }
        )

    def tearDown(self) -> None:
        pass

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _connect(self):
        client = socketio.test_client(self.app)
        self.addCleanup(self._safe_disconnect, client)
        return client

    def _safe_disconnect(self, client):
        if client.is_connected():
            client.disconnect()

    def _drain(self, client):
        return client.get_received()

    def _peer_id(self, client) -> str:
        """Return the server-assigned peer_id by joining a probe room."""
        client.emit("join_session", {"library_id": "__probe"})
        events = self._drain(client)
        joined = self._find_event(events, "joined")
        pid = joined["args"][0]["peer_id"]
        client.emit("leave_session", {"library_id": "__probe"})
        self._drain(client)
        return str(pid)

    def _join(self, client, library_id: str):
        client.emit("join_session", {"library_id": library_id})
        return self._drain(client)

    @staticmethod
    def _find_event(events, name: str):
        for e in events:
            if e["name"] == name:
                return e
        raise AssertionError(f"Event '{name}' not found in {events}")

    @staticmethod
    def _event_names(events):
        return [e["name"] for e in events]

    @staticmethod
    def _events_by_name(events, name: str):
        return [e for e in events if e["name"] == name]

    # ------------------------------------------------------------------
    # connect / disconnect
    # ------------------------------------------------------------------

    def test_client_connects(self):
        c = self._connect()
        self.assertTrue(c.is_connected())

    def test_disconnect_removes_peer_from_room(self):
        c = self._connect()
        pid = self._peer_id(c)
        self._join(c, "lib-1")

        room = _room_for("lib-1")
        self.assertIn(pid, _room_peers.get(room, set()))

        c.disconnect()
        self.assertNotIn(pid, _room_peers.get(room, set()))

    def test_disconnect_cleans_up_empty_rooms(self):
        c = self._connect()
        self._join(c, "lib-2")

        room = _room_for("lib-2")
        self.assertIn(room, _room_peers)
        c.disconnect()
        self.assertNotIn(room, _room_peers)

    # ------------------------------------------------------------------
    # join_session
    # ------------------------------------------------------------------

    def test_join_session_returns_joined_event(self):
        c = self._connect()
        events = self._join(c, "lib-3")

        names = self._event_names(events)
        self.assertIn("peer_joined", names)
        self.assertIn("joined", names)

        joined_data = self._find_event(events, "joined")["args"][0]
        self.assertIn("peer_id", joined_data)
        self.assertIn("server_time", joined_data)
        self.assertIn("sync_state", joined_data)

    def test_join_session_broadcasts_peer_joined_to_room(self):
        peer_a = self._connect()
        peer_b = self._connect()

        self._join(peer_a, "lib-4")
        self._join(peer_b, "lib-4")

        pid_b = self._peer_id(peer_b)
        events_a = self._drain(peer_a)
        pj_events = self._events_by_name(events_a, "peer_joined")
        pids = [e["args"][0]["peer_id"] for e in pj_events]
        self.assertIn(
            pid_b,
            pids,
            f"peer_a did not receive peer_joined for {pid_b}. Got pids: {pids}",
        )

    # ------------------------------------------------------------------
    # sync_action broadcast (not to sender)
    # ------------------------------------------------------------------

    def test_sync_action_broadcasts_to_peers_excluding_sender(self):
        peer_a = self._connect()
        peer_b = self._connect()

        for p in (peer_a, peer_b):
            self._join(p, "lib-5")
        self._drain(peer_a)
        self._drain(peer_b)

        peer_a.emit(
            "sync_action",
            {
                "library_id": "lib-5",
                "action": "play",
                "track_id": "track-1",
                "position": 10.5,
            },
        )

        events_a = self._drain(peer_a)
        self.assertNotIn(
            "sync_action",
            self._event_names(events_a),
            f"sender received its own sync_action: {events_a}",
        )

        events_b = self._drain(peer_b)
        sync_actions = self._events_by_name(events_b, "sync_action")
        self.assertEqual(len(sync_actions), 1)
        data = sync_actions[0]["args"][0]
        self.assertEqual(data["action"], "play")
        self.assertEqual(data["track_id"], "track-1")
        self.assertIn("server_time", data)
        self.assertIn("execute_at", data)
        self.assertIn("version", data)

    def test_sync_action_increments_room_version(self):
        c = self._connect()
        self._join(c, "lib-6")

        room = _room_for("lib-6")
        v0 = _room_version[room]

        c.emit(
            "sync_action", {"library_id": "lib-6", "action": "play", "track_id": "t"}
        )
        self.assertEqual(_room_version[room], v0 + 1)

        c.emit(
            "sync_action", {"library_id": "lib-6", "action": "pause", "track_id": "t"}
        )
        self.assertEqual(_room_version[room], v0 + 2)

    def test_sync_action_stores_state_for_polling(self):
        c = self._connect()
        self._join(c, "lib-7")

        c.emit(
            "sync_action",
            {
                "library_id": "lib-7",
                "action": "play",
                "track_id": "trk-99",
                "position": 55.0,
            },
        )
        self._drain(c)

        state = get_sync_state(_room_for("lib-7"))
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state["action"], "play")
        self.assertEqual(state["track_id"], "trk-99")
        self.assertEqual(state["position"], 55.0)

    # ------------------------------------------------------------------
    # peer_joined / peer_left events
    # ------------------------------------------------------------------

    def test_peer_left_on_disconnect_reaches_remaining_peers(self):
        peer_a = self._connect()
        peer_b = self._connect()

        pid_a = self._peer_id(peer_a)
        for p in (peer_a, peer_b):
            self._join(p, "lib-8")
        self._drain(peer_a)
        self._drain(peer_b)

        peer_a.disconnect()

        events_b = self._drain(peer_b)
        pl_events = self._events_by_name(events_b, "peer_left")
        pids = [e["args"][0]["peer_id"] for e in pl_events]
        self.assertIn(
            pid_a, pids, f"peer_b did not receive peer_left for {pid_a}: {events_b}"
        )

    def test_peer_left_on_leave_session_reaches_remaining_peers(self):
        peer_a = self._connect()
        peer_b = self._connect()

        pid_a = self._peer_id(peer_a)
        for p in (peer_a, peer_b):
            self._join(p, "lib-9")
        self._drain(peer_a)
        self._drain(peer_b)

        peer_a.emit("leave_session", {"library_id": "lib-9"})
        self._drain(peer_a)

        events_b = self._drain(peer_b)
        pl_events = self._events_by_name(events_b, "peer_left")
        pids = [e["args"][0]["peer_id"] for e in pl_events]
        self.assertIn(
            pid_a, pids, f"peer_b did not receive peer_left for {pid_a}: {events_b}"
        )

    def test_peer_joined_and_left_counts_are_accurate(self):
        peer_a = self._connect()
        pid_a = self._peer_id(peer_a)
        events = self._join(peer_a, "lib-10")
        pj = self._find_event(events, "peer_joined")
        self.assertEqual(pj["args"][0]["peer_count"], 1)
        self.assertEqual(pj["args"][0]["peers"], [pid_a])

        peer_b = self._connect()
        pid_b = self._peer_id(peer_b)
        self._join(peer_b, "lib-10")

        # peer_joined for peer_b is queued on peer_a — drain once
        events_a = self._drain(peer_a)
        pj_b = self._find_event(events_a, "peer_joined")
        self.assertEqual(pj_b["args"][0]["peer_count"], 2)
        self.assertCountEqual(pj_b["args"][0]["peers"], [pid_a, pid_b])

        peer_a.disconnect()
        events_b = self._drain(peer_b)
        pl = self._find_event(events_b, "peer_left")
        self.assertEqual(pl["args"][0]["peer_count"], 1)
        self.assertEqual(pl["args"][0]["peers"], [pid_b])

    # ------------------------------------------------------------------
    # broadcast_library_change
    # ------------------------------------------------------------------

    def test_broadcast_library_change_emits_to_room(self):
        c = self._connect()
        self._join(c, "lib-11")

        from songwalk.sync import broadcast_library_change

        broadcast_library_change("lib-11", "track_added", {"track_id": "t-new"})

        events = self._drain(c)
        lib_events = self._events_by_name(events, "library_changed")
        self.assertEqual(len(lib_events), 1)
        data = lib_events[0]["args"][0]
        self.assertEqual(data["event"], "track_added")
        self.assertEqual(data["library_id"], "lib-11")
        self.assertEqual(data["payload"]["track_id"], "t-new")
        self.assertIn("timestamp", data)

    def test_broadcast_library_change_no_payload(self):
        c = self._connect()
        self._join(c, "lib-12")

        from songwalk.sync import broadcast_library_change

        broadcast_library_change("lib-12", "track_deleted")

        events = self._drain(c)
        lib_events = self._events_by_name(events, "library_changed")
        self.assertEqual(len(lib_events), 1)
        data = lib_events[0]["args"][0]
        self.assertEqual(data["event"], "track_deleted")
        self.assertNotIn("payload", data)

    # ------------------------------------------------------------------
    # sync_state relay
    # ------------------------------------------------------------------

    def test_sync_state_relays_to_peers_excluding_sender(self):
        peer_a = self._connect()
        peer_b = self._connect()

        pid_a = self._peer_id(peer_a)
        for p in (peer_a, peer_b):
            self._join(p, "lib-13")
        self._drain(peer_a)
        self._drain(peer_b)

        peer_a.emit(
            "sync_state",
            {
                "library_id": "lib-13",
                "position": 42.0,
                "playing": True,
            },
        )

        events_a = self._drain(peer_a)
        self.assertNotIn(
            "sync_state",
            self._event_names(events_a),
            f"sender received relayed sync_state: {events_a}",
        )

        events_b = self._drain(peer_b)
        states = self._events_by_name(events_b, "sync_state")
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0]["args"][0]["peer_id"], pid_a)
        self.assertIn("server_time", states[0]["args"][0])
        self.assertIn("version", states[0]["args"][0])

    # ------------------------------------------------------------------
    # edge cases
    # ------------------------------------------------------------------

    def test_join_session_rejects_empty_library_id(self):
        c = self._connect()
        c.emit("join_session", {"library_id": ""})
        events = self._drain(c)
        self.assertEqual(events, [])

    def test_sync_action_rejects_empty_library_id(self):
        peer_a = self._connect()
        peer_b = self._connect()
        for p in (peer_a, peer_b):
            self._join(p, "lib-14")
        self._drain(peer_a)
        self._drain(peer_b)

        peer_a.emit("sync_action", {"library_id": "", "action": "play"})
        events_b = self._drain(peer_b)
        self.assertNotIn("sync_action", self._event_names(events_b))

    def test_sync_action_rejects_empty_action(self):
        peer_a = self._connect()
        peer_b = self._connect()
        for p in (peer_a, peer_b):
            self._join(p, "lib-15")
        self._drain(peer_a)
        self._drain(peer_b)

        peer_a.emit("sync_action", {"library_id": "lib-15", "action": ""})
        events_b = self._drain(peer_b)
        self.assertNotIn("sync_action", self._event_names(events_b))

    def test_multiple_rooms_isolation(self):
        peer_a = self._connect()
        pid_a = self._peer_id(peer_a)

        self._join(peer_a, "lib-alpha")
        self._join(peer_a, "lib-beta")

        self.assertIn(pid_a, _room_peers.get(_room_for("lib-alpha"), set()))
        self.assertIn(pid_a, _room_peers.get(_room_for("lib-beta"), set()))

        peer_a.emit("leave_session", {"library_id": "lib-alpha"})
        self._drain(peer_a)

        self.assertNotIn(pid_a, _room_peers.get(_room_for("lib-alpha"), set()))
        self.assertIn(pid_a, _room_peers.get(_room_for("lib-beta"), set()))


if __name__ == "__main__":
    unittest.main()
