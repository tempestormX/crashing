#!/usr/bin/env python3
"""Equilibrium's local, privacy-preserving multi-account API server.

Run: python3 server.py
Then open http://127.0.0.1:8000. The SQLite database is created in database/equilibrium.db.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def load_local_env(path: Path) -> None:
    """Load a gitignored local .env without replacing deployment secrets."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, value.removeprefix('"').removesuffix('"').removeprefix("'").removesuffix("'"))


load_local_env(ROOT / ".env")
DATABASE_DIR = ROOT / "database"
DATABASE_PATH = DATABASE_DIR / "equilibrium.db"
SCHEMA_PATH = DATABASE_DIR / "schema.sql"
POLICY_VERSION = "2026-07-20"
SESSION_DAYS = 14
MAX_BODY_BYTES = 16_384
DEMO_EMAIL = "anu@equilibrium.student"
DEMO_NAME = "Anu"
DEMO_PASSWORD = "Anu@Equilibrium26"
REFLECTION_MODEL = os.environ.get("OPENAI_REFLECTION_MODEL", "gpt-5.4-mini")
REFLECTION_PROVIDER = os.environ.get("EQUILIBRIUM_REFLECTION_PROVIDER", "openai").strip().lower()
REFLECTION_PROVIDERS = {"openai", "gemini", "mistral"}
FIREBASE_REQUIRED_SETTINGS = ("FIREBASE_PROJECT_ID", "FIREBASE_WEB_API_KEY", "FIREBASE_MESSAGING_SENDER_ID", "FIREBASE_APP_ID", "FIREBASE_VAPID_KEY")
SUPABASE_AUTH_SETTINGS = ("SUPABASE_URL", "SUPABASE_ANON_KEY")
SUPABASE_SYNC_SETTINGS = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
EXTERNAL_ACTIONS = {"notification", "counsellor_referral", "summary_share"}


def fcm_web_configured() -> bool:
    return all(os.environ.get(name) for name in FIREBASE_REQUIRED_SETTINGS)


def device_cipher():
    """Return the approved at-rest encryption primitive, or None when unavailable."""
    encryption_key = os.environ.get("EQUILIBRIUM_DEVICE_ENCRYPTION_KEY")
    if not encryption_key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(encryption_key.encode("utf-8"))
    except (ImportError, ValueError):
        return None


def fcm_registration_ready() -> bool:
    return fcm_web_configured() and device_cipher() is not None


def fcm_sender_ready() -> bool:
    """True only when a reviewed sender has been deliberately enabled."""
    credentials_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_FILE")
    configured = (
        fcm_registration_ready()
        and os.environ.get("EQUILIBRIUM_FCM_SENDER_ENABLED") == "1"
        and bool(credentials_path and Path(credentials_path).is_file())
    )
    if not configured:
        return False
    try:
        from google.auth.transport.requests import AuthorizedSession  # noqa: F401
        from google.oauth2 import service_account  # noqa: F401
    except ImportError:
        return False
    return True


def supabase_auth_enabled() -> bool:
    return os.environ.get("EQUILIBRIUM_SUPABASE_AUTH") == "1" and all(os.environ.get(name) for name in SUPABASE_AUTH_SETTINGS)


def supabase_sync_enabled() -> bool:
    return os.environ.get("EQUILIBRIUM_SUPABASE_SYNC") == "1" and all(os.environ.get(name) for name in SUPABASE_SYNC_SETTINGS)


def langgraph_actions_ready() -> bool:
    if os.environ.get("EQUILIBRIUM_LANGGRAPH_ACTIONS") != "1":
        return False
    try:
        import langgraph  # noqa: F401
    except ImportError:
        return False
    return True


def firebase_public_config() -> dict[str, str]:
    return {
        "apiKey": os.environ["FIREBASE_WEB_API_KEY"],
        "authDomain": f"{os.environ['FIREBASE_PROJECT_ID']}.firebaseapp.com",
        "projectId": os.environ["FIREBASE_PROJECT_ID"],
        "messagingSenderId": os.environ["FIREBASE_MESSAGING_SENDER_ID"],
        "appId": os.environ["FIREBASE_APP_ID"],
        "vapidKey": os.environ["FIREBASE_VAPID_KEY"],
    }


def reflection_provider_details() -> tuple[str, str | None, str | None]:
    """Return the selected provider and its server-side model/key configuration.

    The browser never receives any of these credential values.  Existing OpenAI
    behaviour remains the default when no provider flag is supplied.
    """
    if REFLECTION_PROVIDER == "openai":
        return "openai", os.environ.get("OPENAI_API_KEY"), REFLECTION_MODEL
    if REFLECTION_PROVIDER == "gemini":
        return "gemini", os.environ.get("GEMINI_API_KEY"), os.environ.get("GEMINI_REFLECTION_MODEL")
    if REFLECTION_PROVIDER == "mistral":
        return "mistral", os.environ.get("MISTRAL_API_KEY"), os.environ.get("MISTRAL_REFLECTION_MODEL")
    return REFLECTION_PROVIDER, None, None


def reflection_provider_configured() -> bool:
    provider, api_key, model = reflection_provider_details()
    return provider in REFLECTION_PROVIDERS and bool(api_key and model)


def integration_status() -> dict[str, Any]:
    """Expose readiness booleans only; never expose any integration secrets."""
    provider, _, model = reflection_provider_details()
    return {
        "reflection": {"provider": provider, "configured": reflection_provider_configured(), "model": model},
        "notifications": {
            "fcmConfigured": fcm_web_configured(),
            "fcmRegistrationReady": fcm_registration_ready(),
            "fcmSenderEnabled": os.environ.get("EQUILIBRIUM_FCM_SENDER_ENABLED") == "1",
            "fcmSenderReady": fcm_sender_ready(),
            "scheduledDeliveryReady": fcm_sender_ready() and bool(os.environ.get("EQUILIBRIUM_JOB_SECRET")),
            "requiresHttps": True,
        },
        "sharedStorage": {
            "supabaseAuthEnabled": supabase_auth_enabled(),
            "supabaseSyncConfigured": all(os.environ.get(name) for name in SUPABASE_SYNC_SETTINGS),
            "syncEnabled": supabase_sync_enabled(),
            "manualSyncRequired": True,
        },
        "orchestration": {
            "langgraphConfigured": langgraph_actions_ready(),
            "humanApprovalRequired": True,
            "actions": {"notification": fcm_sender_ready(), "counsellorReferral": bool(os.environ.get("EQUILIBRIUM_COUNSELLOR_WEBHOOK_URL") and os.environ.get("EQUILIBRIUM_COUNSELLOR_REFERRAL_ENABLED") == "1"), "summaryShare": bool(os.environ.get("EQUILIBRIUM_SUMMARY_WEBHOOK_URL") and os.environ.get("EQUILIBRIUM_SUMMARY_SHARE_ENABLED") == "1")},
        },
    }


