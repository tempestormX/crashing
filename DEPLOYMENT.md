# HTTPS deployment path: Firebase Hosting + Cloud Run

This configuration gives Equilibrium one HTTPS origin, so browser requests,
the Firebase service worker, and `/api/*` stay same-origin:

```text
Student browser → Firebase Hosting → Cloud Run (Equilibrium Python server)
```

`firebase.json` rewrites all requests to the Cloud Run service
`equilibrium-api` in `asia-southeast1`. The server now honours `PORT` and binds
to `EQUILIBRIUM_HOST`; local use remains `127.0.0.1:8000` by default.

## Important production gate

Do not deploy this as a real student service while it still uses local SQLite.
Cloud Run's filesystem is ephemeral, so accounts, consent, FCM registrations,
and community records would not be durable. First complete the Supabase Auth
and Postgres adapter, test account/data deletion, and obtain institutional
security/DPO approval.

The configuration may be deployed only as a non-production technical demo with
synthetic accounts and no real student data.

## When the Supabase migration is ready

1. In Google Cloud Console, enable Cloud Run and Cloud Build for
   `equilibrium-a76db`; ensure billing approval is in place.
2. Deploy the included `Dockerfile` as the Cloud Run service named
   `equilibrium-api` in `asia-southeast1`.
3. Add the server environment variables in Cloud Run's secret/environment
   configuration. Never put secrets in `firebase.json`, source files, or a
   browser script.
4. In Firebase Hosting, deploy the included rewrite configuration. It routes
   the HTTPS domain to the Cloud Run service.
5. Visit `/api/health`, sign in, then enable Background device reminders from
   the Privacy view. Only after that explicit opt-in will an encrypted Firebase
   Installation ID be registered.

## Required server variables

- Firebase public web values: `FIREBASE_PROJECT_ID`, `FIREBASE_WEB_API_KEY`,
  `FIREBASE_MESSAGING_SENDER_ID`, `FIREBASE_APP_ID`, `FIREBASE_VAPID_KEY`
- Server secret: `EQUILIBRIUM_DEVICE_ENCRYPTION_KEY`
- Reflection provider credentials, if enabled
- Supabase server credentials only after the reviewed adapter is live

FCM registration is implemented. A production FCM sender still needs a
service-account/OAuth job runner, rate limits, quiet-hour enforcement, and an
idempotent send ledger; it is intentionally outside this deployment config.
