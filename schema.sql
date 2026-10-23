-- Synapsed schema for Neon Postgres. Run once as the database owner role.
-- Prerequisite: create the application role first (see the end of this file).

-- Enable pgvector extension for RAG and semantic clustering
create extension if not exists vector;

-- 1. Workspaces and membership (tenant boundary)
create table workspaces (
    id uuid default gen_random_uuid() primary key,
    name text not null,
    company text not null,
    industry text not null,
    created_at timestamptz default timezone('utc', now()) not null
);

create table workspace_members (
    workspace_id uuid references workspaces(id) on delete cascade,
    user_id uuid not null,                    -- Neon Auth user id (JWT sub)
    role text not null default 'owner',   -- owner | pm | researcher | viewer
    primary key (workspace_id, user_id)
);

-- 2. Campaigns / sub-campaigns partitioning
create table campaigns (
    id uuid default gen_random_uuid() primary key,
    workspace_id uuid not null references workspaces(id) on delete cascade,
    name text not null,
    goal text,
    created_at timestamptz default timezone('utc', now()) not null
);

-- 3. Customer segments (drive Business Impact weighting)
create table segments (
    id uuid default gen_random_uuid() primary key,
    campaign_id uuid not null references campaigns(id) on delete cascade,
    name text not null,                       -- e.g. 'Enterprise'
    tier text not null check (tier in ('enterprise', 'mid_market', 'free', 'other')),
    weight numeric(3,1) not null default 1.0 check (weight > 0),
    description text
);

-- 4. User personas
create table personas (
    id uuid default gen_random_uuid() primary key,
    campaign_id uuid not null references campaigns(id) on delete cascade,
    segment_id uuid references segments(id) on delete set null,
    name text not null,
    description text not null,
    attributes jsonb default '{}'::jsonb
);

-- 5. Uploaded resources (Knowledge Vault)
create table resources (
    id uuid default gen_random_uuid() primary key,
    campaign_id uuid not null references campaigns(id) on delete cascade,
    title text not null,
    source_type text not null check (source_type in
        ('transcript','ticket','survey','audio','video','ocr','pdf','web_scrape')),
    source_url text,
    storage_path text,                        -- object key in Neon Object Storage
    content text not null,                    -- PII-scrubbed text
    summary text,                             -- short preview shown while staged
    language text,
    segment_id uuid references segments(id) on delete set null,
    content_hash text not null,               -- sha256 of cleaned text, for de-duplication
    pii_redacted boolean not null default false,
    pii_note text,                            -- set when names may remain (e.g. non-English text)
    status text not null default 'staged' check (status in ('staged','approved','rejected')),
    analyzed_at timestamptz,                  -- set once the analysis graph has extracted its pain points
    created_at timestamptz default timezone('utc', now()) not null,
    unique (campaign_id, content_hash)
);

-- 6. Resource embedding chunks (768-dim gemini-embedding-001)
create table resource_chunks (
    id uuid default gen_random_uuid() primary key,
    resource_id uuid not null references resources(id) on delete cascade,
    chunk_index int not null,
    content text not null,
    start_offset int not null,                -- character offsets into resources.content
    end_offset int not null,
    embedding vector(768)
);
create index resource_chunks_embedding_idx
    on resource_chunks using hnsw (embedding vector_cosine_ops);

-- 7. Semantic cluster themes
create table themes (
    id uuid default gen_random_uuid() primary key,
    campaign_id uuid not null references campaigns(id) on delete cascade,
    label text not null,
    color_code text not null,
    description text,
    frequency int not null default 0,                         -- number of insights
    business_impact numeric(5,2) not null default 0,          -- 0-100
    created_at timestamptz default timezone('utc', now()) not null
);

-- 8. Extracted insights
create table insights (
    id uuid default gen_random_uuid() primary key,
    campaign_id uuid not null references campaigns(id) on delete cascade,
    theme_id uuid references themes(id) on delete set null,
    segment_id uuid references segments(id) on delete set null,
    use_case text,
    summary_text text not null,
    severity int not null default 3 check (severity between 1 and 5),
    sentiment text not null default 'neutral' check (sentiment in ('positive','neutral','negative')),
    kind text not null default 'pain_point' check (kind in ('pain_point','feature_request')),
    confidence_score numeric(3,2) check (confidence_score between 0.00 and 1.00),
    embedding vector(768),
    created_at timestamptz default timezone('utc', now()) not null
);
create index insights_embedding_idx on insights using hnsw (embedding vector_cosine_ops);

