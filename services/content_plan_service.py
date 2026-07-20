import logging
import os
import re
from dataclasses import asdict, dataclass
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

from utils.telegram_html import sanitize_for_telegram_html

load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

DAY_NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]

TYPE_DISPLAY = {
    "expert": "💡 Экспертный",
    "personal": "👤 Личный",
    "selling": "💎 Продающий",
}

TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "expert": ("эксперт", "полезн", "expert", "образователь"),
    "personal": ("личн", "истори", "personal", "история"),
    "selling": ("прода", "selling", "продающ", "реклам", "запис"),
}

# In-memory кэш (дублирует БД; работает, если таблица ещё не создана)
_plans_cache: dict[int, "ContentPlan"] = {}


@dataclass
class PlanDay:
    day: int
    title: str
    content_type: str
    full_text: str
    completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanDay:
        return cls(
            day=int(data["day"]),
            title=str(data.get("title") or ""),
            content_type=str(data.get("content_type") or "expert"),
            full_text=str(data.get("full_text") or ""),
            completed=bool(data.get("completed")),
        )


@dataclass
class ContentPlan:
    telegram_id: int
    niche_topic: str
    full_text: str
    days: list[PlanDay]

    def get_day(self, day_num: int) -> PlanDay | None:
        for item in self.days:
            if item.day == day_num:
                return item
        return None

    def to_storage(self) -> dict[str, Any]:
        return {
            "telegram_id": self.telegram_id,
            "niche_topic": self.niche_topic,
            "full_text": self.full_text,
            "days_json": [day.to_dict() for day in self.days],
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ContentPlan:
        days = [PlanDay.from_dict(item) for item in (row.get("days_json") or [])]
        return cls(
            telegram_id=int(row["telegram_id"]),
            niche_topic=str(row.get("niche_topic") or ""),
            full_text=str(row.get("full_text") or ""),
            days=days,
        )


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _extract_title(block: str) -> str:
    patterns = (
        r"(?:Название\s+темы|Тема\s+публикации|Тема|Topic)\s*:?\s*(.+?)(?:\n|$)",
        r"^\s*[-•]\s*(?:Название\s+темы|Тема)\s*:?\s*(.+?)(?:\n|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, block, re.IGNORECASE | re.MULTILINE)
        if match:
            title = _strip_html(match.group(1).strip())
            if title:
                return title[:220]

    for line in block.splitlines():
        clean = _strip_html(line.strip())
        if not clean:
            continue
        if re.match(r"^(?:Тип|Type|Главная\s+цель|Цель|Краткое|Почему|Описание)\b", clean, re.I):
            continue
        if re.match(r"^(?:День|Day)\s*\d", clean, re.I):
            continue
        return clean[:220]

    return "Тема дня"


def _extract_content_type(block: str) -> str:
    match = re.search(
        r"(?:Тип\s+публикации|Type|Формат)\s*:?\s*(.+?)(?:\n|$)",
        block,
        re.IGNORECASE,
    )
    probe = (match.group(1) if match else block).lower()
    for content_type, keywords in TYPE_KEYWORDS.items():
        if any(keyword in probe for keyword in keywords):
            return content_type
    return "expert"


def parse_content_plan(full_text: str) -> list[PlanDay]:
    """Извлекает 7 дней из полного ответа Gemini."""
    text = sanitize_for_telegram_html(full_text)

    day_pattern = re.compile(
        r"(?:^|\n)\s*(?:<b>\s*)?(?:День|Day)\s*(\d)\s*[\.:\)\-]?(?:\s*</b>)?",
        re.IGNORECASE,
    )
    matches = list(day_pattern.finditer(text))

    if len(matches) < 7:
        fallback_pattern = re.compile(r"(?:^|\n)\s*(\d)\s*[\.)\]:]\s+", re.MULTILINE)
        matches = list(fallback_pattern.finditer(text))

    if not matches:
        raise ValueError("Не удалось распознать дни в контент-плане")

    days: list[PlanDay] = []
    for index, match in enumerate(matches[:7]):
        day_num = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if not block:
            continue

        days.append(
            PlanDay(
                day=day_num,
                title=_extract_title(block),
                content_type=_extract_content_type(block),
                full_text=block,
                completed=False,
            )
        )

    if len(days) < 7:
        raise ValueError(f"Распознано только {len(days)} из 7 дней")

    days.sort(key=lambda item: item.day)
    normalized: list[PlanDay] = []
    for index, day in enumerate(days[:7], start=1):
        normalized.append(
            PlanDay(
                day=index,
                title=day.title,
                content_type=day.content_type,
                full_text=day.full_text,
                completed=False,
            )
        )
    return normalized


def format_plan_list(plan: ContentPlan, *, created: bool = False) -> str:
    header = "📅 <b>Контент-план создан</b>\n" if created else "📅 <b>Контент-план на неделю</b>\n"
    lines = [header]

    for day in plan.days:
        type_label = TYPE_DISPLAY.get(day.content_type, TYPE_DISPLAY["expert"])
        if day.completed:
            prefix = f"✅ {day.day}."
        else:
            prefix = DAY_NUMBER_EMOJIS[day.day - 1]
        lines.append(f"{prefix} {day.title}\n{type_label}")

    return "\n\n".join(lines)


def build_plan_days_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=DAY_NUMBER_EMOJIS[0], callback_data="plan_day_1"),
                InlineKeyboardButton(text=DAY_NUMBER_EMOJIS[1], callback_data="plan_day_2"),
                InlineKeyboardButton(text=DAY_NUMBER_EMOJIS[2], callback_data="plan_day_3"),
                InlineKeyboardButton(text=DAY_NUMBER_EMOJIS[3], callback_data="plan_day_4"),
            ],
            [
                InlineKeyboardButton(text=DAY_NUMBER_EMOJIS[4], callback_data="plan_day_5"),
                InlineKeyboardButton(text=DAY_NUMBER_EMOJIS[5], callback_data="plan_day_6"),
                InlineKeyboardButton(text=DAY_NUMBER_EMOJIS[6], callback_data="plan_day_7"),
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")],
        ]
    )


