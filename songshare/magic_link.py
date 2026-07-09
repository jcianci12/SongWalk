import json
import time
from pathlib import Path
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from uuid import uuid4

TOKEN_MAX_AGE = 86400  # 24 hours


class MagicLinkStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._secret = self._load_or_create_secret()
        self._serializer = URLSafeTimedSerializer(self._secret)
        self._mapping_path = data_dir / "user-libraries.json"

    def _load_or_create_secret(self) -> str:
        secret_path = self._data_dir / "magic-link-secret.txt"
        if secret_path.exists():
            return secret_path.read_text(encoding="utf-8").strip()
        secret = uuid4().hex + uuid4().hex
        secret_path.write_text(secret, encoding="utf-8")
        return secret

    def _load_mappings(self) -> dict:
        if not self._mapping_path.exists():
            return {}
        return json.loads(self._mapping_path.read_text(encoding="utf-8"))

    def _save_mappings(self, mappings: dict) -> None:
        self._mapping_path.write_text(json.dumps(mappings, indent=2), encoding="utf-8")

    def generate_token(self, email: str) -> str:
        return self._serializer.dumps({"email": email})

    def verify_token(self, token: str) -> str | None:
        try:
            data = self._serializer.loads(token, max_age=TOKEN_MAX_AGE)
            return data.get("email")
        except (BadSignature, SignatureExpired):
            return None

    def get_library_id(self, email: str) -> str | None:
        mappings = self._load_mappings()
        entry = mappings.get(email.lower().strip())
        return entry["library_id"] if entry else None

    def set_library_id(self, email: str, library_id: str) -> None:
        mappings = self._load_mappings()
        key = email.lower().strip()
        mappings[key] = {
            "email": key,
            "library_id": library_id,
            "created_at": time.time(),
        }
        self._save_mappings(mappings)
