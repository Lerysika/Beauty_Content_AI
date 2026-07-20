# --- ЭТАП 4: HISTORY-блок системного промпта ---
# Модуль не ходит в базу сам — принимает уже полученный список
# последних генераций (services.generation_history.get_recent_generations)
# и превращает его в текстовый контекст для Gemini.

CONTENT_TYPE_LABELS = {
    "selling": "продающий",
    "expert": "экспертный",
    "personal": "личная история",
    "plan": "контент-план",
}

SUMMARY_LENGTH = 250


def _summarize(generated_text: str, length: int = SUMMARY_LENGTH) -> str:
    """Краткое содержание текста для контекста истории — не полный текст."""
    clean = " ".join((generated_text or "").split())
    if len(clean) <= length:
        return clean
    return clean[:length].rstrip() + "…"


def build_history_prompt(history: list[dict] | None) -> str:
    """
    Формирует блок HISTORY для системного промпта.

    Если истории нет — возвращает пустую строку, блок автоматически пропускается.
    """
    if not history:
        return ""

    items = []
    for i, item in enumerate(history, start=1):
        label = CONTENT_TYPE_LABELS.get(item.get("content_type"), item.get("content_type") or "—")
        topic = item.get("topic") or "—"
        summary = _summarize(item.get("generated_text", ""))
        items.append(f"{i}.\nТип: {label}\n\nТема:\n{topic}\n\nКраткое содержание:\n{summary}")

    history_block = "\n\n---\n\n".join(items)

    return (
        "\n\nНедавние публикации пользователя:\n\n"
        f"{history_block}\n\n---\n\n"
        "Используй эту информацию.\n\n"
        "Не повторяй темы.\n\n"
        "Не используй одинаковые хуки.\n\n"
        "Не используй одинаковые примеры.\n\n"
        "Если пользователь просит написать материал на похожую тему — "
        "найди новый угол раскрытия.\n\n"
        "Сделай публикацию уникальной.\n\n"
    )
