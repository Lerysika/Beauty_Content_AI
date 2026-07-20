# --- ЭТАП 4: сервисный слой для истории генераций ---
# Вся работа с таблицей generation_history находится здесь.
# Обработчики в main.py не содержат SQL-запросов напрямую.

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


async def save_generation(
    telegram_id: int,
    content_type: str,
    topic: str,
    generated_text: str,
) -> dict:
    """Сохраняет одну успешную генерацию в историю пользователя."""
    payload = {
        "telegram_id": telegram_id,
        "content_type": content_type,
        "topic": topic,
        "generated_text": generated_text,
    }
    result = supabase.table("generation_history").insert(payload).execute()
    return result.data[0] if result.data else payload


async def get_recent_generations(telegram_id: int, limit: int = 10) -> list[dict]:
    """Возвращает последние генерации пользователя, сначала самые новые."""
    result = (
        supabase.table("generation_history")
        .select("content_type, topic, generated_text, created_at")
        .eq("telegram_id", telegram_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


POSTS_MAX_TOTAL = 20


async def count_user_posts(telegram_id: int) -> int:
    """Возвращает общее число сохранённых генераций пользователя."""
    result = (
        supabase.table("generation_history")
        .select("id", count="exact")
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return result.count or 0


async def get_user_posts(telegram_id: int, limit: int = 10, offset: int = 0) -> list[dict]:
    """
    Возвращает страницу публикаций пользователя для раздела «Мои посты».
    Сортировка: created_at DESC. Для MVP — не более POSTS_MAX_TOTAL последних записей.
    """
    if offset >= POSTS_MAX_TOTAL:
        return []

    fetch_limit = min(limit, POSTS_MAX_TOTAL - offset)
    end = offset + fetch_limit - 1

    result = (
        supabase.table("generation_history")
        .select("id, content_type, topic, created_at")
        .eq("telegram_id", telegram_id)
        .order("created_at", desc=True)
        .range(offset, end)
        .execute()
    )
    return result.data or []


async def get_post_by_id(post_id: int, telegram_id: int) -> dict | None:
    """Возвращает одну публикацию по id, только если она принадлежит пользователю."""
    result = (
        supabase.table("generation_history")
        .select("id, content_type, topic, generated_text, created_at")
        .eq("id", post_id)
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None
