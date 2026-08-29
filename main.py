import asyncio
import logging
import os
import ssl
from datetime import datetime
from openai import AsyncOpenAI
from asyncio import Semaphore

import certifi
from aiohttp import ClientSession
from aiohttp.hdrs import USER_AGENT
from aiohttp.http import SERVER_SOFTWARE
from aiohttp_socks import ProxyConnector
from aiogram import Bot, Dispatcher, F, __version__
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import CommandStart, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from dotenv import load_dotenv
from supabase import Client, create_client

# --- ЭТАП 2: промпты вынесены в отдельный пакет prompts/ ---
from prompts import (
    STRATEGY_PROMPT,
    FORMATTING_PROMPT,
    CTA_PROMPT,
    NATURAL_FLOW_PROMPT,
    EMOTION_BALANCE_PROMPT,
    HUMAN_STYLE_PROMPT,
    HUMAN_EDITOR_PROMPT,
    FINAL_QUALITY_PROMPT,
    ANTI_AI_PROMPT,
    build_profile_prompt,
    get_selling_prompt,
    get_expert_prompt,
    get_personal_prompt,
    get_plan_prompt,
)
from prompts.system_prompt import get_system_prompt
from prompts.story_prompt import get_story_prompt
from prompts.post_length_prompt import get_post_length_prompt
from prompts.history_prompt import build_history_prompt, CONTENT_TYPE_LABELS
from utils.telegram_html import sanitize_for_telegram_html
from utils.telegram_messages import send_long_message, send_long_text
from utils.length_validator import get_length_limits, count_chars, validate_length, fallback_truncate
from utils.api_retry import retry_with_backoff
from services.editor_service import editor_pass
from services.generation_history import (
    save_generation,
    get_recent_generations,
    get_user_posts,
    count_user_posts,
    get_post_by_id,
)
from services.content_plan_service import (
    build_after_plan_post_keyboard,
    build_no_plan_keyboard,
    build_plan_days_keyboard,
    create_content_plan,
    format_plan_list,
    get_content_plan,
    get_day_generation_prompt,
    mark_day_completed,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PROXY_URL = os.getenv("PROXY_URL")
AI_API_KEY = os.getenv("AI_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.aitunnel.ru/v1")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.5-flash")

if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    raise ValueError("Заполните BOT_TOKEN, SUPABASE_URL и SUPABASE_KEY в файле .env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

dp = Dispatcher()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Semaphore для ограничения одновременных AI-запросов
ai_semaphore = Semaphore(5)  # Максимум 5 одновременных запросов

ai_client = AsyncOpenAI(
    api_key=AI_API_KEY,
    base_url=AI_BASE_URL,
)


# ==================== FSM STATES ====================

class ContentStates(StatesGroup):
    waiting_for_text_type = State()
    waiting_for_post_length = State()
    waiting_for_topic = State()
    waiting_for_plan_topic = State()


# --- ЭТАП 1: FSM для анкеты-онбординга мастера ---
class OnboardingStates(StatesGroup):
    waiting_for_specialization = State()
    waiting_for_specialization_other = State()
    waiting_for_name = State()
    waiting_for_experience = State()
    waiting_for_avg_check = State()
    waiting_for_services_to_promote = State()


# --- ЭТАП 3: FSM для редактирования отдельных полей профиля ---
class ProfileEditStates(StatesGroup):
    editing_specialization = State()
    editing_specialization_other = State()
    editing_name = State()
    editing_experience = State()
    editing_avg_check = State()
    editing_services_to_promote = State()


EDIT_FIELD_PROMPTS = {
    "name": "🙋 <b>Как тебя теперь называть?</b>",
    "experience": "<b>Какой у тебя стаж в профессии?</b>\n\n<i>Например: 2 года, 6 месяцев, только начинаю</i>",
    "avg_check": "<b>Какой у тебя средний чек?</b>\n\n<i>Например: 2500 руб или «от 1500 до 4000»</i>",
    "services_to_promote": "<b>Какие услуги хочешь продавать чаще?</b>\n\n<i>Например: наращивание, комплекс бровей, SPA-уход</i>",
}

EDIT_FIELD_STATES = {
    "name": ProfileEditStates.editing_name,
    "experience": ProfileEditStates.editing_experience,
    "avg_check": ProfileEditStates.editing_avg_check,
    "services_to_promote": ProfileEditStates.editing_services_to_promote,
}


# ==================== КЛАВИАТУРЫ ====================

def get_welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✨ Тексты / Контент", callback_data="texts"),
                InlineKeyboardButton(text="🎨 Визуал", callback_data="visual"),
            ],
            [InlineKeyboardButton(text="👤 Мой профиль", callback_data="my_profile")],
            [InlineKeyboardButton(text="📝 Мои посты", callback_data="my_posts")],
        ]
    )


