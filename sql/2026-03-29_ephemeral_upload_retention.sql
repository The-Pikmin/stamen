-- Ephemeral upload retention support for plant_uploads
-- Apply in Supabase SQL editor before enabling the cleanup job.

alter table public.plant_uploads
    add column if not exists retention_state text not null default 'retained',
    add column if not exists expires_at timestamptz null,
    add column if not exists retained_at timestamptz null;

update public.plant_uploads
set retention_state = 'retained'
where retention_state is null;

create index if not exists plant_uploads_retention_state_expires_at_idx
    on public.plant_uploads (retention_state, expires_at);

alter table public.plant_uploads
    add constraint plant_uploads_retention_state_check
    check (retention_state in ('ephemeral', 'retained', 'deleting'))
    not valid;

alter table public.plant_uploads
    validate constraint plant_uploads_retention_state_check;
