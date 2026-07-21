# Optional production integrations

The base Equilibrium prototype remains local-first. These integrations are
disabled unless their server environment variables are deliberately supplied.
No browser code receives an API key, service-role key, or provider secret.

## Reflection provider selection

OpenAI remains the default and preserves the current behaviour:

```sh
OPENAI_API_KEY="..." OPENAI_REFLECTION_MODEL="gpt-5.4-mini" python3 server.py
```

To use exactly one alternative provider, select it explicitly before starting
the server. The reflection remains opt-in and neither its text nor response is
stored by Equilibrium.

```sh
# Gemini: choose a currently supported text model in your Google project.
EQUILIBRIUM_REFLECTION_PROVIDER="gemini" \
GEMINI_API_KEY="..." GEMINI_REFLECTION_MODEL="your-model-id" python3 server.py

# Mistral: choose a currently supported chat model in your Mistral project.
EQUILIBRIUM_REFLECTION_PROVIDER="mistral" \
MISTRAL_API_KEY="..." MISTRAL_REFLECTION_MODEL="your-model-id" python3 server.py
```

The active provider is visible as a name and readiness boolean at
`/api/health`; credentials are never returned. Do not configure more than one
provider for normal student use: a single provider is easier to explain in the
consent notice and data-processing record.

## Firebase Cloud Messaging (FCM)

FCM should be enabled only after the app is deployed on HTTPS with a service
worker, a student-facing notification preference, quiet hours, and a clear
unsubscribe control. It is not meaningful on `http://127.0.0.1`.

Set these server environment variables only after configuring the Firebase web
app. Their presence is reported as a readiness boolean, but no tokens or
notifications are collected or sent by this prototype yet:

```sh
FIREBASE_PROJECT_ID="..."
FIREBASE_WEB_API_KEY="..."
FIREBASE_MESSAGING_SENDER_ID="..."
FIREBASE_APP_ID="..."
FIREBASE_VAPID_KEY="..."
```

Install the optional encryption dependency, then generate a server-only Fernet
key. Do not put this key in the Firebase console, JavaScript, or a `.env` file
that is committed to source control.

```sh
python3 -m pip install -r requirements-integrations.txt
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set the printed value as `EQUILIBRIUM_DEVICE_ENCRYPTION_KEY` in the server
environment. Once all Firebase values and this key are present, the signed-in
student can explicitly enable background reminders, choose quiet hours, and
register their Firebase Installation ID. Equilibrium stores only an encrypted
copy plus a non-reversible hash for uniqueness; disabling reminders or deleting
the account removes the registration.

The service worker and registration path are implemented. Sending scheduled
FCM messages still requires a Firebase service-account/OAuth deployment and a
reviewed job runner; it is deliberately not included in this local prototype.
The existing in-browser scheduled nudge remains available as the safe fallback.

## Shared Supabase database

`supabase/migrations/20260720_equilibrium.sql` is an isolated Postgres schema
with Row Level Security. It stores only account-linked aggregate trials,
consent, notification preferences, and anonymised community data. It does not
store reflection text or raw behavioural events.

Apply it to a separate Supabase project after a data-protection review. Keep a
`SUPABASE_SERVICE_ROLE_KEY` on the server only; never add it to JavaScript. The
current SQLite path remains active until an explicit, reviewed sync/migration
adapter is implemented. Merely setting these variables never copies data:

```sh
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="..."
EQUILIBRIUM_SUPABASE_SYNC="0"
```

## LangGraph approval gate

`agent_workflow.py` provides a human-in-the-loop boundary for future external
actions. It pauses for the student's approve/reject decision and never makes a
provider call itself. This avoids autonomous notifications, referrals, or
disclosures. Install it only when you are ready to integrate a reviewed action
adapter:

```sh
python3 -m pip install langgraph
```

If a hosted LangGraph deployment is later used, configure its URL and key only
on the server. The status endpoint reports readiness without revealing either:

```sh
LANGGRAPH_API_URL="https://..."
LANGGRAPH_API_KEY="..."
```

## Safety boundary

No integration may receive raw typing text/events, scrolling histories,
identity/academic records, or a reflection without the student choosing the
specific action. Do not use agent tools to diagnose stress, contact a
counsellor, or notify a device autonomously.