def reflection_request(provider: str, api_key: str, model: str, instructions: str, text: str) -> urllib.request.Request:
    """Build a provider request without retaining the student's reflection."""
    if provider == "openai":
        return urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps({"model": model, "instructions": instructions, "input": text, "max_output_tokens": 450}).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
    if provider == "gemini":
        encoded_model = urllib.parse.quote(model, safe="-._")
        encoded_key = urllib.parse.quote(api_key, safe="")
        body = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"maxOutputTokens": 450},
        }
        return urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{encoded_model}:generateContent?key={encoded_key}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    if provider == "mistral":
        body = {
            "model": model,
            "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": text}],
            "max_tokens": 450,
        }
        return urllib.request.Request(
            "https://api.mistral.ai/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
    raise ValueError("Choose a supported reflection provider.")


def reflection_text(provider: str, result: dict[str, Any]) -> str:
    if provider == "openai":
        return str(result.get("output_text", "")).strip()
    if provider == "gemini":
        candidates = result.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        return "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
    if provider == "mistral":
        choices = result.get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        if isinstance(content, list):
            return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict)).strip()
        return str(content).strip()
    return ""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    database = sqlite3.connect(DATABASE_PATH)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    return database


def initialise_database() -> None:
    DATABASE_DIR.mkdir(exist_ok=True)
    with connect() as database:
        database.executescript(SCHEMA_PATH.read_text())
        # Existing local databases predate the optional Supabase identity link.
        # SQLite's CREATE TABLE IF NOT EXISTS does not add new columns.
        account_columns = {row["name"] for row in database.execute("PRAGMA table_info(accounts)")}
        if "supabase_user_id" not in account_columns:
            database.execute("ALTER TABLE accounts ADD COLUMN supabase_user_id TEXT")
        database.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_supabase_user ON accounts(supabase_user_id)")
        preference_columns = {row["name"] for row in database.execute("PRAGMA table_info(notification_preferences)")}
        if "timezone_offset_minutes" not in preference_columns:
            database.execute("ALTER TABLE notification_preferences ADD COLUMN timezone_offset_minutes INTEGER")


