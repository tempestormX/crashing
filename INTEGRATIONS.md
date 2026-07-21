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
app. Their presence is reported as a readiness boolean; no registration token
is collected until a signed-in student explicitly enables reminders:

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
register their Firebase token. Equilibrium stores only an encrypted copy plus a
non-reversible hash for uniqueness; disabling reminders or deleting the account
removes the registration.

The service worker registers a Firebase **registration token** (not an
installation ID) only after the student turns reminders on. It stores an
encrypted token plus a non-reversible hash. The token is deleted locally when
the student turns reminders off or deletes their data.

### Conditional FCM delivery

The sender, delivery ledger and job route are implemented but disabled by
default. This lets the project be code-ready without contacting Firebase.
Before enabling it, review the reminder copy, retention policy, rate limits and
the job-runner access control. Then install the optional package and set these
server-only values in the deployment secret store:

```sh
python3 -m pip install -r requirements-integrations.txt
FIREBASE_SERVICE_ACCOUNT_FILE="/secure/path/firebase-service-account.json"
EQUILIBRIUM_FCM_SENDER_ENABLED="1"
EQUILIBRIUM_JOB_SECRET="a-long-random-secret"
```

`POST /api/integrations/fcm/process-due` requires the
`X-Equilibrium-Job-Key` header and processes only approved, due rows in
`notification_send_ledger`. It honours the student’s enabled setting and quiet
hours, records `sent`, `failed`, `cancelled`, or `skipped_quiet_hours`, and
never creates a message from a stress score. Connect Cloud Scheduler only after
the endpoint has been tested in a non-production Firebase project.

## Shared Supabase database

`supabase/migrations/20260720_equilibrium.sql` is an isolated Postgres schema
with Row Level Security. It stores only account-linked aggregate trials,
consent, notification preferences, and anonymised community data. It does not
store reflection text or raw behavioural events.

Apply it to a separate Supabase project after a data-protection review. Keep a
`SUPABASE_SERVICE_ROLE_KEY` on the server only; never add it to JavaScript.
The current SQLite path remains active by default. The adapters below are
deliberately disabled until their separate flags are set:

```sh
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_ANON_KEY="..."
SUPABASE_SERVICE_ROLE_KEY="..."
EQUILIBRIUM_SUPABASE_SYNC="0"
EQUILIBRIUM_SUPABASE_AUTH="0"
```

### Conditional Supabase Auth

Set `EQUILIBRIUM_SUPABASE_AUTH="1"` only after configuring Supabase Auth’s
redirect URLs, email templates and password policy. New sign-ups and sign-ins
then authenticate through Supabase; Equilibrium still issues its own short-lived
application session and stores only the Supabase user UUID locally.

Existing SQLite password hashes cannot and must not be copied to Supabase. A
signed-in student can instead call the user-initiated
`POST /api/auth/migrate-to-supabase` route with their current local password and
a newly chosen Supabase password. The password is verified/transmitted only for
that request and is never copied between stores. Email confirmation remains a
Supabase project policy.

### Conditional Supabase sync

With `EQUILIBRIUM_SUPABASE_SYNC="1"`, the server writes only a manually flushed
outbox of consent events, aggregate cadence summaries, notification preferences
and encrypted device registrations. Nothing is synced just because a key is
present. A linked Supabase user plus aggregate-storage consent are required,
then the student must call `POST /api/integrations/supabase/sync` with
`{"confirmAggregateSync": true}`. Reflection text, raw key/scroll events,
session tokens and local passwords are never eligible for the outbox.

When a student deletes their data, Equilibrium clears pending sync records and
queues a deletion-only request. If Supabase had previously been enabled, the
student can explicitly flush that request with
`{"confirmDeletionSync": true}`; it removes their synced aggregate trials,
notification preferences, device registrations and community records without
requiring them to re-consent to storage.

## LangGraph approval gate

`agent_workflow.py` provides the human-in-the-loop boundary used by the optional
external-action routes. It pauses for the student's approve/reject decision.
The server records a proposal first; approval is then required for the exact
action, destination and student-supplied content.

```sh
python3 -m pip install langgraph
EQUILIBRIUM_LANGGRAPH_ACTIONS="1"
```

The local gate needs no hosted LangGraph connection. If a hosted deployment is
later used, configure its URL and key only on the server. The status endpoint
reports readiness without revealing either:

```sh
LANGGRAPH_API_URL="https://..."
LANGGRAPH_API_KEY="..."
```

The three approved-action adapters are conditionally available:

- `notification` queues a chosen message for already opted-in devices; the FCM
  job is the only component that can deliver it.
- `counsellor_referral` posts only the student-written request and campus code
  to a reviewed HTTPS connector after `EQUILIBRIUM_COUNSELLOR_REFERRAL_ENABLED=1`
  and `EQUILIBRIUM_COUNSELLOR_WEBHOOK_URL` are set.
- `summary_share` posts only the student-written summary and recipient label to
  a reviewed HTTPS connector after `EQUILIBRIUM_SUMMARY_SHARE_ENABLED=1` and
  `EQUILIBRIUM_SUMMARY_WEBHOOK_URL` are set.

Do not set either webhook until the receiving service’s identity verification,
data-processing agreement, retention schedule and incident process are
approved. These routes cannot infer a referral or summary from behavioural data.

## Safety boundary

No integration may receive raw typing text/events, scrolling histories,
identity/academic records, or a reflection without the student choosing the
specific action. Do not use agent tools to diagnose stress, contact a
counsellor, or notify a device autonomously.