def get_text_types_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗓️ Контент-план на 7 дней", callback_data="type_plan")],
            [InlineKeyboardButton(text="📅 Мой контент-план", callback_data="view_content_plan")],
            [InlineKeyboardButton(text="💰 Продающий пост", callback_data="type_selling")],
            [InlineKeyboardButton(text="🧠 Полезный / Экспертный", callback_data="type_expert")],
            [InlineKeyboardButton(text="🎭 Личный / История", callback_data="type_personal")],
            [InlineKeyboardButton(text="↩️ Назад в меню", callback_data="back_to_main")]
        ]
    )


def get_post_length_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Короткий", callback_data="length_short")],
            [InlineKeyboardButton(text="✨ Стандартный", callback_data="length_medium")],
            [InlineKeyboardButton(text="📖 Развернутый", callback_data="length_long")],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="texts")]
        ]
    )


# --- ЭТАП 1: клавиатуры анкеты ---
SPECIALIZATION_OPTIONS = [
    ("Маникюр", "spec_manicure"),
    ("Ресницы", "spec_lashes"),
    ("Брови", "spec_brows"),
    ("Косметология", "spec_cosmetology"),
    ("Парикмахер / Стилист", "spec_hair"),
    ("Другое", "spec_other"),
]
SPECIALIZATION_LABELS = {callback_data: label for label, callback_data in SPECIALIZATION_OPTIONS}


def get_specialization_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=cb)] for label, cb in SPECIALIZATION_OPTIONS]
    )


# --- ЭТАП 3: просмотр и редактирование профиля ---
def get_profile_text(profile: dict) -> str:
    return (
        "👤 <b>Мой профиль</b>\n\n"
        f"🎨 Специализация: <b>{profile.get('specialization') or '—'}</b>\n"
        f"🙋 Имя: <b>{profile.get('name') or '—'}</b>\n"
        f"⏳ Стаж: <b>{profile.get('experience') or '—'}</b>\n"
        f"💰 Средний чек: <b>{profile.get('avg_check') or '—'}</b>\n"
        f"🎯 Продвигаемые услуги: <b>{profile.get('services_to_promote') or '—'}</b>\n\n"
        f"Нажми на поле ниже, чтобы изменить его 👇"
    )


def get_profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Изменить специализацию", callback_data="edit_specialization")],
            [InlineKeyboardButton(text="🙋 Изменить имя", callback_data="edit_name")],
            [InlineKeyboardButton(text="⏳ Изменить стаж", callback_data="edit_experience")],
            [InlineKeyboardButton(text="💰 Изменить средний чек", callback_data="edit_avg_check")],
            [InlineKeyboardButton(text="🎯 Изменить продвигаемые услуги", callback_data="edit_services_to_promote")],
            [InlineKeyboardButton(text="↩️ Назад в меню", callback_data="back_to_main")],
        ]
    )


def get_welcome_text(username: str | None, profile_name: str | None = None) -> str:
    if profile_name:
        name = profile_name
    elif username:
        name = f"@{username}"
    else:
        name = "красавица"
    return (
        f"💎 <b>Добро пожаловать в Beauty AI Studio</b>\n\n"
        f"Привет, {name}! Здесь создают контент, который продаёт.\n\n"
        f"✨ <i>Тексты</i> — продающие посты, контент-планы, stories\n"
        f"🎨 <i>Визуал</i> — идеи для фото, reels и визуальный стиль\n\n"
        f"Выберите направление 👇"
    )


# ==================== SUPABASE: ПОЛЬЗОВАТЕЛИ И ПРОФИЛЬ ====================

