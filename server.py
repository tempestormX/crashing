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
            "requiresHttps": True,
        },
        "sharedStorage": {
            "supabaseConfigured": all(os.environ.get(name) for name in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")),
            "syncEnabled": os.environ.get("EQUILIBRIUM_SUPABASE_SYNC") == "1",
        },
        "orchestration": {
            "langgraphConfigured": all(os.environ.get(name) for name in ("LANGGRAPH_API_URL", "LANGGRAPH_API_KEY")),
            "humanApprovalRequired": True,
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
            elif self.path == "/api/community/posts":
                self.create_community_post(payload)
            elif self.path.startswith("/api/community/posts/") and self.path.endswith("/report"):
                self.report_community_post(payload)
            else:
                self.json_response({"error": "Unknown API route."}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as error:
            self.json_response({"error": str(error)}, HTTPStatus.BAD_REQUEST)
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
                        "SELECT fcm_enabled, quiet_start, quiet_end, updated_at FROM notification_preferences WHERE account_id = ?",
                        (account["id"],),
                    ).fetchone()
                    self.json_response({"preference": dict(preference) if preference else {"fcm_enabled": 0, "quiet_start": None, "quiet_end": None}})
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
            database.execute("INSERT INTO consent_events(id, account_id, scope, granted, policy_version, created_at) VALUES (?, ?, 'cloud_trial_summaries', 0, ?, ?)", (str(uuid.uuid4()), account["id"], POLICY_VERSION, now()))
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
        account_id = str(uuid.uuid4())
        with connect() as database:
            database.execute("INSERT INTO accounts(id, email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)", (account_id, email, display_name, password_hash(password), now()))
            audit(database, account_id, "account_created")
        self.json_response({"account": {"id": account_id, "email": email, "displayName": display_name}}, HTTPStatus.CREATED)

    def login(self, payload: dict[str, Any]) -> None:
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        with connect() as database:
            account = database.execute("SELECT * FROM accounts WHERE email = ? AND disabled_at IS NULL", (email,)).fetchone()
            if not account or not password_matches(password, account["password_hash"]):
                audit(database, account["id"] if account else None, "login_failed")
                self.json_response({"error": "Email or password is incorrect."}, HTTPStatus.UNAUTHORIZED)
                return
            token = secrets.token_urlsafe(32)
            expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
            database.execute("INSERT INTO account_sessions(token_hash, account_id, created_at, expires_at) VALUES (?, ?, ?, ?)", (token_hash(token), account["id"], now(), expires))
            audit(database, account["id"], "login_succeeded")
            self.json_response({"token": token, "expiresAt": expires, "account": self.public_account(account), "cloudTrialSummaries": current_consent(database, account["id"])})

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
            database.execute("INSERT INTO consent_events(id, account_id, scope, granted, policy_version, created_at) VALUES (?, ?, 'cloud_trial_summaries', ?, ?, ?)", (str(uuid.uuid4()), account["id"], int(granted), POLICY_VERSION, now()))
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
        if enabled and not fcm_registration_ready():
            self.json_response({"error": "Secure device notifications are not ready on this server yet."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        with connect() as database:
            account = self.require_account(database)
            if not account:
                return
            database.execute(
                "INSERT INTO notification_preferences(account_id, fcm_enabled, quiet_start, quiet_end, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(account_id) DO UPDATE SET fcm_enabled = excluded.fcm_enabled, quiet_start = excluded.quiet_start, quiet_end = excluded.quiet_end, updated_at = excluded.updated_at",
                (account["id"], int(enabled), quiet_start, quiet_end, now()),
            )
            if not enabled:
                database.execute("DELETE FROM fcm_device_registrations WHERE account_id = ?", (account["id"],))
            audit(database, account["id"], "fcm_notification_preference_changed", {"enabled": enabled, "quietHoursSet": bool(quiet_start and quiet_end)})
        self.json_response({"enabled": enabled, "quietStart": quiet_start, "quietEnd": quiet_end})

    def register_fcm_device(self, payload: dict[str, Any]) -> None:
        installation_id = str(payload.get("installationId", "")).strip()
        consent = payload.get("pushConsent")
        if not isinstance(consent, bool) or not consent:
            raise ValueError("Explicit device-notification consent is required.")
        if not 1 <= len(installation_id) <= 512:
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
            audit(database, account["id"], "fcm_device_registered", {"registration": "encrypted"})
        self.json_response({"registered": True}, HTTPStatus.CREATED)

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
