from __future__ import annotations

import time
from collections import defaultdict

from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms

socketio = SocketIO()

# Track peers per sync room: { "sync:<library_id>": {sid, sid, ...} }
_room_peers: dict[str, set[str]] = defaultdict(set)

# Store last sync state per room for HTTP polling fallback
_room_sync_state: dict[str, dict] = {}

# Monotonically increasing version per room — clients ignore stale states
_room_version: dict[str, int] = defaultdict(int)

# Remove unused anchor tracking — server is the single authority


def _room_for(library_id: str) -> str:
    return f"sync:{library_id}"


def _peers_in_room(room: str, *, exclude: str | None = None) -> list[str]:
    peers = list(_room_peers.get(room, set()))
    if exclude and exclude in peers:
        peers.remove(exclude)
    return peers


def get_sync_state(room: str) -> dict | None:
    """Return the last known sync state for a room (for HTTP polling fallback)."""
    return _room_sync_state.get(room)


def init_sync(app):
    socketio.init_app(app, cors_allowed_origins="*")

    @socketio.on("connect")
    def handle_connect():
        pass

    @socketio.on("join_session")
    def handle_join(data):
        library_id = data.get("library_id", "").strip()
        if not library_id:
            return
        room = _room_for(library_id)
        join_room(room)
        sid = request.sid
        _room_peers[room].add(sid)

        # Tell everyone (including the joiner) about the new peer
        peer_count = len(_room_peers[room])
        emit(
            "peer_joined",
            {"peer_id": sid, "peer_count": peer_count, "peers": _peers_in_room(room)},
            to=room,
        )
        # Send direct reply to joiner with server time + current playback state
        sync_info = _room_sync_state.get(room)
        emit(
            "joined",
            {
                "peer_id": sid,
                "room": room,
                "server_time": time.time(),
                "sync_state": sync_info,
            },
        )

    @socketio.on("leave_session")
    def handle_leave(data):
        library_id = data.get("library_id", "").strip()
        if not library_id:
            return
        room = _room_for(library_id)
        leave_room(room)
        sid = request.sid
        _room_peers[room].discard(sid)
        if not _room_peers[room]:
            del _room_peers[room]
        peer_count = len(_room_peers.get(room, set()))
        emit(
            "peer_left",
            {"peer_id": sid, "peer_count": peer_count, "peers": _peers_in_room(room)},
            to=room,
        )

    @socketio.on("sync_action")
    def handle_sync_action(data):
        """Intentional user action — increments version, becomes authoritative state."""
        library_id = data.get("library_id", "").strip()
        action = data.get("action", "").strip()
        if not library_id or not action:
            return
        room = _room_for(library_id)
        sid = request.sid

        # Validate position is a finite number
        pos = data.get("position", 0)
        if not isinstance(pos, (int, float)) or not (-1 < pos < 86400):
            pos = 0

        # Increment room version
        _room_version[room] += 1

        state = {
            "action": action,
            "track_id": str(data.get("track_id", "")),
            "position": pos,
            "playing": bool(data.get("playing", action != "pause")),
            "peer_id": sid,
            "server_time": time.time(),
            "version": _room_version[room],
        }

        _room_sync_state[room] = state
        state["execute_at"] = state["server_time"] + 0.15
        emit("sync_action", state, to=room, include_self=False)

    @socketio.on("sync_state")
    def handle_sync_state(data):
        """Passive health report — does NOT overwrite authoritative state. Relayed for latency info only."""
        library_id = data.get("library_id", "").strip()
        if not library_id:
            return
        room = _room_for(library_id)
        data["peer_id"] = request.sid
        data["server_time"] = time.time()
        # Include current room version so clients know if they're stale
        data["version"] = _room_version.get(room, 0)
        # Do NOT overwrite _room_sync_state — this is not authoritative
        emit("sync_state", data, to=room, include_self=False)

    @socketio.on("disconnect")
    def handle_disconnect():
        sid = request.sid
        for room_name in list(rooms()):
            if room_name.startswith("sync:"):
                leave_room(room_name)
                _room_peers[room_name].discard(sid)
                if not _room_peers[room_name]:
                    del _room_peers[room_name]
                    _room_sync_state.pop(room_name, None)
                peer_count = len(_room_peers.get(room_name, set()))
                emit(
                    "peer_left",
                    {
                        "peer_id": sid,
                        "peer_count": peer_count,
                        "peers": _peers_in_room(room_name),
                    },
                    to=room_name,
                )


def broadcast_library_change(
    library_id: str, event_type: str, payload: dict | None = None
) -> None:
    """Notify all sync peers that the library has changed (add/delete/rename/reorder).

    Emits to the sync room for *library_id* with include_self=False so the
    triggering peer (which already updated its own UI) does not reload twice.
    """
    room = _room_for(library_id)
    data: dict = {
        "event": event_type,
        "library_id": library_id,
        "timestamp": time.time(),
    }
    if payload:
        data["payload"] = payload
    try:
        socketio.emit("library_changed", data, to=room)
    except RuntimeError:
        # socketio.emit raises RuntimeError if called outside of a SocketIO
        # request context and the server is not running (e.g. during tests).
        pass