async def get_or_create_user(telegram_id: int, username: str | None) -> dict:
    result = (
        supabase.table("users")
        .select("*")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    insert_result = (
        supabase.table("users")
        .insert(
            {
                "telegram_id": telegram_id,
                "username": username,
                "sub_status": "free",
            }
        )
        .execute()
    )
    return insert_result.data[0]


# --- ЭТАП 1: профиль мастера ---
async def get_profile(telegram_id: int) -> dict | None:
    result = (
        supabase.table("profiles")
        .select("*")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


async def save_profile(telegram_id: int, data: dict) -> dict:
    payload = {
        "telegram_id": telegram_id,
        "specialization": data.get("specialization"),
        "name": data.get("name"),
        "experience": data.get("experience"),
        "avg_check": data.get("avg_check"),
        "services_to_promote": data.get("services_to_promote"),
        "onboarding_completed": True,
    }
    result = (
        supabase.table("profiles")
        .upsert(payload, on_conflict="telegram_id")
        .execute()
    )
    return result.data[0] if result.data else payload


# --- ЭТАП 3: точечное обновление одного поля профиля ---
async def update_profile_field(telegram_id: int, field: str, value: str) -> dict:
    result = (
        supabase.table("profiles")
        .update({field: value})
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return result.data[0] if result.data else {}


# ==================== СТАРТ И ОНБОРДИНГ ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if not user:
        return

    await state.clear()

    try:
        await get_or_create_user(telegram_id=user.id, username=user.username)
        profile = await get_profile(user.id)
    except Exception:
        logger.exception("Ошибка при работе с Supabase")
        await message.answer("⚠️ Временная ошибка. Попробуйте позже.")
        return

    if not profile or not profile.get("onboarding_completed"):
        await start_onboarding(message, state)
        return

    await message.answer(
        get_welcome_text(user.username, profile.get("name")),
        reply_markup=get_welcome_keyboard(),
        parse_mode="HTML",
    )


async def start_onboarding(message: Message, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.waiting_for_specialization)
    text = (
        "👋 <b>Давай знакомиться!</b>\n\n"
        "Отвечу на пару вопросов — и буду писать посты с учётом твоей специфики, "
        "а не просто «средний текст про бьюти».\n\n"
        "<b>1/5. Какая у тебя специализация?</b>"
    )
    await message.answer(text, reply_markup=get_specialization_keyboard(), parse_mode="HTML")


async def ask_name(message: Message, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.waiting_for_name)
    await message.answer(
        "<b>2/5. Как тебя зовут?</b>\n\nТак я буду обращаться к тебе.",
        parse_mode="HTML",
    )


@dp.callback_query(OnboardingStates.waiting_for_specialization, F.data.startswith("spec_"))
async def specialization_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data == "spec_other":
        await state.set_state(OnboardingStates.waiting_for_specialization_other)
        await callback.message.edit_text(
            "✏️ Напиши свою специализацию в одном-двух словах:", reply_markup=None
        )
        await callback.answer()
        return

    label = SPECIALIZATION_LABELS.get(callback.data, "Другое")
    await state.update_data(specialization=label)
    await callback.message.edit_text(
        f"✅ Специализация: <b>{label}</b>", reply_markup=None, parse_mode="HTML"
    )
    await ask_name(callback.message, state)
    await callback.answer()


@dp.message(OnboardingStates.waiting_for_specialization)
async def specialization_wrong_input(message: Message) -> None:
    await message.answer("👆 Пожалуйста, выбери вариант на кнопках выше.")


@dp.message(OnboardingStates.waiting_for_specialization_other)
async def specialization_other_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("❌ Пожалуйста, напиши специализацию текстом.")
        return
    await state.update_data(specialization=message.text.strip())
    await ask_name(message, state)


@dp.message(OnboardingStates.waiting_for_name)
async def name_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("❌ Пожалуйста, напиши имя текстом.")
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(OnboardingStates.waiting_for_experience)
    await message.answer(
        "<b>3/5. Какой у тебя стаж в профессии?</b>\n\n<i>Например: 2 года, 6 месяцев, только начинаю</i>",
        parse_mode="HTML",
    )


@dp.message(OnboardingStates.waiting_for_experience)
async def experience_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("❌ Пожалуйста, напиши ответ текстом.")
        return
    await state.update_data(experience=message.text.strip())
    await state.set_state(OnboardingStates.waiting_for_avg_check)
    await message.answer(
        "<b>4/5. Какой у тебя средний чек?</b>\n\n<i>Например: 2500 руб или «от 1500 до 4000»</i>",
        parse_mode="HTML",
    )


@dp.message(OnboardingStates.waiting_for_avg_check)
async def avg_check_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("❌ Пожалуйста, напиши ответ текстом.")
        return
    await state.update_data(avg_check=message.text.strip())
    await state.set_state(OnboardingStates.waiting_for_services_to_promote)
    await message.answer(
        "<b>5/5. Какие услуги хочешь продавать чаще?</b>\n\n<i>Например: наращивание, комплекс бровей, SPA-уход</i>",
        parse_mode="HTML",
    )


@dp.message(OnboardingStates.waiting_for_services_to_promote)
async def services_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("❌ Пожалуйста, напиши ответ текстом.")
        return

    await state.update_data(services_to_promote=message.text.strip())
    data = await state.get_data()
    user = message.from_user

    try:
        profile = await save_profile(user.id, data)
    except Exception:
        logger.exception("Ошибка при сохранении профиля")
        await message.answer(
            "⚠️ Не получилось сохранить профиль. Попробуй ещё раз, набрав /start."
        )
        return

    await state.clear()
    await message.answer(
        "🎉 <b>Профиль готов!</b> Теперь тексты будут учитывать твою специфику.",
        parse_mode="HTML",
    )
    await message.answer(
        get_welcome_text(user.username, profile.get("name")),
        reply_markup=get_welcome_keyboard(),
        parse_mode="HTML",
    )


# ==================== ГЛАВНОЕ МЕНЮ ====================

@dp.callback_query(F.data.in_({"texts", "visual", "back_to_main"}))
async def handle_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    if callback.data == "back_to_main":
        user = callback.from_user
        await callback.message.edit_text(
            get_welcome_text(user.username),
            reply_markup=get_welcome_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    if callback.data == "texts":
        text = "✨ <b>Выберите формат:</b>\n\nЯ могу составить контент-план на неделю или написать отдельный сочный пост 👇"
        await callback.message.edit_text(text, reply_markup=get_text_types_keyboard(), parse_mode="HTML")
    else:
        text = "🎨 <b>Визуал</b>\n\nРаздел в разработке — скоро здесь будут идеи для контента."
        await callback.message.answer(text, parse_mode="HTML")

    await callback.answer()


# ==================== ЭТАП 3: ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ====================

@dp.callback_query(F.data == "my_profile")
async def handle_my_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    try:
        profile = await get_profile(callback.from_user.id)
    except Exception:
        logger.exception("Ошибка при получении профиля")
        await callback.answer("⚠️ Временная ошибка. Попробуй позже.", show_alert=True)
        return

    if not profile:
        await callback.answer("Профиль не найден — набери /start, чтобы пройти анкету.", show_alert=True)
        return

    await callback.message.edit_text(
        get_profile_text(profile), reply_markup=get_profile_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


async def show_updated_profile(message: Message, telegram_id: int) -> None:
    profile = await get_profile(telegram_id)
    await message.answer(
        "✅ Обновлено!\n\n" + get_profile_text(profile),
        reply_markup=get_profile_keyboard(),
        parse_mode="HTML",
    )


# --- Редактирование специализации (кнопки, как в онбординге) ---
@dp.callback_query(F.data == "edit_specialization")
async def start_edit_specialization(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileEditStates.editing_specialization)
    await callback.message.edit_text(
        "🎨 <b>Выбери новую специализацию:</b>", reply_markup=get_specialization_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(ProfileEditStates.editing_specialization, F.data.startswith("spec_"))
async def edit_specialization_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data == "spec_other":
        await state.set_state(ProfileEditStates.editing_specialization_other)
        await callback.message.edit_text("✏️ Напиши свою специализацию в одном-двух словах:", reply_markup=None)
        await callback.answer()
        return

    label = SPECIALIZATION_LABELS.get(callback.data, "Другое")
    try:
        await update_profile_field(callback.from_user.id, "specialization", label)
    except Exception:
        logger.exception("Ошибка при обновлении специализации")
        await callback.answer("⚠️ Не получилось сохранить. Попробуй ещё раз.", show_alert=True)
        return

    await state.clear()
    await show_updated_profile(callback.message, callback.from_user.id)
    await callback.answer()


@dp.message(ProfileEditStates.editing_specialization_other)
async def edit_specialization_other_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("❌ Пожалуйста, напиши специализацию текстом.")
        return

    try:
        await update_profile_field(message.from_user.id, "specialization", message.text.strip())
    except Exception:
        logger.exception("Ошибка при обновлении специализации")
        await message.answer("⚠️ Не получилось сохранить. Попробуй ещё раз.")
        return

    await state.clear()
    await show_updated_profile(message, message.from_user.id)


# --- Редактирование текстовых полей: имя, стаж, средний чек, услуги ---
@dp.callback_query(F.data.startswith("edit_") & ~F.data.in_({"edit_specialization"}))
async def start_edit_text_field(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.removeprefix("edit_")
    if field not in EDIT_FIELD_PROMPTS:
        await callback.answer()
        return

    await state.set_state(EDIT_FIELD_STATES[field])
    await state.update_data(edit_field=field)
    await callback.message.edit_text(EDIT_FIELD_PROMPTS[field], reply_markup=None, parse_mode="HTML")
    await callback.answer()


@dp.message(StateFilter(*EDIT_FIELD_STATES.values()))
async def edit_text_field_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("❌ Пожалуйста, напиши ответ текстом.")
        return

    data = await state.get_data()
    field = data.get("edit_field")

    try:
        await update_profile_field(message.from_user.id, field, message.text.strip())
    except Exception:
        logger.exception(f"Ошибка при обновлении поля профиля: {field}")
        await message.answer("⚠️ Не получилось сохранить. Попробуй ещё раз.")
        return

    await state.clear()
    await show_updated_profile(message, message.from_user.id)


# ==================== ЭТАП 4: БИБЛИОТЕКА ПОСТОВ ("Мои посты") ====================

POSTS_PAGE_SIZE = 10
POSTS_MAX_TOTAL = 20  # для MVP: не показываем больше последних 20 записей

NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

MONTHS_RU_GENITIVE = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _format_date_ru(created_at: str) -> str:
    """'2026-07-17T10:23:00+00:00' -> '17 июля'."""
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return f"{dt.day} {MONTHS_RU_GENITIVE[dt.month]}"
    except Exception:
        return created_at


def get_posts_list_text(posts: list[dict]) -> str:
    if not posts:
        return (
            "📝 <b>У вас пока нет сохранённых постов.</b>\n\n"
            "Создайте первую публикацию — и она появится здесь."
        )

    lines = ["📝 <b>Мои посты</b>\n"]
    for post in posts:
        label = CONTENT_TYPE_LABELS.get(post.get("content_type"), post.get("content_type") or "—")
        lines.append(
            f"📝 <b>{label.capitalize()}</b>\n"
            f"💅 {post.get('topic', '—')}\n"
            f"📅 {_format_date_ru(post.get('created_at', ''))}"
        )
    return "\n\n".join(lines)


def get_posts_list_keyboard(posts: list[dict], offset: int, total: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, post in enumerate(posts):
        row.append(
            InlineKeyboardButton(text=NUMBER_EMOJIS[i], callback_data=f"post_view_{post['id']}_{offset}")
        )
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="⬅ Предыдущие", callback_data=f"posts_page_{offset - POSTS_PAGE_SIZE}"))
    if offset + POSTS_PAGE_SIZE < total:
        nav_row.append(InlineKeyboardButton(text="Следующие ➡", callback_data=f"posts_page_{offset + POSTS_PAGE_SIZE}"))
    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton(text="↩️ Назад в меню", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_empty_posts_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍ Создать пост", callback_data="texts")],
            [InlineKeyboardButton(text="↩️ Назад в меню", callback_data="back_to_main")],
        ]
    )


def get_post_detail_text(post: dict) -> str:
    label = CONTENT_TYPE_LABELS.get(post.get("content_type"), post.get("content_type") or "—")
    return (
        f"📝 <b>{label.capitalize()} пост</b>\n\n"
        f"Тема:\n{post.get('topic', '—')}\n\n"
        f"Дата:\n{_format_date_ru(post.get('created_at', ''))}\n\n"
        f"――――――――――――\n\n"
        f"{sanitize_for_telegram_html(post.get('generated_text', ''))}\n\n"
        f"――――――――――――"
    )


def get_post_detail_keyboard(back_offset: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data=f"posts_page_{back_offset}")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")],
        ]
    )


async def show_posts_page(callback: CallbackQuery, offset: int) -> None:
    telegram_id = callback.from_user.id
    try:
        total = min(await count_user_posts(telegram_id), POSTS_MAX_TOTAL)
        posts = await get_user_posts(telegram_id, limit=POSTS_PAGE_SIZE, offset=offset)
    except Exception:
        logger.exception("Не удалось получить список постов")
        await callback.answer("⚠️ Не получилось загрузить посты. Попробуй позже.", show_alert=True)
        return

    if not posts:
        text, keyboard = get_posts_list_text([]), get_empty_posts_keyboard()
    else:
        text, keyboard = get_posts_list_text(posts), get_posts_list_keyboard(posts, offset, total)

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "my_posts")
async def handle_my_posts(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show_posts_page(callback, offset=0)
    await callback.answer()


@dp.callback_query(F.data.startswith("posts_page_"))
async def handle_posts_page(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        offset = int(callback.data.removeprefix("posts_page_"))
    except ValueError:
        offset = 0
    await show_posts_page(callback, offset=offset)
    await callback.answer()


@dp.callback_query(F.data.startswith("post_view_"))
async def handle_post_view(callback: CallbackQuery, state: FSMContext) -> None:
    payload = callback.data.removeprefix("post_view_")
    post_id_str, _, offset_str = payload.partition("_")
    try:
        post_id = int(post_id_str)
        back_offset = int(offset_str) if offset_str else 0
    except ValueError:
        await callback.answer()
        return

    try:
        post = await get_post_by_id(post_id, callback.from_user.id)
    except Exception:
        logger.exception("Не удалось получить пост")
        await callback.answer("⚠️ Не получилось открыть пост.", show_alert=True)
        return

    if not post:
        await callback.answer("Пост не найден.", show_alert=True)
        return

    await send_long_text(
        callback.message,
        get_post_detail_text(post),
        reply_markup=get_post_detail_keyboard(back_offset),
        parse_mode="HTML",
        edit=True,
    )
    await callback.answer()


# ==================== КОНТЕНТ-ПЛАН: ОТОБРАЖЕНИЕ И ВЫБОР ДНЯ ====================

@dp.callback_query(F.data == "view_content_plan")
async def handle_view_content_plan(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    plan = await get_content_plan(callback.from_user.id)
    if not plan:
        await callback.message.edit_text(
            "Сначала создайте контент-план 📅",
            reply_markup=build_no_plan_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await callback.message.answer(
        format_plan_list(plan),
        reply_markup=build_plan_days_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("plan_day_"))
async def handle_plan_day(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        day_num = int(callback.data.removeprefix("plan_day_"))
    except ValueError:
        await callback.answer()
        return

    plan = await get_content_plan(callback.from_user.id)
    if not plan:
        await callback.message.edit_text(
            "Сначала создайте контент-план 📅",
            reply_markup=build_no_plan_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    day = plan.get_day(day_num)
    if not day:
        await callback.answer("День не найден в плане.", show_alert=True)
        return

    # Сохраняем информацию о выбранном дне для генерации после выбора длины
    await state.update_data(plan_day=day_num, plan_day_data=day)
    await state.set_state(ContentStates.waiting_for_post_length)

    text = (
        "📏 <b>Какой объем поста хотите получить?</b>\n\n"
        "⚡ <b>Короткий</b> — 400–600 символов, идеально для продающих постов и аносов\n\n"
        "✨ <b>Стандартный</b> — 700–1000 символов, подходит для большинства публикаций\n\n"
        "📖 <b>Развернутый</b> — 1000–1400 символов, для кейсов и глубоких историй"
    )

    await callback.message.answer(text, reply_markup=get_post_length_keyboard(), parse_mode="HTML")
    await callback.answer()


# --- ИСПРАВЛЕНО: removeprefix вместо split и двойная вложенность инлайн-кнопок ---
@dp.callback_query(F.data.startswith("type_"))
async def handle_text_type(callback: CallbackQuery, state: FSMContext) -> None:
    text_type = callback.data.removeprefix("type_")  # Защита от сложных названий callback

    # ПРАВИЛЬНО: Два уровня вложенности [ [Кнопка] ] вместо трех
    cancel_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена (В меню)", callback_data="back_to_main")]
        ]
    )

    if text_type == "plan":
        await state.set_state(ContentStates.waiting_for_plan_topic)
        text = (
            "🗓️ <b>Составление контент-плана на 7 дней</b>\n\n"
            "Напиши свою нишу и специализацию (например: <i>мастер маникюра, наращивание ресниц, топ-косметолог</i>).\n"
            "Если есть конкретная цель (например: <i>заполнить окошки на август или продвинуть новую услугу</i>) — тоже укажи это!"
        )
        await callback.message.answer(text, reply_markup=cancel_keyboard, parse_mode="HTML")
        await callback.answer()
        return

    await state.update_data(chosen_type=text_type)
    await state.set_state(ContentStates.waiting_for_post_length)

    text = (
        "📏 <b>Какой объем поста хотите получить?</b>\n\n"
        "⚡ <b>Короткий</b> — 400–600 символов, идеально для продающих постов и аносов\n\n"
        "✨ <b>Стандартный</b> — 700–1000 символов, подходит для большинства публикаций\n\n"
        "📖 <b>Развернутый</b> — 1000–1400 символов, для кейсов и глубоких историй"
    )

    await callback.message.answer(text, reply_markup=get_post_length_keyboard(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(ContentStates.waiting_for_post_length, F.data.startswith("length_"))
async def handle_post_length(callback: CallbackQuery, state: FSMContext) -> None:
    post_length = callback.data.removeprefix("length_")  # short, medium, long

    await state.update_data(post_length=post_length)

    user_data = await state.get_data()

    # Проверяем, генерируем ли мы пост из контент-плана
    if "plan_day" in user_data:
        # Генерация из контент-плана
        day_num = user_data.get("plan_day")
        day = user_data.get("plan_day_data")
        await state.clear()

        await callback.answer()
        status_message = await callback.message.answer(
            f"🤖 <i>Пишу пост для дня {day_num}...</i>",
            parse_mode="HTML",
        )

        try:
            profile = await get_profile(callback.from_user.id)
            try:
                history = await get_recent_generations(callback.from_user.id)
            except Exception:
                logger.exception("Не удалось получить историю генераций")
                history = []

            prompt = get_day_generation_prompt(day)
            generated_post = await call_beauty_ai(prompt, day.content_type, profile, history, post_length)
            await status_message.delete()

            await send_long_message(
                callback.message,
                generated_post,
                reply_markup=build_after_plan_post_keyboard(),
                parse_mode="HTML",
            )

            try:
                await save_generation(callback.from_user.id, day.content_type, day.title, generated_post)
            except Exception:
                logger.exception("Не удалось сохранить генерацию в историю")

            await mark_day_completed(callback.from_user.id, day_num)
        except Exception as e:
            logger.error(f"Ошибка при генерации поста из контент-плана (день {day_num}): {e}")
            await status_message.edit_text("❌ Не получилось сгенерировать пост. Попробуй ещё раз позже.")
    else:
        # Обычная генерация — переходим к вводу темы
        await state.set_state(ContentStates.waiting_for_topic)

        chosen_type = user_data.get("chosen_type", "selling")

        prompts = {
            "selling": "<i>Пример: акция на ресницы, свободные окошки на завтра...</i>",
            "expert": "<i>Пример: как ухаживать за бровями дома, топ-3 мифа...</i>",
            "personal": "<i>Пример: как я пришла в бьюти, мой самый забавный случай...</i>"
        }

        cancel_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена (В меню)", callback_data="back_to_main")]
            ]
        )

        text = (
            f"📝 <b>Отлично! Напиши кратко тему или тезисы для поста.</b>\n\n"
            f"{prompts.get(chosen_type, '')}\n\n"
            f"ИИ сгенерирует текст специально под этот формат!"
        )

        await callback.message.answer(text, reply_markup=cancel_keyboard, parse_mode="HTML")
        await callback.answer()


# ==================== ГЕНЕРАЦИЯ ЧЕРЕЗ AITUNNEL (OpenAI Compatible) ====================

async def call_beauty_ai(
    prompt_text: str, text_type: str, profile: dict | None = None, history: list[dict] | None = None, post_length: str = "medium"
) -> str:
    profile_prompt = build_profile_prompt(profile)
    history_prompt = build_history_prompt(history)
    system_prompt = get_system_prompt(post_length)

    if text_type == "plan":
        type_prompt = get_plan_prompt()
    elif text_type == "selling":
        type_prompt = get_selling_prompt(post_length=post_length)
    elif text_type == "expert":
        type_prompt = get_expert_prompt(post_length=post_length)
    else:  # personal
        type_prompt = get_personal_prompt(post_length=post_length)

    # Получаем prompt для длины поста (по умолчанию medium для совместимости)
    length_prompt = get_post_length_prompt(post_length)
    story_prompt = get_story_prompt(post_length)

    # Общее правило приоритета Prompt:
    # Каждый следующий Prompt может улучшать текст, но не имеет права нарушать ограничения предыдущих.
    # Если выбран режим Short — нельзя увеличивать объем текста.
    # Если выбран продающий пост — нельзя превращать его в экспертную статью.
    # Если выбран личный пост — нельзя превращать его в обучающий материал.
    # Если выбрана определенная длина — она имеет более высокий приоритет.

    # Новый порядок приоритета Prompt:
    # SYSTEM → PROFILE → HISTORY → TYPE → POST_LENGTH → STORY → CTA → HUMAN_STYLE → NATURAL_FLOW → EMOTION_BALANCE → ANTI_AI → HUMAN_EDITOR → FINAL_QUALITY → FORMATTING

    # Для контент-плана исключаем промпты, которые могут нарушить структуру (HUMAN_EDITOR, FINAL_QUALITY, POST_LENGTH)
    if text_type == "plan":
        system_instruction_text = (
            system_prompt + STRATEGY_PROMPT + profile_prompt + history_prompt + type_prompt + story_prompt + CTA_PROMPT + HUMAN_STYLE_PROMPT + NATURAL_FLOW_PROMPT + EMOTION_BALANCE_PROMPT + ANTI_AI_PROMPT + FORMATTING_PROMPT
        )
    elif post_length == "short":
        # Для режима Short исключаем STRATEGY_PROMPT (требует полноценную структуру) и CTA_PROMPT (необязательный)
        # Оставляем только prompt, совместимые с мини-публикациями
        system_instruction_text = (
            system_prompt + profile_prompt + history_prompt + type_prompt + length_prompt + story_prompt + HUMAN_STYLE_PROMPT + NATURAL_FLOW_PROMPT + EMOTION_BALANCE_PROMPT + ANTI_AI_PROMPT + HUMAN_EDITOR_PROMPT + FINAL_QUALITY_PROMPT + FORMATTING_PROMPT
        )
    else:
        # Для режимов Medium и Long используем полный набор prompt
        system_instruction_text = (
            system_prompt + STRATEGY_PROMPT + profile_prompt + history_prompt + type_prompt + length_prompt + story_prompt + CTA_PROMPT + HUMAN_STYLE_PROMPT + NATURAL_FLOW_PROMPT + EMOTION_BALANCE_PROMPT + ANTI_AI_PROMPT + HUMAN_EDITOR_PROMPT + FINAL_QUALITY_PROMPT + FORMATTING_PROMPT
        )

    async with ai_semaphore:
        try:
            response = await retry_with_backoff(
                ai_client.chat.completions.create,
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": system_instruction_text},
                    {"role": "user", "content": f"Запрос пользователя: {prompt_text}"}
                ],
                max_retries=3,
                base_delay=1.0,
                max_delay=8.0
            )
            text = response.choices[0].message.content
            text = sanitize_for_telegram_html(text)
            
            # Проверка длины (только для обычных постов, не для контент-плана)
            if text_type != "plan":
                is_valid, actual_length, hard_max = validate_length(text, post_length)
                
                logger.info(
                    f"Length check: post_length={post_length}, target_max={hard_max}, "
                    f"generated_length={actual_length}, is_valid={is_valid}"
                )
                
                # Если текст превышает лимит, запускаем editor-pass
                if not is_valid:
                    logger.info(f"Editor pass triggered: text too long ({actual_length} > {hard_max})")
                    
                    try:
                        text = await retry_with_backoff(
                            editor_pass,
                            text, post_length, ai_client, AI_MODEL,
                            max_retries=2,
                            base_delay=1.0,
                            max_delay=4.0
                        )
                        text = sanitize_for_telegram_html(text)
                        
                        # Повторная проверка после editor-pass
                        is_valid_after, actual_length_after, _ = validate_length(text, post_length)
                        logger.info(
                            f"After editor pass: length={actual_length_after}, is_valid={is_valid_after}"
                        )
                        
                        # Если всё ещё превышает лимит, используем fallback
                        if not is_valid_after:
                            logger.warning(f"Text still too long after editor pass, using fallback")
                            text = fallback_truncate(text, hard_max)
                            final_length = count_chars(text)
                            logger.info(f"After fallback: length={final_length}")
                            
                    except Exception as e:
                        logger.error(f"Editor pass failed: {e}, using fallback")
                        text = fallback_truncate(text, hard_max)
            
            return text
        except Exception as e:
            logger.error(f"Ошибка при генерации через AITunnel: {e}")
            raise Exception(f"Ошибка генерации: {e}")


# --- ИСПРАВЛЕНО: Валидация на наличие текста (защита от фото/стикеров) ---
# --- ЭТАП 1: подгружаем профиль перед генерацией ---
@dp.message(ContentStates.waiting_for_topic)
async def topic_received(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ <b>Пожалуйста, напишите тему текстом.</b> Фотографии, стикеры или голосовые сообщения пока не поддерживаются!", parse_mode="HTML")
        return

    user_topic = message.text
    user_data = await state.get_data()
    chosen_type = user_data.get("chosen_type", "selling")
    post_length = user_data.get("post_length", "medium")  # По умолчанию medium для совместимости
    await state.clear()

    status_message = await message.answer("🤖 <i>ИИ адаптирует стиль под выбранный формат... Пишу пост...</i>", parse_mode="HTML")

    try:
        profile = await get_profile(message.from_user.id)

        # ЭТАП 4: последние генерации пользователя как контекст
        try:
            history = await get_recent_generations(message.from_user.id)
        except Exception:
            logger.exception("Не удалось получить историю генераций")
            history = []

        generated_post = await call_beauty_ai(user_topic, chosen_type, profile, history, post_length)
        await status_message.delete()

        after_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="📝 Создать еще контент", callback_data="texts"),
                InlineKeyboardButton(text="↩️ В главное меню", callback_data="back_to_main")
            ]]
        )
        await send_long_message(message, generated_post, reply_markup=after_keyboard, parse_mode="HTML")

        # ЭТАП 4: автосохранение успешной генерации в историю
        try:
            await save_generation(message.from_user.id, chosen_type, user_topic, generated_post)
        except Exception:
            logger.exception("Не удалось сохранить генерацию в историю")
    except Exception as e:
        logger.error(f"Ошибка при генерации поста: {e}")
        await message.answer("❌ Произошла ошибка при генерации текста. Попробуй еще раз позже.")


# --- ИСПРАВЛЕНО: Валидация на наличие текста для контент-плана ---
# --- ЭТАП 1: подгружаем профиль перед генерацией ---
@dp.message(ContentStates.waiting_for_plan_topic)
async def plan_topic_received(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ <b>Пожалуйста, опишите вашу бьюти-нишу текстом.</b>", parse_mode="HTML")
        return

    user_topic = message.text
    await state.clear()

    status_message = await message.answer("🗓️ <i>Анализирую бьюти-нишу... Составляю убойный контент-план на 7 дней...</i>", parse_mode="HTML")

    try:
        profile = await get_profile(message.from_user.id)

        # ЭТАП 4: последние генерации пользователя как контекст
        try:
            history = await get_recent_generations(message.from_user.id)
        except Exception:
            logger.exception("Не удалось получить историю генераций")
            history = []

        generated_plan = await call_beauty_ai(user_topic, "plan", profile, history)
        logger.info("RAW CONTENT PLAN:\n%s", generated_plan)

        # Проверка наличия маркера "День 1" для валидации формата
        if "День 1" not in generated_plan and "Day 1" not in generated_plan:
            logger.warning("Ответ не содержит маркер 'День 1' или 'Day 1'. Выполняем повторную генерацию.")
            # Добавляем дополнительную инструкцию для повторной генерации
            retry_topic = user_topic + "\n\nВАЖНО: Предыдущий ответ не соответствовал обязательному формату. Повтори генерацию. Используй только формат: День 1, День 2, ..., День 7."
            generated_plan = await call_beauty_ai(retry_topic, "plan", profile, history)
            logger.info("RETRY RAW CONTENT PLAN:\n%s", generated_plan)

        await status_message.delete()

        try:
            plan = await create_content_plan(message.from_user.id, user_topic, generated_plan)
        except ValueError as exc:
            logger.error(f"Ошибка парсинга контент-плана: {exc}")
            await message.answer(
                "❌ План создан, но не удалось разобрать его на 7 дней. Попробуйте сгенерировать ещё раз.",
                parse_mode="HTML",
            )
            return

        await message.answer(
            format_plan_list(plan, created=True),
            reply_markup=build_plan_days_keyboard(),
            parse_mode="HTML",
        )

        # В «Мои посты» сохраняем компактный список, полный план — в content_plans
        try:
            await save_generation(
                message.from_user.id,
                "plan",
                user_topic,
                format_plan_list(plan),
            )
        except Exception:
            logger.exception("Не удалось сохранить контент-план в историю")
    except Exception as e:
        logger.error(f"Ошибка при генерации контент-плана: {e}")
        await message.answer("❌ Произошла ошибка при составлении контент-плана. Попробуй еще раз позже.")


async def main() -> None:
    session = AiohttpSession()
    if PROXY_URL:
        connector = ProxyConnector.from_url(
            PROXY_URL, rdns=True, ssl=ssl.create_default_context(cafile=certifi.where())
        )
        async def create_session() -> ClientSession:
            if session._session is None or session._session.closed:
                session._session = ClientSession(
                    connector=connector,
                    headers={USER_AGENT: f"{SERVER_SOFTWARE} aiogram/{__version__}"},
                )
                session._should_reset_connector = False
            return session._session
        session.create_session = create_session
        logger.info("Telegram-сессия настроена через SOCKS-прокси")

    bot = Bot(token=BOT_TOKEN, session=session)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())