-- 9. Granular citations (powers click-to-highlight)
create table citations (
    id uuid default gen_random_uuid() primary key,
    insight_id uuid not null references insights(id) on delete cascade,
    resource_id uuid not null references resources(id) on delete cascade,
    chunk_id uuid references resource_chunks(id) on delete set null,
    text_snippet text not null,
    start_offset int not null,
    end_offset int not null
);

-- 10. Roadmap items (ICE = Impact x Confidence x Ease)
create table roadmap_items (
    id uuid default gen_random_uuid() primary key,
    campaign_id uuid not null references campaigns(id) on delete cascade,
    theme_id uuid references themes(id) on delete set null,
    insight_id uuid references insights(id) on delete set null,
    title text not null,
    description text not null,
    horizon text not null check (horizon in ('now','next','later')),
    impact_score int not null check (impact_score between 1 and 10),
    confidence_score int not null check (confidence_score between 1 and 10),
    ease_score int not null check (ease_score between 1 and 10),
    ice_score int generated always as (impact_score * confidence_score * ease_score) stored,
    created_at timestamptz default timezone('utc', now()) not null
);

-- 11. Generated PRDs
create table prds (
    id uuid default gen_random_uuid() primary key,
    roadmap_item_id uuid not null references roadmap_items(id) on delete cascade,
    content jsonb not null,                   -- structured PRD (validated by Pydantic)
    markdown text not null,
    jira_issue_key text,
    created_at timestamptz default timezone('utc', now()) not null
);

-- 12. Agent runs (Laboratory pipeline view, run history and replay)
create table agent_runs (
    id uuid default gen_random_uuid() primary key,
    campaign_id uuid not null references campaigns(id) on delete cascade,
    run_id uuid not null,                     -- groups the nodes of one pipeline run
    node text not null,                       -- 'triage' | 'extraction' | 'clustering' | ...
    status text not null check (status in ('running','done','error')),
    model_used text,
    prompt text,
    input jsonb,
    output jsonb,
    tokens int default 0,
    latency_ms int,
    created_at timestamptz default timezone('utc', now()) not null
);

-- 13. Telemetry
create table telemetry_logs (
    id uuid default gen_random_uuid() primary key,
    campaign_id uuid not null references campaigns(id) on delete cascade,
    model_used text not null,
    tokens_processed integer not null,
    latency_ms int,
    action_type text not null,
    fallback_from text,                       -- set when a provider switch happened
    created_at timestamptz default timezone('utc', now()) not null
);

-- 14. Audit logs (Enterprise Shield)
create table audit_logs (
    id uuid default gen_random_uuid() primary key,
    workspace_id uuid not null references workspaces(id) on delete cascade,
    actor text not null,
    action text not null,
    target_resource text,
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz default timezone('utc', now()) not null
);

-- ---------- Search functions ----------
create or replace function match_chunks(
    query_embedding vector(768), match_campaign uuid,
    match_count int default 8, only_approved boolean default true)
returns table (id uuid, resource_id uuid, content text,
               start_offset int, end_offset int, similarity float)
language sql stable as $$
    select c.id, c.resource_id, c.content, c.start_offset, c.end_offset,
           1 - (c.embedding <=> query_embedding) as similarity
    from resource_chunks c
    join resources r on r.id = c.resource_id
    where r.campaign_id = match_campaign
      and (not only_approved or r.status = 'approved')
    order by c.embedding <=> query_embedding
    limit match_count;
$$;

create or replace function match_insights(
    query_embedding vector(768), match_campaign uuid, match_count int default 5)
returns table (id uuid, theme_id uuid, summary_text text, similarity float)
language sql stable as $$
    select i.id, i.theme_id, i.summary_text,
           1 - (i.embedding <=> query_embedding) as similarity
    from insights i
    where i.campaign_id = match_campaign and i.embedding is not null
    order by i.embedding <=> query_embedding
    limit match_count;
$$;

-- ---------- Row Level Security ----------
-- The browser never connects to Postgres. FastAPI verifies the Neon Auth JWT, then runs
-- each request in a transaction as the non-owner role synapsed_app after
--     select set_config('app.user_id', <jwt sub>, true);
-- so these policies scope every query to the signed-in user's workspaces.
-- Migrations and the demo seed use the owner role (DATABASE_URL_ADMIN).
create or replace function current_app_user() returns uuid
language sql stable as $$
    select nullif(current_setting('app.user_id', true), '')::uuid;
$$;

create or replace function is_member(ws uuid) returns boolean
language sql security definer stable set search_path = public as $$
    select exists (select 1 from workspace_members
                   where workspace_id = ws and user_id = current_app_user());
$$;

