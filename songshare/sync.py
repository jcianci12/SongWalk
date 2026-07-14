from __future__ import annotations

import time

from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms

socketio = SocketIO()


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
        room = f"sync:{library_id}"
        join_room(room)
        peer_id = request.sid
        emit(
            "peer_joined",
            {"peer_id": peer_id, "action": "peer_joined"},
            to=room,
            include_self=False,
        )
        emit("joined", {"peer_id": peer_id, "room": room})

    @socketio.on("leave_session")
    def handle_leave(data):
        library_id = data.get("library_id", "").strip()
        if not library_id:
            return
        room = f"sync:{library_id}"
        leave_room(room)
        emit("peer_left", {"peer_id": request.sid, "action": "peer_left"}, to=room)

    @socketio.on("sync_action")
    def handle_sync_action(data):
        library_id = data.get("library_id", "").strip()
        action = data.get("action", "").strip()
        if not library_id or not action:
            return
        room = f"sync:{library_id}"
        data["peer_id"] = request.sid
        data["timestamp"] = time.time()
        emit("sync_action", data, to=room, include_self=False)

    @socketio.on("sync_state")
    def handle_sync_state(data):
        library_id = data.get("library_id", "").strip()
        if not library_id:
            return
        room = f"sync:{library_id}"
        data["peer_id"] = request.sid
        data["timestamp"] = time.time()
        emit("sync_state", data, to=room, include_self=False)

    @socketio.on("disconnect")
    def handle_disconnect():
        for room_name in rooms():
            if room_name.startswith("sync:"):
                emit(
                    "peer_left",
                    {"peer_id": request.sid, "action": "peer_left"},
                    to=room_name,
                )
