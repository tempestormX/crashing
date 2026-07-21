# Equilibrium

Equilibrium is a privacy-first study companion for students. It helps a student
notice changes in their own study rhythm, choose a small reset, and find support
on their own terms. It is not a diagnostic or crisis service.

Built for OpenAI Build Week with Codex and GPT-5.6.

## What it does

- Runs an opt-in typing trial that keeps the typed content private and works
  only with aggregate timing features such as pace, pauses, corrections, and
  longer gaps.
- Compares a session with the student's own local baseline rather than a
  universal stress score.
- Offers student-chosen focus resets and optional gentle reminders; a signal
  never sends a notification automatically.
- Provides opt-in reflection and direct Singapore support routes without
  automatically contacting, referring, or disclosing information to anyone.
- Supports local data controls, including baseline reset and logout.

## Run locally

Requirements: Python 3.10+ and a modern browser.

```sh
git clone https://github.com/tempestormX/crashing.git
cd crashing
python3 server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The base demo runs locally with SQLite and does not require external API keys.
Optional integrations are deliberately disabled until their credentials and
consent gates are configured.

## Technology

- HTML, CSS, JavaScript, and Python
- TensorFlow.js for the local baseline model
- SQLite for the local demo datastore
- Optional, consent-gated Firebase Cloud Messaging, Supabase, and LangGraph
  integrations
- Firebase Hosting and Cloud Run deployment configuration

## How Codex and GPT-5.6 were used

Codex with GPT-5.6 accelerated the implementation of the student flow, the
local-first API and privacy controls, the cadence-trial workflow, and guarded
integration paths. It also supported iterative debugging, interface refinement,
and the project documentation. The project retains human-set safety boundaries:
no raw typing text, reflection text, browsing history, or automatic referrals
are sent by the app.

## Safety and privacy

The prototype uses synthetic demo data only. Do not deploy it for real student
data without completing the production security, data-protection, authentication,
and retention work described in [DEPLOYMENT.md](DEPLOYMENT.md) and
[INTEGRATIONS.md](INTEGRATIONS.md).

## Further documentation

- [DATABASE.md](DATABASE.md) — local database and privacy details
- [DATA_ARCHITECTURE.md](DATA_ARCHITECTURE.md) — data-flow design
- [INTEGRATIONS.md](INTEGRATIONS.md) — optional integration gates
- [DEPLOYMENT.md](DEPLOYMENT.md) — demo deployment constraints