-- A new workspace has no members yet, so creation goes through this function,
-- which inserts the workspace and its owner membership in one step.
create or replace function create_workspace(p_name text, p_company text, p_industry text)
returns uuid language plpgsql security definer set search_path = public as $$
declare ws uuid;
begin
    if current_app_user() is null then
        raise exception 'not authenticated';
    end if;
    insert into workspaces (name, company, industry)
    values (p_name, p_company, p_industry) returning id into ws;
    insert into workspace_members (workspace_id, user_id, role)
    values (ws, current_app_user(), 'owner');
    return ws;
end;
$$;

create or replace function campaign_workspace(c uuid) returns uuid
language sql security definer stable set search_path = public as $$
    select workspace_id from campaigns where id = c;
$$;

alter table workspaces        enable row level security;
alter table workspace_members enable row level security;
alter table campaigns         enable row level security;
alter table resource_chunks   enable row level security;
alter table citations         enable row level security;
alter table prds              enable row level security;
alter table audit_logs        enable row level security;

create policy ws_member   on workspaces        for all using (is_member(id));
create policy mem_self    on workspace_members for select using (user_id = current_app_user());
create policy camp_member on campaigns         for all using (is_member(workspace_id));
create policy audit_read  on audit_logs        for select using (is_member(workspace_id));
create policy chunk_member on resource_chunks  for all using (
    is_member(campaign_workspace((select campaign_id from resources r where r.id = resource_id))));
create policy cite_member on citations         for all using (
    is_member(campaign_workspace((select campaign_id from insights i where i.id = insight_id))));
create policy prd_member  on prds              for all using (
    is_member(campaign_workspace((select campaign_id from roadmap_items ri where ri.id = roadmap_item_id))));

-- Tables that carry campaign_id share one policy shape
do $$
declare t text;
begin
    foreach t in array array['segments','personas','resources','themes','insights',
                             'roadmap_items','agent_runs','telemetry_logs']
    loop
        execute format('alter table %I enable row level security', t);
        execute format(
            'create policy %I on %I for all using (is_member(campaign_workspace(campaign_id)))',
            t || '_member', t);
    end loop;
end $$;

-- ---------- Audit logging ----------
create or replace function log_audit_event() returns trigger
language plpgsql security definer set search_path = public as $$
declare
    rec jsonb;
    ws uuid;
begin
    if TG_OP = 'DELETE' then rec := to_jsonb(old); else rec := to_jsonb(new); end if;

    if rec ? 'workspace_id' then
        ws := (rec->>'workspace_id')::uuid;
    elsif rec ? 'campaign_id' then
        select workspace_id into ws from campaigns where id = (rec->>'campaign_id')::uuid;
    end if;

    if ws is not null then
        insert into audit_logs (workspace_id, actor, action, target_resource, metadata)
        values (ws, coalesce(current_app_user()::text, 'system_agent'), TG_OP, TG_TABLE_NAME,
                jsonb_build_object('row_id', rec->>'id'));
    end if;
    return null;
exception when foreign_key_violation then
    return null;   -- workspace being deleted by cascade
end;
$$;

create trigger audit_insights   after insert or update or delete on insights
    for each row execute function log_audit_event();
create trigger audit_resources  after insert or update or delete on resources
    for each row execute function log_audit_event();
create trigger audit_roadmap    after insert or update or delete on roadmap_items
    for each row execute function log_audit_event();

-- 15. Rate limits: fixed-window counters per user, shared by every server instance
create table if not exists rate_limits (
    user_id uuid not null,
    bucket text not null,                      -- 'chat', 'ingest', ...
    window_kind text not null check (window_kind in ('minute', 'day')),
    window_start timestamp not null,           -- UTC start of the window
    hits int not null default 0,
    primary key (user_id, bucket, window_kind, window_start)
);
create index if not exists rate_limits_window_idx on rate_limits (window_start);
alter table rate_limits enable row level security;
do $$ begin
    if not exists (select 1 from pg_policies where tablename = 'rate_limits' and policyname = 'rate_limits_own') then
        create policy rate_limits_own on rate_limits for all
            using (user_id = current_app_user()) with check (user_id = current_app_user());
    end if;
end $$;
grant select, insert, update, delete on rate_limits to synapsed_app;

-- ---------- Application role ----------
-- Create synapsed_app in the Neon console (Roles) or with
--   create role synapsed_app with login password '<strong password>';
-- It is not the table owner, so RLS applies to it.
grant usage on schema public to synapsed_app;
grant select, insert, update, delete on all tables in schema public to synapsed_app;
grant execute on all functions in schema public to synapsed_app;
alter default privileges in schema public
    grant select, insert, update, delete on tables to synapsed_app;