def build_no_plan_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Создать контент-план", callback_data="type_plan")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")],
        ]
    )


def build_after_plan_post_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 К контент-плану", callback_data="view_content_plan")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")],
        ]
    )


async def save_content_plan(plan: ContentPlan) -> None:
    _plans_cache[plan.telegram_id] = plan
    try:
        supabase.table("content_plans").upsert(plan.to_storage(), on_conflict="telegram_id").execute()
    except Exception:
        logger.exception("Не удалось сохранить контент-план в БД — используется память процесса")


async def get_content_plan(telegram_id: int) -> ContentPlan | None:
    if telegram_id in _plans_cache:
        return _plans_cache[telegram_id]

    try:
        result = (
            supabase.table("content_plans")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )
        if result.data:
            plan = ContentPlan.from_row(result.data[0])
            _plans_cache[telegram_id] = plan
            return plan
    except Exception:
        logger.exception("Не удалось загрузить контент-план из БД")

    return _plans_cache.get(telegram_id)


async def create_content_plan(telegram_id: int, niche_topic: str, full_text: str) -> ContentPlan:
    days = parse_content_plan(full_text)
    plan = ContentPlan(
        telegram_id=telegram_id,
        niche_topic=niche_topic,
        full_text=full_text,
        days=days,
    )
    await save_content_plan(plan)
    return plan


async def mark_day_completed(telegram_id: int, day_num: int) -> ContentPlan | None:
    plan = await get_content_plan(telegram_id)
    if not plan:
        return None

    for day in plan.days:
        if day.day == day_num:
            day.completed = True
            break

    await save_content_plan(plan)
    return plan


def get_day_generation_prompt(day: PlanDay) -> str:
    """Текст для генерации поста по выбранному дню."""
    return (
        f"Сгенерируй готовый пост по этому дню контент-плана.\n\n"
        f"Тема: {day.title}\n\n"
        f"Материалы и описание дня из плана:\n{day.full_text}"
    )