def ensure_demo_account() -> None:
    """Make the requested local demo account available without exposing its password."""
    with connect() as database:
        exists = database.execute("SELECT 1 FROM accounts WHERE email = ?", (DEMO_EMAIL,)).fetchone()
        if not exists:
            account_id = str(uuid.uuid4())
            database.execute(
                "INSERT INTO accounts(id, email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (account_id, DEMO_EMAIL, DEMO_NAME, password_hash(DEMO_PASSWORD), now()),
            )
            audit(database, account_id, "demo_account_created")


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    return "pbkdf2_sha256$600000$%s$%s" % (
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def password_matches(password: str, encoded: str) -> bool:
    algorithm, rounds, salt, expected = encoded.split("$", 3)
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(rounds))
    return hmac.compare_digest(base64.b64encode(digest).decode("ascii"), expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def audit(database: sqlite3.Connection, account_id: str | None, action: str, details: dict[str, Any] | None = None) -> None:
    database.execute(
        "INSERT INTO audit_events(id, account_id, action, created_at, details) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), account_id, action, now(), json.dumps(details or {})),
    )


def current_consent(database: sqlite3.Connection, account_id: str) -> bool:
    row = database.execute(
        "SELECT granted FROM consent_events WHERE account_id = ? AND scope = 'cloud_trial_summaries' ORDER BY created_at DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    return bool(row and row["granted"])


def create_local_session(database: sqlite3.Connection, account_id: str) -> tuple[str, str]:
    """Create Equilibrium's own short-lived bearer session after authentication."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    database.execute(
        "INSERT INTO account_sessions(token_hash, account_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token_hash(token), account_id, now(), expires),
    )
    return token, expires


def supabase_request(path: str, payload: dict[str, Any], *, service_role: bool = False) -> dict[str, Any]:
    """Call Supabase only from an explicitly enabled adapter; never return keys."""
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key_name = "SUPABASE_SERVICE_ROLE_KEY" if service_role else "SUPABASE_ANON_KEY"
    api_key = os.environ.get(key_name, "")
    if not base_url or not api_key:
        raise RuntimeError("Supabase credentials are not configured.")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"apikey": api_key, "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        # Provider body can contain sensitive details; retain only a safe status.
        raise RuntimeError(f"Supabase request failed (HTTP {error.code}).") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("Supabase could not be reached.") from error


def supabase_auth(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return supabase_request(path, payload, service_role=False)


def supabase_rest(table: str, payload: dict[str, Any], *, upsert: bool = False, on_conflict: str | None = None) -> dict[str, Any]:
    """Server-only write to the reviewed Equilibrium schema in Supabase."""
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base_url or not service_key:
        raise RuntimeError("Supabase sync credentials are not configured.")
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Content-Profile": "equilibrium",
        "Prefer": "return=minimal" + (",resolution=merge-duplicates" if upsert else ""),
    }
    query = f"?on_conflict={urllib.parse.quote(on_conflict, safe='_')}" if on_conflict else ""
    request = urllib.request.Request(f"{base_url}/rest/v1/{urllib.parse.quote(table, safe='_-')}{query}", data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Supabase sync failed (HTTP {error.code}).") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("Supabase sync could not be reached.") from error


def supabase_delete_for_student(table: str, owner_column: str, student_id: str) -> None:
    """Server-only deletion for a student who explicitly removes synced data."""
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base_url or not service_key:
        raise RuntimeError("Supabase sync credentials are not configured.")
    query = urllib.parse.urlencode({owner_column: f"eq.{student_id}"})
    request = urllib.request.Request(
        f"{base_url}/rest/v1/{urllib.parse.quote(table, safe='_-')}?{query}",
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}", "Content-Profile": "equilibrium", "Prefer": "return=minimal"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"Supabase deletion failed (HTTP {response.status}).")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Supabase deletion failed (HTTP {error.code}).") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("Supabase deletion could not be reached.") from error


def queue_supabase_event(database: sqlite3.Connection, account_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Queue a minimal allowed aggregate; this does not make a network call."""
    database.execute(
        "INSERT INTO supabase_sync_outbox(id, account_id, event_type, payload_json, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
        (str(uuid.uuid4()), account_id, event_type, json.dumps(payload), now()),
    )


def sync_account_outbox(database: sqlite3.Connection, account: sqlite3.Row, limit: int = 50, *, deletions_only: bool = False) -> dict[str, int]:
    """Manually flush an account's approved aggregate queue; never sync raw data."""
    if not supabase_sync_enabled():
        raise RuntimeError("Supabase sync is disabled until the reviewed environment flag is enabled.")
    student_id = account["supabase_user_id"]
    if not student_id:
        raise RuntimeError("Link this account to Supabase Auth before synchronising data.")
    query = "SELECT * FROM supabase_sync_outbox WHERE account_id = ? AND status IN ('pending', 'failed', 'blocked')"
    if deletions_only:
        query += " AND event_type = 'deletion'"
    rows = database.execute(query + " ORDER BY created_at LIMIT ?", (account["id"], limit)).fetchall()
    outcome = {"synced": 0, "failed": 0, "blocked": 0}
    for row in rows:
        payload = json.loads(row["payload_json"])
        try:
            if row["event_type"] == "consent":
                supabase_rest("consent_ledger", {"id": row["id"], "student_id": student_id, "purpose": "aggregate_cadence_storage", **payload})
            elif row["event_type"] == "trial":
                supabase_rest("aggregate_cadence_trials", {"id": payload.pop("id"), "student_id": student_id, **payload})
            elif row["event_type"] == "notification_preference":
                supabase_rest("notification_preferences", {"student_id": student_id, **payload}, upsert=True, on_conflict="student_id")
            elif row["event_type"] == "fcm_registration":
                supabase_rest("fcm_device_registrations", {"id": row["id"], "student_id": student_id, **payload})
            elif row["event_type"] == "deletion":
                supabase_delete_for_student("aggregate_cadence_trials", "student_id", student_id)
                supabase_delete_for_student("notification_preferences", "student_id", student_id)
                supabase_delete_for_student("fcm_device_registrations", "student_id", student_id)
                supabase_delete_for_student("community_reports", "reporter_id", student_id)
                supabase_delete_for_student("community_posts", "author_id", student_id)
            else:
                raise RuntimeError("Unsupported sync event.")
        except RuntimeError as error:
            database.execute("UPDATE supabase_sync_outbox SET status = 'failed', attempts = attempts + 1, last_error = ? WHERE id = ?", (str(error)[:160], row["id"]))
            outcome["failed"] += 1
        else:
            database.execute("UPDATE supabase_sync_outbox SET status = 'synced', attempts = attempts + 1, last_error = NULL, synced_at = ? WHERE id = ?", (now(), row["id"]))
            outcome["synced"] += 1
    return outcome


def fcm_send(registration_token: str, title: str, body: str) -> str:
    """Send one approved notification through FCM HTTP v1, never from the browser."""
    if not fcm_sender_ready():
        raise RuntimeError("FCM delivery is not enabled on this server.")
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError as error:
        raise RuntimeError("Install google-auth before enabling FCM delivery.") from error
    credentials = service_account.Credentials.from_service_account_file(
        os.environ["FIREBASE_SERVICE_ACCOUNT_FILE"],
        scopes=["https://www.googleapis.com/auth/firebase.messaging"],
    )
    session = AuthorizedSession(credentials)
    response = session.post(
        f"https://fcm.googleapis.com/v1/projects/{os.environ['FIREBASE_PROJECT_ID']}/messages:send",
        json={"message": {"token": registration_token, "notification": {"title": title, "body": body}, "webpush": {"fcm_options": {"link": "/"}}}},
        timeout=15,
    )
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"FCM rejected the message (HTTP {response.status_code}).")
    return str((response.json() or {}).get("name") or "sent")


def post_approved_webhook(url: str, payload: dict[str, Any]) -> None:
    """Strict HTTPS-only connector for a reviewed campus/share service."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("The external action endpoint must use HTTPS.")
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"The external action endpoint returned HTTP {response.status}.")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"The external action endpoint returned HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("The external action endpoint could not be reached.") from error


def in_quiet_hours(utc_now: datetime, quiet_start: str | None, quiet_end: str | None, offset_minutes: int | None) -> bool:
    if not quiet_start or not quiet_end or offset_minutes is None:
        return False
    local = utc_now - timedelta(minutes=offset_minutes)
    minute = local.hour * 60 + local.minute
    start = int(quiet_start[:2]) * 60 + int(quiet_start[3:])
    end = int(quiet_end[:2]) * 60 + int(quiet_end[3:])
    return start <= minute < end if start <= end else minute >= start or minute < end


class EquilibriumHandler(SimpleHTTPRequestHandler):
    server_version = "Equilibrium/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        # Avoid emitting credentials or request bodies to the terminal.
        if not self.path.startswith("/api/"):
            super().log_message(format, *args)

    def json_response(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_BODY_BYTES:
            raise ValueError("Request body must be between 1 and 16 KB.")
        parsed = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object.")
        return parsed

    def account_from_token(self, database: sqlite3.Connection) -> sqlite3.Row | None:
        prefix, _, token = self.headers.get("Authorization", "").partition(" ")
        if prefix != "Bearer" or not token:
            return None
        return database.execute(
            """SELECT accounts.* FROM account_sessions
               JOIN accounts ON accounts.id = account_sessions.account_id
               WHERE account_sessions.token_hash = ? AND account_sessions.revoked_at IS NULL
                 AND account_sessions.expires_at > ? AND accounts.disabled_at IS NULL""",
            (token_hash(token), now()),
        ).fetchone()

    @staticmethod
    def public_account(account: sqlite3.Row) -> dict[str, str]:
        return {"id": account["id"], "email": account["email"], "displayName": account["display_name"]}

    def require_account(self, database: sqlite3.Connection) -> sqlite3.Row | None:
        account = self.account_from_token(database)
        if not account:
            self.json_response({"error": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
        return account

    def do_POST(self) -> None:
        if not self.path.startswith("/api/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            if self.path == "/api/auth/logout":
                self.logout()
                return
            payload = self.read_json()
            if self.path == "/api/auth/register":
                self.register(payload)
            elif self.path == "/api/auth/login":
                self.login(payload)
            elif self.path == "/api/auth/migrate-to-supabase":
                self.migrate_account_to_supabase(payload)
            elif self.path == "/api/consents/cloud-trial-summaries":
                self.set_consent(payload)
            elif self.path == "/api/trials":
                self.create_trial(payload)
            elif self.path == "/api/checkins":
                self.create_checkin(payload)
            elif self.path == "/api/reflection":
                self.create_reflection(payload)
            elif self.path == "/api/integrations/notifications/preference":
                self.set_notification_preference(payload)
            elif self.path == "/api/integrations/fcm/registrations":
                self.register_fcm_device(payload)
            elif self.path == "/api/integrations/supabase/sync":
                self.sync_supabase(payload)
            elif self.path == "/api/integrations/fcm/process-due":
                self.process_due_notifications(payload)
            elif self.path == "/api/actions/proposals":
                self.create_action_proposal(payload)
            elif self.path.startswith("/api/actions/") and self.path.endswith("/decision"):
                self.decide_action_proposal(payload)
            elif self.path == "/api/community/posts":
                self.create_community_post(payload)
            elif self.path.startswith("/api/community/posts/") and self.path.endswith("/report"):
                self.report_community_post(payload)
            else:
                self.json_response({"error": "Unknown API route."}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as error:
            self.json_response({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as error:
            self.json_response({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except sqlite3.IntegrityError:
            self.json_response({"error": "That record already exists or is not valid."}, HTTPStatus.CONFLICT)

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self.json_response({
                "ok": True,
                "storage": "sqlite",
                "policyVersion": POLICY_VERSION,
                "reflectionConfigured": reflection_provider_configured(),
                "reflectionProvider": REFLECTION_PROVIDER,
                "reflectionModel": reflection_provider_details()[2],
            })
        elif self.path == "/api/integrations/status":
            with connect() as database:
                if self.require_account(database):
                    self.json_response(integration_status())
        elif self.path == "/api/integrations/firebase-config":
            if not fcm_web_configured():
                self.json_response({"error": "Firebase Cloud Messaging is not configured on this server."}, HTTPStatus.SERVICE_UNAVAILABLE)
            else:
                self.json_response(firebase_public_config())
        elif self.path == "/api/integrations/notifications/preference":
            with connect() as database:
                account = self.require_account(database)
                if account:
                    preference = database.execute(
                        "SELECT fcm_enabled, quiet_start, quiet_end, timezone_offset_minutes, updated_at FROM notification_preferences WHERE account_id = ?",
                        (account["id"],),
                    ).fetchone()
                    self.json_response({"preference": dict(preference) if preference else {"fcm_enabled": 0, "quiet_start": None, "quiet_end": None, "timezone_offset_minutes": None}})
        elif self.path == "/api/actions/proposals":
            with connect() as database:
                account = self.require_account(database)
                if account:
                    proposals = [dict(row) for row in database.execute(
                        "SELECT id, action, destination, status, created_at, decided_at, completed_at, result_json FROM external_action_proposals WHERE account_id = ? ORDER BY created_at DESC LIMIT 30",
                        (account["id"],),
                    )]
                    self.json_response({"proposals": proposals})
        elif self.path == "/api/me":
            with connect() as database:
                account = self.require_account(database)
                if account:
                    self.json_response({"account": self.public_account(account), "cloudTrialSummaries": current_consent(database, account["id"])})
        elif self.path == "/api/trials":
            with connect() as database:
                account = self.require_account(database)
                if account:
                    trials = [dict(row) for row in database.execute(
                        "SELECT id, timing_events, median_ms, variability_pct, correction_count, long_pause_count, client_created_at, stored_at FROM cadence_trials WHERE account_id = ? ORDER BY stored_at DESC LIMIT 100",
                        (account["id"],),
                    )]
                    self.json_response({"trials": trials})
        elif self.path == "/api/community/posts":
            self.list_community_posts()
        else:
            super().do_GET()

    def do_DELETE(self) -> None:
        if self.path != "/api/me/data":
            self.json_response({"error": "Unknown API route."}, HTTPStatus.NOT_FOUND)
            return
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            database.execute("DELETE FROM cadence_checkins WHERE account_id = ?", (account["id"],))
            database.execute("DELETE FROM cadence_trials WHERE account_id = ?", (account["id"],))
            database.execute("DELETE FROM community_reports WHERE account_id = ?", (account["id"],))
            database.execute("DELETE FROM community_posts WHERE account_id = ?", (account["id"],))
            database.execute("DELETE FROM fcm_device_registrations WHERE account_id = ?", (account["id"],))
            database.execute("DELETE FROM notification_preferences WHERE account_id = ?", (account["id"],))
            database.execute("DELETE FROM external_action_proposals WHERE account_id = ?", (account["id"],))
            database.execute("DELETE FROM supabase_sync_outbox WHERE account_id = ?", (account["id"],))
            queue_supabase_event(database, account["id"], "deletion", {"requested_at": now()})
            withdrawn_at = now()
            database.execute("INSERT INTO consent_events(id, account_id, scope, granted, policy_version, created_at) VALUES (?, ?, 'cloud_trial_summaries', 0, ?, ?)", (str(uuid.uuid4()), account["id"], POLICY_VERSION, withdrawn_at))
            audit(database, account["id"], "cloud_data_deleted")
            self.json_response({"deleted": True})

    def register(self, payload: dict[str, Any]) -> None:
        email = str(payload.get("email", "")).strip().lower()
        display_name = str(payload.get("displayName", "")).strip()
        password = str(payload.get("password", ""))
        if "@" not in email or len(email) > 254:
            raise ValueError("Enter a valid student email.")
        if not 1 <= len(display_name) <= 80:
            raise ValueError("Display name must be 1–80 characters.")
        if len(password) < 12:
            raise ValueError("Password must contain at least 12 characters.")
        if supabase_auth_enabled():
            result = supabase_auth("/auth/v1/signup", {"email": email, "password": password, "data": {"display_name": display_name}})
            remote_user = result.get("user") or {}
            remote_id = str(remote_user.get("id") or "")
            if not remote_id:
                raise ValueError("Supabase did not return a new account identifier.")
            account_id = str(uuid.uuid4())
            with connect() as database:
                database.execute(
                    "INSERT INTO accounts(id, email, display_name, password_hash, supabase_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (account_id, email, display_name, password_hash(secrets.token_urlsafe(32)), remote_id, now()),
                )
                audit(database, account_id, "supabase_account_registered")
            self.json_response({"account": {"id": account_id, "email": email, "displayName": display_name}, "requiresEmailConfirmation": not bool(result.get("access_token"))}, HTTPStatus.CREATED)
            return
        account_id = str(uuid.uuid4())
        with connect() as database:
            database.execute("INSERT INTO accounts(id, email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)", (account_id, email, display_name, password_hash(password), now()))
            audit(database, account_id, "account_created")
        self.json_response({"account": {"id": account_id, "email": email, "displayName": display_name}}, HTTPStatus.CREATED)

    def login(self, payload: dict[str, Any]) -> None:
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if supabase_auth_enabled():
            # Preserve access to an existing local account long enough for the
            # student to complete the explicit one-way migration. Once linked,
            # this fallback is no longer available for that account.
            with connect() as database:
                pending_account = database.execute("SELECT * FROM accounts WHERE email = ? AND supabase_user_id IS NULL AND disabled_at IS NULL", (email,)).fetchone()
                if pending_account and password_matches(password, pending_account["password_hash"]):
                    token, expires = create_local_session(database, pending_account["id"])
                    audit(database, pending_account["id"], "local_login_pending_supabase_migration")
                    self.json_response({"token": token, "expiresAt": expires, "account": self.public_account(pending_account), "cloudTrialSummaries": current_consent(database, pending_account["id"]), "supabaseMigrationRequired": True})
                    return
            result = supabase_auth("/auth/v1/token?grant_type=password", {"email": email, "password": password})
            remote_user = result.get("user") or {}
            remote_id = str(remote_user.get("id") or "")
            remote_email = str(remote_user.get("email") or email).strip().lower()
            if not remote_id or not remote_email:
                self.json_response({"error": "Supabase did not return a usable student account."}, HTTPStatus.BAD_GATEWAY)
                return
            display_name = str((remote_user.get("user_metadata") or {}).get("display_name") or remote_email.split("@", 1)[0])[:80]
            with connect() as database:
                account = database.execute("SELECT * FROM accounts WHERE supabase_user_id = ? OR email = ?", (remote_id, remote_email)).fetchone()
                if not account:
                    account_id = str(uuid.uuid4())
                    database.execute(
                        "INSERT INTO accounts(id, email, display_name, password_hash, supabase_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (account_id, remote_email, display_name, password_hash(secrets.token_urlsafe(32)), remote_id, now()),
                    )
                    account = database.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
                    audit(database, account_id, "supabase_account_linked_at_login")
                elif account["supabase_user_id"] != remote_id:
                    database.execute("UPDATE accounts SET supabase_user_id = ?, display_name = ? WHERE id = ?", (remote_id, display_name, account["id"]))
                    account = database.execute("SELECT * FROM accounts WHERE id = ?", (account["id"],)).fetchone()
                token, expires = create_local_session(database, account["id"])
                audit(database, account["id"], "supabase_login_succeeded")
                self.json_response({"token": token, "expiresAt": expires, "account": self.public_account(account), "cloudTrialSummaries": current_consent(database, account["id"])})
            return
        with connect() as database:
            account = database.execute("SELECT * FROM accounts WHERE email = ? AND disabled_at IS NULL", (email,)).fetchone()
            if not account or not password_matches(password, account["password_hash"]):
                audit(database, account["id"] if account else None, "login_failed")
                self.json_response({"error": "Email or password is incorrect."}, HTTPStatus.UNAUTHORIZED)
                return
            token, expires = create_local_session(database, account["id"])
            audit(database, account["id"], "login_succeeded")
            self.json_response({"token": token, "expiresAt": expires, "account": self.public_account(account), "cloudTrialSummaries": current_consent(database, account["id"])})

    def migrate_account_to_supabase(self, payload: dict[str, Any]) -> None:
        """One-way, student-initiated migration; passwords are never copied."""
        if not supabase_auth_enabled():
            self.json_response({"error": "Supabase Auth migration is disabled until the reviewed adapter is enabled."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        current_password = str(payload.get("currentPassword", ""))
        new_password = str(payload.get("newPassword", ""))
        if len(new_password) < 12:
            raise ValueError("Choose a new Supabase password with at least 12 characters.")
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            if account["supabase_user_id"]:
                self.json_response({"migrated": True, "requiresEmailConfirmation": False})
                return
            if not password_matches(current_password, account["password_hash"]):
                self.json_response({"error": "Current password is incorrect."}, HTTPStatus.UNAUTHORIZED)
                return
            result = supabase_auth("/auth/v1/signup", {"email": account["email"], "password": new_password, "data": {"display_name": account["display_name"]}})
            remote_id = str((result.get("user") or {}).get("id") or "")
            if not remote_id:
                self.json_response({"error": "Supabase did not return a new account identifier."}, HTTPStatus.BAD_GATEWAY)
                return
            database.execute("UPDATE accounts SET supabase_user_id = ? WHERE id = ?", (remote_id, account["id"]))
            audit(database, account["id"], "supabase_account_migration_started")
        self.json_response({"migrated": True, "requiresEmailConfirmation": not bool(result.get("access_token"))})

    def logout(self) -> None:
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if token:
            with connect() as database:
                database.execute("UPDATE account_sessions SET revoked_at = ? WHERE token_hash = ?", (now(), token_hash(token)))
        self.json_response({"loggedOut": True})

    def set_consent(self, payload: dict[str, Any]) -> None:
        granted = payload.get("granted")
        if not isinstance(granted, bool):
            raise ValueError("Consent choice is required.")
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            created_at = now()
            database.execute("INSERT INTO consent_events(id, account_id, scope, granted, policy_version, created_at) VALUES (?, ?, 'cloud_trial_summaries', ?, ?, ?)", (str(uuid.uuid4()), account["id"], int(granted), POLICY_VERSION, created_at))
            queue_supabase_event(database, account["id"], "consent", {"granted": granted, "policy_version": POLICY_VERSION, "created_at": created_at})
            audit(database, account["id"], "cloud_trial_consent_changed", {"granted": granted})
        self.json_response({"cloudTrialSummaries": granted})

    @staticmethod
    def valid_quiet_time(value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
            raise ValueError("Quiet hours must use the HH:MM format.")
        hour, minute = value[:2], value[3:]
        if not hour.isdigit() or not minute.isdigit() or not 0 <= int(hour) <= 23 or not 0 <= int(minute) <= 59:
            raise ValueError("Quiet hours must be a valid time.")
        return value

    def set_notification_preference(self, payload: dict[str, Any]) -> None:
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("A notification preference is required.")
        quiet_start = self.valid_quiet_time(payload.get("quietStart"))
        quiet_end = self.valid_quiet_time(payload.get("quietEnd"))
        timezone_offset = payload.get("timezoneOffsetMinutes")
        if timezone_offset is not None and (not isinstance(timezone_offset, int) or not -840 <= timezone_offset <= 840):
            raise ValueError("The notification time-zone offset is invalid.")
        if enabled and not fcm_registration_ready():
            self.json_response({"error": "Secure device notifications are not ready on this server yet."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            database.execute(
                "INSERT INTO notification_preferences(account_id, fcm_enabled, quiet_start, quiet_end, timezone_offset_minutes, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(account_id) DO UPDATE SET fcm_enabled = excluded.fcm_enabled, quiet_start = excluded.quiet_start, quiet_end = excluded.quiet_end, timezone_offset_minutes = excluded.timezone_offset_minutes, updated_at = excluded.updated_at",
                (account["id"], int(enabled), quiet_start, quiet_end, timezone_offset, now()),
            )
            if not enabled:
                database.execute("DELETE FROM fcm_device_registrations WHERE account_id = ?", (account["id"],))
            queue_supabase_event(database, account["id"], "notification_preference", {"enabled": enabled, "quiet_start": quiet_start, "quiet_end": quiet_end, "updated_at": now()})
            audit(database, account["id"], "fcm_notification_preference_changed", {"enabled": enabled, "quietHoursSet": bool(quiet_start and quiet_end)})
        self.json_response({"enabled": enabled, "quietStart": quiet_start, "quietEnd": quiet_end})

    def register_fcm_device(self, payload: dict[str, Any]) -> None:
        # Firebase's web SDK returns a registration token. Older development
        # builds used installationId, so accept it only as a backwards-safe alias.
        installation_id = str(payload.get("registrationToken", payload.get("installationId", ""))).strip()
        consent = payload.get("pushConsent")
        if not isinstance(consent, bool) or not consent:
            raise ValueError("Explicit device-notification consent is required.")
        if not 1 <= len(installation_id) <= 4096:
            raise ValueError("The device registration identifier is invalid.")
        cipher = device_cipher()
        if not fcm_web_configured() or cipher is None:
            self.json_response({"error": "Secure device notifications are not ready on this server yet."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        installation_hash = hashlib.sha256(installation_id.encode("utf-8")).hexdigest()
        encrypted_id = cipher.encrypt(installation_id.encode("utf-8")).decode("utf-8")
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            database.execute(
                "INSERT INTO fcm_device_registrations(id, account_id, installation_id_hash, encrypted_installation_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(installation_id_hash) DO UPDATE SET account_id = excluded.account_id, encrypted_installation_id = excluded.encrypted_installation_id, updated_at = excluded.updated_at",
                (str(uuid.uuid4()), account["id"], installation_hash, encrypted_id, now(), now()),
            )
            database.execute(
                "INSERT INTO notification_preferences(account_id, fcm_enabled, updated_at) VALUES (?, 1, ?) "
                "ON CONFLICT(account_id) DO UPDATE SET fcm_enabled = 1, updated_at = excluded.updated_at",
                (account["id"], now()),
            )
            queue_supabase_event(database, account["id"], "fcm_registration", {
                "installation_id_hash": installation_hash,
                "encrypted_installation_id": encrypted_id,
                "created_at": now(),
                "updated_at": now(),
            })
            audit(database, account["id"], "fcm_device_registered", {"registration": "encrypted"})
        self.json_response({"registered": True}, HTTPStatus.CREATED)

    def sync_supabase(self, payload: dict[str, Any]) -> None:
        """An explicit, per-account manual sync—not an automatic background copy."""
        aggregate_sync = payload.get("confirmAggregateSync") is True
        deletion_sync = payload.get("confirmDeletionSync") is True
        if not aggregate_sync and not deletion_sync:
            raise ValueError("Confirm either your aggregate-data sync or synced-data deletion.")
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            if aggregate_sync and not current_consent(database, account["id"]):
                self.json_response({"error": "Enable aggregate-storage consent before syncing."}, HTTPStatus.FORBIDDEN)
                return
            outcome = sync_account_outbox(database, account, deletions_only=deletion_sync and not aggregate_sync)
            audit(database, account["id"], "supabase_manual_sync", outcome)
        self.json_response({"synced": outcome})

    @staticmethod
    def action_adapter_ready(action: str) -> bool:
        return {
            "notification": fcm_sender_ready(),
            "counsellor_referral": os.environ.get("EQUILIBRIUM_COUNSELLOR_REFERRAL_ENABLED") == "1" and bool(os.environ.get("EQUILIBRIUM_COUNSELLOR_WEBHOOK_URL")),
            "summary_share": os.environ.get("EQUILIBRIUM_SUMMARY_SHARE_ENABLED") == "1" and bool(os.environ.get("EQUILIBRIUM_SUMMARY_WEBHOOK_URL")),
        }.get(action, False)

    def create_action_proposal(self, payload: dict[str, Any]) -> None:
        if not langgraph_actions_ready():
            self.json_response({"error": "Approval-gated actions are disabled until LangGraph is explicitly enabled."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        action = str(payload.get("action", ""))
        destination = str(payload.get("destination", "")).strip()
        if action not in EXTERNAL_ACTIONS:
            raise ValueError("Choose a supported external action.")
        clean_payload: dict[str, Any]
        if action == "notification":
            body = str(payload.get("body", "")).strip()
            scheduled_for = str(payload.get("scheduledFor", "")).strip()
            if destination != "registered_devices" or not 1 <= len(body) <= 180:
                raise ValueError("A notification needs a registered-device destination and a short message.")
            try:
                scheduled = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
                if scheduled.tzinfo is None:
                    raise ValueError
                scheduled = scheduled.astimezone(timezone.utc)
            except ValueError:
                raise ValueError("Provide a scheduled UTC date/time for the notification.") from None
            if scheduled < datetime.now(timezone.utc) or scheduled > datetime.now(timezone.utc) + timedelta(days=30):
                raise ValueError("Schedule the notification between now and 30 days from now.")
            clean_payload = {"body": body, "scheduledFor": scheduled.isoformat(timespec="seconds")}
        elif action == "counsellor_referral":
            message = str(payload.get("message", "")).strip()
            if destination not in {"nus", "ntu", "smu"} or not 1 <= len(message) <= 1000:
                raise ValueError("Choose a supported campus and write a short message you want to send.")
            clean_payload = {"message": message}
        else:
            summary = str(payload.get("summary", "")).strip()
            if not 1 <= len(destination) <= 100 or not 1 <= len(summary) <= 1200:
                raise ValueError("A summary share needs a recipient label and a short summary you choose.")
            clean_payload = {"summary": summary}
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            proposal_id = str(uuid.uuid4())
            database.execute(
                "INSERT INTO external_action_proposals(id, account_id, action, destination, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (proposal_id, account["id"], action, destination, json.dumps(clean_payload), now()),
            )
            audit(database, account["id"], "external_action_proposed", {"proposalId": proposal_id, "action": action, "destination": destination})
        self.json_response({"proposal": {"id": proposal_id, "action": action, "destination": destination, "status": "pending_approval"}}, HTTPStatus.CREATED)

    def decide_action_proposal(self, payload: dict[str, Any]) -> None:
        proposal_id = self.path.removeprefix("/api/actions/").removesuffix("/decision")
        decision = payload.get("decision")
        if decision not in {"approve", "reject"}:
            raise ValueError("Choose approve or reject for this exact action.")
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            proposal = database.execute("SELECT * FROM external_action_proposals WHERE id = ? AND account_id = ?", (proposal_id, account["id"])).fetchone()
            if not proposal:
                self.json_response({"error": "That approval request is unavailable."}, HTTPStatus.NOT_FOUND)
                return
            if proposal["status"] != "pending_approval":
                self.json_response({"error": "That action has already been decided."}, HTTPStatus.CONFLICT)
                return
            if decision == "reject":
                database.execute("UPDATE external_action_proposals SET status = 'rejected', decided_at = ? WHERE id = ?", (now(), proposal_id))
                audit(database, account["id"], "external_action_rejected", {"proposalId": proposal_id})
                self.json_response({"status": "rejected"})
                return
            if not self.action_adapter_ready(proposal["action"]):
                self.json_response({"error": "This approved action's connector is not enabled yet. Nothing was sent."}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            try:
                from langgraph.types import Command
                from agent_workflow import build_support_approval_graph
                graph = build_support_approval_graph()
                graph.invoke({"action": proposal["action"], "destination": proposal["destination"], "student_approved": False, "result": ""}, config={"configurable": {"thread_id": proposal_id}})
                gate_result = graph.invoke(Command(resume="approve"), config={"configurable": {"thread_id": proposal_id}})
            except (ImportError, RuntimeError) as error:
                self.json_response({"error": f"Approval gate is unavailable: {error}"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if not gate_result.get("student_approved"):
                self.json_response({"error": "The approval gate did not approve the action. Nothing was sent."}, HTTPStatus.CONFLICT)
                return
            action_payload = json.loads(proposal["payload_json"])
            try:
                if proposal["action"] == "notification":
                    registrations = database.execute(
                        "SELECT r.installation_id_hash FROM fcm_device_registrations r JOIN notification_preferences p ON p.account_id = r.account_id WHERE r.account_id = ? AND p.fcm_enabled = 1",
                        (account["id"],),
                    ).fetchall()
                    if not registrations:
                        raise RuntimeError("No opted-in device is registered for this account.")
                    for registration in registrations:
                        database.execute(
                            "INSERT INTO notification_send_ledger(id, account_id, registration_id_hash, request_id, title, body, scheduled_for, created_at) VALUES (?, ?, ?, ?, 'Equilibrium', ?, ?, ?)",
                            (str(uuid.uuid4()), account["id"], registration["installation_id_hash"], f"{proposal_id}:{registration['installation_id_hash']}", action_payload["body"], action_payload["scheduledFor"], now()),
                        )
                    result = {"queued": len(registrations), "scheduledFor": action_payload["scheduledFor"]}
                elif proposal["action"] == "counsellor_referral":
                    post_approved_webhook(os.environ["EQUILIBRIUM_COUNSELLOR_WEBHOOK_URL"], {"kind": "student_requested_counsellor_referral", "campus": proposal["destination"], "message": action_payload["message"]})
                    result = {"sent": True, "destination": proposal["destination"]}
                else:
                    post_approved_webhook(os.environ["EQUILIBRIUM_SUMMARY_WEBHOOK_URL"], {"kind": "student_requested_summary_share", "recipient": proposal["destination"], "summary": action_payload["summary"]})
                    result = {"sent": True, "destination": proposal["destination"]}
            except RuntimeError as error:
                database.execute("UPDATE external_action_proposals SET status = 'failed', decided_at = ?, result_json = ? WHERE id = ?", (now(), json.dumps({"error": str(error)[:160]}), proposal_id))
                audit(database, account["id"], "external_action_failed", {"proposalId": proposal_id, "action": proposal["action"]})
                self.json_response({"error": "The approved action could not be completed. Nothing else was sent."}, HTTPStatus.BAD_GATEWAY)
                return
            database.execute("UPDATE external_action_proposals SET status = 'completed', decided_at = ?, completed_at = ?, result_json = ? WHERE id = ?", (now(), now(), json.dumps(result), proposal_id))
            audit(database, account["id"], "external_action_completed", {"proposalId": proposal_id, "action": proposal["action"]})
        self.json_response({"status": "completed", "result": result})

    def process_due_notifications(self, payload: dict[str, Any]) -> None:
        """Job-runner endpoint; it is disabled unless a secret and FCM sender are set."""
        job_secret = os.environ.get("EQUILIBRIUM_JOB_SECRET", "")
        supplied_secret = self.headers.get("X-Equilibrium-Job-Key", "")
        if not job_secret or not hmac.compare_digest(job_secret, supplied_secret):
            self.json_response({"error": "Job authentication required."}, HTTPStatus.UNAUTHORIZED)
            return
        if not fcm_sender_ready():
            self.json_response({"error": "FCM scheduled delivery is not enabled."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        processed = {"sent": 0, "quietHours": 0, "failed": 0, "cancelled": 0}
        with connect() as database:
            due = database.execute(
                "SELECT l.*, r.encrypted_installation_id, p.fcm_enabled, p.quiet_start, p.quiet_end, p.timezone_offset_minutes FROM notification_send_ledger l JOIN fcm_device_registrations r ON r.installation_id_hash = l.registration_id_hash LEFT JOIN notification_preferences p ON p.account_id = l.account_id WHERE l.status = 'pending' AND l.scheduled_for <= ? ORDER BY l.scheduled_for LIMIT 100",
                (now(),),
            ).fetchall()
            cipher = device_cipher()
            for item in due:
                if not item["fcm_enabled"]:
                    database.execute("UPDATE notification_send_ledger SET status = 'cancelled', attempted_at = ? WHERE id = ?", (now(), item["id"]))
                    processed["cancelled"] += 1
                    continue
                if in_quiet_hours(datetime.now(timezone.utc), item["quiet_start"], item["quiet_end"], item["timezone_offset_minutes"]):
                    database.execute("UPDATE notification_send_ledger SET status = 'skipped_quiet_hours', attempted_at = ? WHERE id = ?", (now(), item["id"]))
                    processed["quietHours"] += 1
                    continue
                try:
                    token = cipher.decrypt(item["encrypted_installation_id"].encode("utf-8")).decode("utf-8") if cipher else ""
                    message_id = fcm_send(token, item["title"], item["body"])
                except Exception:
                    database.execute("UPDATE notification_send_ledger SET status = 'failed', attempted_at = ?, error_code = 'delivery_failed' WHERE id = ?", (now(), item["id"]))
                    processed["failed"] += 1
                else:
                    database.execute("UPDATE notification_send_ledger SET status = 'sent', attempted_at = ?, provider_message_id = ? WHERE id = ?", (now(), message_id[:255], item["id"]))
                    processed["sent"] += 1
        self.json_response({"processed": processed})

    def create_trial(self, payload: dict[str, Any]) -> None:
        allowed = {"timingEvents", "medianMs", "variability", "corrections", "longPauses", "clientCreatedAt"}
        if not set(payload).issubset(allowed) or not {"timingEvents", "medianMs", "variability", "corrections", "longPauses"}.issubset(payload):
            raise ValueError("Only aggregate cadence fields can be stored.")
        values = [payload[key] for key in ("timingEvents", "medianMs", "variability", "corrections", "longPauses")]
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("Cadence aggregates must be non-negative integers.")
        if values[0] > 180 or values[1] > 4000 or values[2] > 500 or values[3] > 180 or values[4] > 180:
            raise ValueError("Cadence summary is outside the allowed range.")
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            if not current_consent(database, account["id"]):
                self.json_response({"error": "Enable cloud trial-summary storage before saving data."}, HTTPStatus.FORBIDDEN)
                return
            trial_id = str(uuid.uuid4())
            database.execute(
                "INSERT INTO cadence_trials(id, account_id, timing_events, median_ms, variability_pct, correction_count, long_pause_count, client_created_at, stored_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (trial_id, account["id"], *values, str(payload.get("clientCreatedAt") or now()), now()),
            )
            queue_supabase_event(database, account["id"], "trial", {
                "id": trial_id,
                "timing_events": values[0],
                "median_ms": values[1],
                "variability_pct": values[2],
                "correction_count": values[3],
                "long_pause_count": values[4],
                "client_created_at": str(payload.get("clientCreatedAt") or now()),
                "created_at": now(),
            })
            audit(database, account["id"], "cloud_trial_saved", {"trialId": trial_id})
        self.json_response({"trialId": trial_id}, HTTPStatus.CREATED)

    def create_checkin(self, payload: dict[str, Any]) -> None:
        label = payload.get("label")
        trial_id = payload.get("trialId")
        if label not in {"steady", "stretched", "depleted"} or (trial_id is not None and not isinstance(trial_id, str)):
            raise ValueError("Check-in label or trial reference is invalid.")
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            if not current_consent(database, account["id"]):
                self.json_response({"error": "Enable cloud trial-summary storage before saving data."}, HTTPStatus.FORBIDDEN)
                return
            if trial_id and not database.execute("SELECT 1 FROM cadence_trials WHERE id = ? AND account_id = ?", (trial_id, account["id"])).fetchone():
                raise ValueError("Trial does not belong to this account.")
            checkin_id = str(uuid.uuid4())
            database.execute("INSERT INTO cadence_checkins(id, account_id, trial_id, label, created_at) VALUES (?, ?, ?, ?, ?)", (checkin_id, account["id"], trial_id, label, now()))
            audit(database, account["id"], "cloud_checkin_saved", {"checkinId": checkin_id})
        self.json_response({"checkinId": checkin_id}, HTTPStatus.CREATED)

    def list_community_posts(self) -> None:
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            posts = [dict(row) for row in database.execute(
                "SELECT id, topic, body, created_at FROM community_posts WHERE status = 'published' ORDER BY created_at DESC LIMIT 60"
            )]
        self.json_response({"posts": posts})

    def create_community_post(self, payload: dict[str, Any]) -> None:
        topic = payload.get("topic")
        body = str(payload.get("body", "")).strip()
        if topic not in {"deadlines", "sleep", "meals", "boundaries", "asking_for_help"}:
            raise ValueError("Choose a community topic.")
        if not 1 <= len(body) <= 500:
            raise ValueError("A community note must be between 1 and 500 characters.")
        lowered = body.lower()
        if "http://" in lowered or "https://" in lowered or "@" in body or any(char.isdigit() for char in body) and sum(char.isdigit() for char in body) >= 8:
            raise ValueError("Remove links, contact details and other identifying information before posting.")
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            post_id = str(uuid.uuid4())
            database.execute(
                "INSERT INTO community_posts(id, account_id, topic, body, status, created_at) VALUES (?, ?, ?, ?, 'published', ?)",
                (post_id, account["id"], topic, body, now()),
            )
            audit(database, account["id"], "community_post_created", {"postId": post_id, "topic": topic})
        self.json_response({"postId": post_id, "published": True}, HTTPStatus.CREATED)

    def report_community_post(self, payload: dict[str, Any]) -> None:
        post_id = self.path.removeprefix("/api/community/posts/").removesuffix("/report")
        reason = payload.get("reason")
        if reason not in {"personal_information", "unsafe", "abuse", "other"}:
            raise ValueError("Choose a report reason.")
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            post = database.execute("SELECT id FROM community_posts WHERE id = ? AND status = 'published'", (post_id,)).fetchone()
            if not post:
                raise ValueError("That post is no longer available.")
            database.execute("INSERT INTO community_reports(id, post_id, account_id, reason, created_at) VALUES (?, ?, ?, ?, ?)", (str(uuid.uuid4()), post_id, account["id"], reason, now()))
            database.execute("UPDATE community_posts SET report_count = report_count + 1 WHERE id = ?", (post_id,))
            database.execute("UPDATE community_posts SET status = 'pending' WHERE id = ? AND report_count >= 3", (post_id,))
            audit(database, account["id"], "community_post_reported", {"postId": post_id, "reason": reason})
        self.json_response({"reported": True})

    def create_reflection(self, payload: dict[str, Any]) -> None:
        text = str(payload.get("text", "")).strip()
        lens = payload.get("lens")
        consent = payload.get("shareWithAssistant")
        if lens not in {"next_step", "boundary", "perspective"} or not isinstance(consent, bool) or not consent:
            raise ValueError("Choose a reflection lens and explicitly consent before sending writing to the assistant.")
        if not 1 <= len(text) <= 1200:
            raise ValueError("A reflection must be between 1 and 1,200 characters.")
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            audit(database, account["id"], "reflection_requested", {"lens": lens, "length": len(text)})
        provider, api_key, model = reflection_provider_details()
        if not reflection_provider_configured():
            missing = {
                "openai": "OPENAI_API_KEY",
                "gemini": "GEMINI_API_KEY and GEMINI_REFLECTION_MODEL",
                "mistral": "MISTRAL_API_KEY and MISTRAL_REFLECTION_MODEL",
            }.get(provider, "a supported EQUILIBRIUM_REFLECTION_PROVIDER")
            self.json_response({"error": f"The reflection assistant is not configured. Set {missing} on the server, then restart it."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        lenses = {
            "next_step": "identify one compassionate, concrete next step that takes under ten minutes",
            "boundary": "suggest one respectful boundary or request the student could make",
            "perspective": "offer a grounded perspective that separates the student from the pressure they are carrying",
        }
        instructions = (
            "You are Equilibrium's private student reflection assistant. Be warm, concise, non-judgmental and practical. "
            "Do not diagnose, claim certainty, assess stress from behaviour, or give clinical advice. Do not mention policy. "
            "Return three short sections titled: What I hear, A useful next move, and A sentence you could use. "
            "If the student mentions immediate danger, self-harm, suicide, or inability to stay safe, lead with an urgent instruction "
            "to call Singapore emergency services (995/999) or SOS 1767, and do not attempt to manage the crisis. "
            f"For this response, {lenses[lens]}."
        )
        request = reflection_request(provider, api_key or "", model or "", instructions, text)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            # Safe diagnostic only: never print the key, request body, or student writing.
            try:
                error_type = json.loads(error.read().decode("utf-8")).get("error", {}).get("code") or "unknown_error"
            except (ValueError, json.JSONDecodeError):
                error_type = "unknown_error"
            print(f"{provider.title()} reflection request failed: HTTP {error.code} ({error_type})")
            self.json_response({"error": "The reflection assistant is unavailable right now. Your writing was not saved by Equilibrium."}, HTTPStatus.BAD_GATEWAY)
            return
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"{provider.title()} reflection request failed: network error ({getattr(error, 'reason', 'timeout')})")
            self.json_response({"error": "The reflection assistant is unavailable right now. Your writing was not saved by Equilibrium."}, HTTPStatus.BAD_GATEWAY)
            return
        answer = reflection_text(provider, result)
        if not answer:
            self.json_response({"error": "The reflection assistant returned no usable response. Your writing was not saved by Equilibrium."}, HTTPStatus.BAD_GATEWAY)
            return
        self.json_response({"reflection": answer})


if __name__ == "__main__":
    initialise_database()
    ensure_demo_account()
    os.chdir(ROOT)
    host = os.environ.get("EQUILIBRIUM_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Equilibrium API: http://{host}:{port}")
    ThreadingHTTPServer((host, port), EquilibriumHandler).serve_forever()
