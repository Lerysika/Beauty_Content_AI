-- Beauty AI Bot — схема базы данных для Supabase
-- Выполните в Supabase Dashboard → SQL Editor → Run

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id BIGINT NOT NULL UNIQUE,
    username TEXT,
    sub_status TEXT NOT NULL DEFAULT 'free',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON public.users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_history_user_id ON public.history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_created_at ON public.history(created_at DESC);

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "bot_access_users" ON public.users
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "bot_access_history" ON public.history
    FOR ALL USING (true) WITH CHECK (true);

-- ЭТАП 4: добавить этот блок в конец своего существующего schema.sql

create table if not exists generation_history (
    id bigserial primary key,

    telegram_id bigint not null references users (telegram_id) on delete cascade,

    content_type text not null,

    topic text not null,

    generated_text text not null,

    created_at timestamptz not null default now()
);

create index if not exists generation_history_telegram_id_idx
on generation_history (telegram_id);

create index if not exists generation_history_created_at_idx
on generation_history (created_at desc);

-- Контент-план: полный текст + структура дней для навигации
create table if not exists content_plans (
    telegram_id bigint primary key references users (telegram_id) on delete cascade,
    niche_topic text,
    full_text text not null,
    days_json jsonb not null default '[]'::jsonb,
    updated_at timestamptz not null default now()
);

create index if not exists content_plans_updated_at_idx
on content_plans (updated_at desc);