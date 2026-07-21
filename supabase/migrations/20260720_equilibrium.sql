-- Equilibrium's optional shared-data schema for Supabase/Postgres.
-- Apply this only to a separate production project after DPO/security review.
-- It deliberately excludes reflection text, model responses, raw key events,
-- raw scroll events, browser history, and student identifiers such as email.

create schema if not exists equilibrium;

create table if not exists equilibrium.consent_ledger (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references auth.users(id) on delete cascade,
  purpose text not null check (purpose in ('aggregate_cadence_storage', 'research_model_improvement', 'push_notifications')),
  granted boolean not null,
  policy_version text not null,
  created_at timestamptz not null default now()
);

create table if not exists equilibrium.aggregate_cadence_trials (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references auth.users(id) on delete cascade,
  timing_events integer not null check (timing_events between 0 and 180),
  median_ms integer not null check (median_ms between 0 and 4000),
  variability_pct integer not null check (variability_pct between 0 and 500),
  correction_count integer not null check (correction_count between 0 and 180),
  long_pause_count integer not null check (long_pause_count between 0 and 180),
  client_created_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table if not exists equilibrium.notification_preferences (
  student_id uuid primary key references auth.users(id) on delete cascade,
  enabled boolean not null default false,
  quiet_start time,
  quiet_end time,
  updated_at timestamptz not null default now()
);

create table if not exists equilibrium.fcm_device_registrations (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references auth.users(id) on delete cascade,
  installation_id_hash text not null unique,
  encrypted_installation_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists equilibrium.community_posts (
  id uuid primary key default gen_random_uuid(),
  author_id uuid not null references auth.users(id) on delete cascade,
  topic text not null check (topic in ('deadlines', 'sleep', 'meals', 'boundaries', 'asking_for_help')),
  body text not null check (char_length(body) between 1 and 500),
  status text not null default 'published' check (status in ('published', 'pending', 'removed')),
  created_at timestamptz not null default now(),
  report_count integer not null default 0
);

create table if not exists equilibrium.community_reports (
  id uuid primary key default gen_random_uuid(),
  post_id uuid not null references equilibrium.community_posts(id) on delete cascade,
  reporter_id uuid not null references auth.users(id) on delete cascade,
  reason text not null check (reason in ('personal_information', 'unsafe', 'abuse', 'other')),
  created_at timestamptz not null default now(),
  unique (post_id, reporter_id)
);

alter table equilibrium.consent_ledger enable row level security;
alter table equilibrium.aggregate_cadence_trials enable row level security;
alter table equilibrium.notification_preferences enable row level security;
alter table equilibrium.fcm_device_registrations enable row level security;
alter table equilibrium.community_posts enable row level security;
alter table equilibrium.community_reports enable row level security;

create policy "students manage their consent" on equilibrium.consent_ledger
  for all to authenticated using (student_id = auth.uid()) with check (student_id = auth.uid());
create policy "students manage their aggregate trials" on equilibrium.aggregate_cadence_trials
  for all to authenticated using (student_id = auth.uid()) with check (student_id = auth.uid());
create policy "students manage their notification preferences" on equilibrium.notification_preferences
  for all to authenticated using (student_id = auth.uid()) with check (student_id = auth.uid());
-- Device IDs are intentionally not exposed to the browser after registration.
create policy "students read published community notes" on equilibrium.community_posts
  for select to authenticated using (status = 'published' or author_id = auth.uid());
create policy "students create their community notes" on equilibrium.community_posts
  for insert to authenticated with check (author_id = auth.uid());
create policy "students delete their own community notes" on equilibrium.community_posts
  for delete to authenticated using (author_id = auth.uid());
create policy "students create their reports" on equilibrium.community_reports
  for insert to authenticated with check (reporter_id = auth.uid());

create index if not exists cadence_trials_student_time on equilibrium.aggregate_cadence_trials(student_id, created_at desc);
create index if not exists community_posts_status_time on equilibrium.community_posts(status, created_at desc);
