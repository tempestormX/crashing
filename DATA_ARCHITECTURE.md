# Equilibrium data architecture

## Prototype behaviour

The current browser prototype stores only on-device aggregate cadence data:

- typing-event count;
- median inter-key interval;
- timing variability;
- correction count and long-pause rate;
- student-selected check-in label; and
- the locally trained model and normalisation metadata.

It does not persist trial text, individual keys, screenshots, URLs, web history, raw timestamps, or raw scrolling events. The student can inspect trial summaries and delete the local baseline, trial history, labels, and model.

## If a shared research database is introduced

This must be a separate, opt-in research programme - not a condition of using Equilibrium.

```text
Identity service             Consent ledger              Research telemetry store
----------------             --------------              ------------------------
student account ID     ->    pseudonymous study ID  ->   aggregate feature windows
email / password hash        purpose + version           self-selected check-in label
authentication only          withdrawal state             model-quality metrics
                             retention expiry             no raw text or key events
```

Rules for the production design:

1. Create a random study ID. Do not use the student number, email, or name as the telemetry key.
2. Keep identity, consent, and telemetry in separate services with separate access roles.
3. Upload only pre-aggregated feature windows created on-device. Never upload typing content, individual key events, raw scroll events, pages, or browsing history.
4. Make sharing off by default. Obtain explicit, purpose-specific consent for research, model improvement, and any new use separately.
5. Show an exportable personal record, a clear retention period, and a one-click withdrawal/deletion path.
6. Train shared models only on opted-in, de-identified aggregate data. Evaluate bias by device type, language, study mode, and accessibility needs before release.
7. Encrypt data in transit and at rest; use least-privilege access, audit logs, breach response, and a named data-protection owner.
8. Do not expose individual predictions to universities, instructors, parents, or counsellors. Student-directed sharing must be a separate, explicit action.

For Singapore deployment, confirm the final workflow with the institution's data protection officer and legal team. The PDPA requires notification and consent for collection/use/disclosure, purpose limitation, security measures, and retention limits.
