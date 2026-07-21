PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL COLLATE NOCASE UNIQUE,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  disabled_at TEXT
);

CREATE TABLE IF NOT EXISTS account_sessions (
  token_hash TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS consent_events (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  scope TEXT NOT NULL CHECK (scope IN ('cloud_trial_summaries')),
  granted INTEGER NOT NULL CHECK (granted IN (0, 1)),
  policy_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cadence_trials (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  timing_events INTEGER NOT NULL CHECK (timing_events >= 0),
  median_ms INTEGER NOT NULL CHECK (median_ms >= 0),
  variability_pct INTEGER NOT NULL CHECK (variability_pct >= 0),
  correction_count INTEGER NOT NULL CHECK (correction_count >= 0),
  long_pause_count INTEGER NOT NULL CHECK (long_pause_count >= 0),
  client_created_at TEXT NOT NULL,
  stored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cadence_checkins (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  trial_id TEXT REFERENCES cadence_trials(id) ON DELETE SET NULL,
  label TEXT NOT NULL CHECK (label IN ('steady', 'stretched', 'depleted')),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  created_at TEXT NOT NULL,
  details TEXT
);

CREATE TABLE IF NOT EXISTS community_posts (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  topic TEXT NOT NULL CHECK (topic IN ('deadlines', 'sleep', 'meals', 'boundaries', 'asking_for_help')),
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 500),
  status TEXT NOT NULL CHECK (status IN ('published', 'pending', 'removed')) DEFAULT 'published',
  created_at TEXT NOT NULL,
  report_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS community_reports (
  id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  reason TEXT NOT NULL CHECK (reason IN ('personal_information', 'unsafe', 'abuse', 'other')),
  created_at TEXT NOT NULL,
  UNIQUE(post_id, account_id)
);

CREATE TABLE IF NOT EXISTS notification_preferences (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  fcm_enabled INTEGER NOT NULL DEFAULT 0 CHECK (fcm_enabled IN (0, 1)),
  quiet_start TEXT,
  quiet_end TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fcm_device_registrations (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  installation_id_hash TEXT NOT NULL UNIQUE,
  encrypted_installation_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trials_account_time ON cadence_trials(account_id, stored_at DESC);
CREATE INDEX IF NOT EXISTS idx_consents_account_time ON consent_events(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_community_posts_status_time ON community_posts(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fcm_registrations_account ON fcm_device_registrations(account_id);
