"""Сервис для editor-pass — сокращения текста при превышении лимита длины."""

from openai import AsyncOpenAI
from utils.length_validator import get_length_limits, count_chars


EDITOR_PROMPT = """Ты — редактор, который сокращает текст.

Твоя задача:
сократить существующий текст, не создавая новый.

ЗАПРЕЩЕНО:
• добавлять новые идеи
• добавлять новые факты
• добавлять новую историю
• добавлять CTA
• изменять смысл
• увеличивать текст

РАЗРЕШЕНО:
• удалять воду
• удалять повторы
• объединять предложения
• сокращать формулировки
• удалять второстепенные детали

Цель — сократить текст до указанного лимита, сохранив основной смысл.

Верни только сокращённый текст, без комментариев."""


async def editor_pass(
    text: str,
    post_length: str,
    ai_client: AsyncOpenAI,
    ai_model: str
) -> str:
    """
    Запускает editor-pass для сокращения текста.
    
    Args:
        text: Исходный текст с HTML-разметкой
        post_length: Режим длины (short, medium, long)
        ai_client: AI клиент
        ai_model: Название модели
    
    Returns:
        Сокращённый текст
    """
    _, _, hard_max = get_length_limits(post_length)
    actual_length = count_chars(text)
    
    # Формируем запрос к AI
    user_message = f"""Сократи этот текст до {hard_max} символов (без HTML-тегов).

Текст:
{text}

Цель: {hard_max} символов.
Текущая длина: {actual_length} символов."""
    
    try:
        response = await ai_client.chat.completions.create(
            model=ai_model,
            messages=[
                {"role": "system", "content": EDITOR_PROMPT},
                {"role": "user", "content": user_message}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        raise Exception(f"Ошибка editor-pass: {e}")
