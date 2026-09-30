"""Encrypted local store for encounters, doctor credentials and the audit log.

* Encounter payloads are encrypted at rest with Fernet (AES-128-CBC + HMAC).
  The key lives in the user's data directory with owner-only permissions.
  Roadmap: protect the key with Windows DPAPI / TPM on HP devices.
* Only metadata needed for listing (id, time, status) is stored in clear.
* Every create, draft, sign and export is appended to an audit log, as the
  DPDP Rules expect logs to be retained for at least one year.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

from .models import Encounter

_SCHEMA = """
CREATE TABLE IF NOT EXISTS encounters (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    payload BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS doctors (
    doctor_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    pin_salt BLOB NOT NULL,
    pin_hash BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    encounter_id TEXT
);
"""

PBKDF2_ROUNDS = 200_000


def _load_or_create_key(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


class Store:
    def __init__(self, db_path: Path, key_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(_load_or_create_key(key_path))
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    # -- encounters --------------------------------------------------------
    def save(self, enc: Encounter) -> None:
        blob = self._fernet.encrypt(enc.model_dump_json().encode("utf-8"))
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO encounters(id, created_at, status, payload) VALUES (?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, payload=excluded.payload",
                (enc.id, enc.created_at.isoformat(), enc.status.value, blob),
            )

    def get(self, encounter_id: str) -> Encounter | None:
        row = self._conn.execute("SELECT payload FROM encounters WHERE id=?", (encounter_id,)).fetchone()
        if not row:
            return None
        return Encounter.model_validate_json(self._fernet.decrypt(row[0]))

    def list(self, limit: int = 50) -> list[Encounter]:
        rows = self._conn.execute(
            "SELECT payload FROM encounters ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Encounter.model_validate_json(self._fernet.decrypt(r[0])) for r in rows]

    # -- doctors -----------------------------------------------------------
    def set_doctor_pin(self, doctor_id: str, display_name: str, pin: str) -> None:
        if len(pin) < 4 or not pin.isdigit():
            raise ValueError("PIN must be at least 4 digits")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ROUNDS)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO doctors VALUES (?,?,?,?) ON CONFLICT(doctor_id) DO UPDATE SET "
                "display_name=excluded.display_name, pin_salt=excluded.pin_salt, pin_hash=excluded.pin_hash",
                (doctor_id, display_name, salt, digest),
            )

    def verify_doctor(self, doctor_id: str, pin: str) -> str | None:
        """Return the doctor's display name if the PIN is right."""
        row = self._conn.execute(
            "SELECT display_name, pin_salt, pin_hash FROM doctors WHERE doctor_id=?", (doctor_id,)
        ).fetchone()
        if not row:
            return None
        name, salt, expected = row
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ROUNDS)
        return name if hmac.compare_digest(digest, expected) else None

    def has_doctors(self) -> bool:
        return self._conn.execute("SELECT 1 FROM doctors LIMIT 1").fetchone() is not None

    # -- audit -------------------------------------------------------------
    def audit(self, actor: str, action: str, encounter_id: str | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit VALUES (?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), actor, action, encounter_id),
            )

    def audit_log(self, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            "SELECT ts, actor, action, encounter_id FROM audit ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(zip(("ts", "actor", "action", "encounter_id"), r)) for r in rows]


def note_fingerprint(enc: Encounter) -> str:
    """SHA-256 over the canonical signed content, stored at sign-off."""
    payload = {"id": enc.id, "note": enc.note.model_dump(mode="json") if enc.note else None}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
