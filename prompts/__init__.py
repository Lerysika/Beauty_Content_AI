"""Пакет с промптами для генерации бьюти-контента.

Каждый файл отвечает только за свой блок промпта:

- system_prompt.py        — базовая роль, стиль и запрещённые AI-фразы (SYSTEM_PROMPT)
- strategy_prompt.py      — стратегия работы с клиентом (STRATEGY_PROMPT)
- formatting_prompt.py    — техническое требование HTML-разметки для Telegram (FORMATTING_PROMPT)
- profile_prompt.py       — контекст профиля мастера (build_profile_prompt)
- selling_prompt.py       — продающий пост (get_selling_prompt)
- expert_prompt.py        — экспертный пост (get_expert_prompt)
- personal_prompt.py      — личный пост (get_personal_prompt)
- plan_prompt.py          — контент-план на 7 дней (get_plan_prompt)
- cta_prompt.py           — разнообразие CTA окончаний постов (CTA_PROMPT)
- story_prompt.py         — разнообразие сюжетов историй (STORY_PROMPT)
- natural_flow_prompt.py  — естественный ритм текста (NATURAL_FLOW_PROMPT)
- emotion_balance_prompt.py — эмоциональный баланс (EMOTION_BALANCE_PROMPT)
- human_style_prompt.py   — разговорный стиль речи (HUMAN_STYLE_PROMPT)
- human_editor_prompt.py  — редактор с минимальными исправлениями (HUMAN_EDITOR_PROMPT)
- final_quality_prompt.py — финальный контроль качества (FINAL_QUALITY_PROMPT)
- anti_ai_prompt.py       — обнаружение AI-клише (ANTI_AI_PROMPT)

formatting_prompt.py не было в исходном ТЗ, но без него модель может начать
возвращать markdown вместо HTML-тегов и ломать отправку сообщений в Telegram
(бот использует parse_mode="HTML").
"""

from .system_prompt import SYSTEM_PROMPT
from .strategy_prompt import STRATEGY_PROMPT
from .formatting_prompt import FORMATTING_PROMPT
from .profile_prompt import build_profile_prompt
from .selling_prompt import get_selling_prompt
from .expert_prompt import get_expert_prompt
from .personal_prompt import get_personal_prompt
from .plan_prompt import get_plan_prompt
from .cta_prompt import CTA_PROMPT
from .story_prompt import STORY_PROMPT
from .natural_flow_prompt import NATURAL_FLOW_PROMPT
from .emotion_balance_prompt import EMOTION_BALANCE_PROMPT
from .human_style_prompt import HUMAN_STYLE_PROMPT
from .human_editor_prompt import HUMAN_EDITOR_PROMPT
from .final_quality_prompt import FINAL_QUALITY_PROMPT
from .anti_ai_prompt import ANTI_AI_PROMPT

__all__ = [
    "SYSTEM_PROMPT",
    "STRATEGY_PROMPT",
    "FORMATTING_PROMPT",
    "build_profile_prompt",
    "get_selling_prompt",
    "get_expert_prompt",
    "get_personal_prompt",
    "get_plan_prompt",
    "CTA_PROMPT",
    "STORY_PROMPT",
    "NATURAL_FLOW_PROMPT",
    "EMOTION_BALANCE_PROMPT",
    "HUMAN_STYLE_PROMPT",
    "HUMAN_EDITOR_PROMPT",
    "FINAL_QUALITY_PROMPT",
    "ANTI_AI_PROMPT",
]
