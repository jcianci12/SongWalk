from __future__ import annotations

import time
from collections import defaultdict

from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms

socketio = SocketIO()

# Track peers per sync room: { "sync:<library_id>": {sid, sid, ...} }
_room_peers: dict[str, set[str]] = defaultdict(set)


def _room_for(library_id: str) -> str:
    return f"sync:{library_id}"


def _peers_in_room(room: str, *, exclude: str | None = None) -> list[str]:
    peers = list(_room_peers.get(room, set()))
    if exclude and exclude in peers:
        peers.remove(exclude)
    return peers


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
        library_id = data.get("library_id", "").strip()
        action = data.get("action", "").strip()
        if not library_id or not action:
            return
        room = _room_for(library_id)
        data["peer_id"] = request.sid
        data["timestamp"] = time.time()
        emit("sync_action", data, to=room, include_self=False)

    @socketio.on("sync_state")
    def handle_sync_state(data):
        library_id = data.get("library_id", "").strip()
        if not library_id:
            return
        room = _room_for(library_id)
        data["peer_id"] = request.sid
        data["timestamp"] = time.time()
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
