# Equilibrium multi-account database

Start the local application and API together:

```sh
python3 server.py
```

Open `http://127.0.0.1:8000`. The server creates `database/equilibrium.db` and applies `database/schema.sql` safely on every start.

## What it stores

- account email, display name and a salted PBKDF2 password hash;
- short-lived, hashed session tokens;
- explicit cloud-storage consent events;
- aggregate cadence trials: count, median timing, variability, correction count and long-pause count;
- optional student-labelled check-ins.
- anonymous community notes, their topic, and safety reports (never a public profile or email address).
- opt-in background-reminder preferences and encrypted Firebase device registration IDs, only after secure FCM configuration.

It rejects text, raw key events, URLs, scrolling histories, screenshots and individual stress predictions. Data is isolated by account ID and the API requires a current `cloud_trial_summaries` consent before a trial or check-in can be saved. `DELETE /api/me/data` removes that account’s cloud trials, check-ins, and community posts/reports, then records withdrawal of consent.

## API summary

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register` | Create an account (development route; use institution SSO in production). |
| POST | `/api/auth/login` | Create a 14-day bearer-token session. |
| POST | `/api/consents/cloud-trial-summaries` | Record the student’s explicit storage choice. |
| GET/POST | `/api/trials` | Read or save that account’s aggregate trial summaries. |
| POST | `/api/checkins` | Save an optional self-labelled check-in. |
| GET/POST | `/api/community/posts` | Read or share an anonymous, practical community note. |
| POST | `/api/community/posts/{id}/report` | Report a community note; three reports hide it from the public feed. |
| POST | `/api/reflection` | Send one explicitly consented reflection to the AI assistant; the API does not persist the text. |
| GET | `/api/integrations/status` | Signed-in, secret-free readiness report for the optional provider, FCM, Supabase, and LangGraph integrations. |
| GET | `/api/integrations/firebase-config` | Return Firebase’s public web identifiers only when FCM is configured. |
| GET/POST | `/api/integrations/notifications/preference` | Read or change a student’s opt-in FCM preference and quiet hours. |
| POST | `/api/integrations/fcm/registrations` | Store one explicitly consented Firebase Installation ID, encrypted at rest. |
| DELETE | `/api/me/data` | Remove the signed-in student’s stored trials and check-ins. |

## Reflection assistant setup

The reflection assistant is intentionally unavailable until the server has an API key. It never receives typing cadence, scrolling history, account details, or a reflection unless the student ticks the explicit consent box in the Reflect view. Equilibrium does not store the reflection text or the model response.

Set the key only in the server environment, never in `app.js` or the browser:

```sh
OPENAI_API_KEY="your-key" OPENAI_REFLECTION_MODEL="gpt-5.4-mini" python3 server.py
```

Without this configuration, the UI explains that the assistant is unavailable and keeps the writing in the browser. The assistant is framed as a short reflection aid, not a counsellor or crisis service.

Before production deployment, place this API behind HTTPS, replace password sign-in with institution SSO, use a managed encrypted database with backups and access controls, set a retention schedule, and complete security, DPO and research/ethics review.

See [INTEGRATIONS.md](INTEGRATIONS.md) for the disabled-by-default Gemini/Mistral provider adapters, Firebase deployment requirements, Supabase migration, and LangGraph approval gate.
