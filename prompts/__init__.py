"""Пакет с промптами для генерации бьюти-контента.

Каждый файл отвечает только за свой блок промпта:

- system_prompt.py     — базовая роль, стиль и запрещённые AI-фразы (SYSTEM_PROMPT)
- strategy_prompt.py   — стратегия работы с клиентом (STRATEGY_PROMPT)
- formatting_prompt.py — техническое требование HTML-разметки для Telegram (FORMATTING_PROMPT)
- profile_prompt.py    — контекст профиля мастера (build_profile_prompt)
- selling_prompt.py    — продающий пост (get_selling_prompt)
- expert_prompt.py     — экспертный пост (get_expert_prompt)
- personal_prompt.py   — личный пост (get_personal_prompt)
- plan_prompt.py       — контент-план на 7 дней (get_plan_prompt)
- cta_prompt.py        — разнообразие CTA окончаний постов (CTA_PROMPT)
- anti_ai_prompt.py    — самопроверка на "AI-шность" (ANTI_AI_PROMPT)

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
    "ANTI_AI_PROMPT",
]
