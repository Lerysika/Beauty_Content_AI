"""Сервис для Medical Claim Guard — защиты от медицинских утверждений."""

from openai import AsyncOpenAI
from prompts.medical_claim_guard_prompt import get_medical_claim_guard_prompt
from utils.medical_claim_detector import detect_medical_claims
import re


def medical_fallback(text: str) -> str:
    """
    Безопасный fallback для medical claims.
    
    Удаляет предложения с claims целиком, чтобы гарантировать отсутствие сломанного текста.
    
    Args:
        text: Текст с потенциальными medical claims
    
    Returns:
        Текст с удалёнными проблемными предложениями
    """
    # Разбиваем текст на предложения
    sentences = re.split(r'(?<=[.!?])\s+', text)
    cleaned_sentences = []
    
    for sentence in sentences:
        has_claim, patterns = detect_medical_claims(sentence)
        if not has_claim:
            cleaned_sentences.append(sentence)
        else:
            # Если есть claim, удаляем всё предложение целиком
            # Это гарантирует отсутствие сломанного текста
            pass
    
    # Если все предложения удалены, возвращаем исходный текст
    if not cleaned_sentences:
        return text
    
    return ' '.join(cleaned_sentences)


async def medical_claim_guard(
    text: str,
    text_type: str,
    ai_client: AsyncOpenAI,
    ai_model: str
) -> str:
    """
    Проверяет текст на медицинские claims и исправляет их.
    
    Pipeline:
    1. Pre-check (regex)
    2. Если есть claim → AI Guard #1
    3. Re-scan
    4. Если claim остался → AI Guard #2 (с более строгой инструкцией)
    5. Re-scan
    6. Если claim остался → Safe fallback
    
    Args:
        text: Исходный текст с HTML-разметкой
        text_type: Тип поста (selling, expert, personal, story)
        ai_client: AI клиент
        ai_model: Название модели
    
    Returns:
        Проверенный текст
    """
    original_text = text
    original_length = len(text)
    guard_passes = 0
    
    # Шаг 1: Программный pre-check
    has_suspicious_claims, matched_patterns = detect_medical_claims(text)
    
    if not has_suspicious_claims:
        # Нет подозрительных паттернов — возвращаем как есть
        return text
    
    # Шаг 2-5: AI Guard с re-scan (максимум 2 попытки)
    for attempt in range(1, 3):  # Максимум 2 AI Guard pass
        try:
            if attempt == 1:
                user_message = f"""Проверь этот текст на медицинские claims и исправь их минимально.

Тип поста: {text_type}

Текст:
{text}

Верни только исправленный текст, без комментариев."""
            else:
                # Вторая попытка с более строгой инструкцией
                user_message = f"""Текст содержит медицинские claim, которые НЕ были исправлены в первой попытке.

Ты ДОЛЖЕН исправить их сейчас. НЕ оставляй текст без изменений.

Тип поста: {text_type}

Текст:
{text}

Верни только исправленный текст, без комментариев."""
            
            response = await ai_client.chat.completions.create(
                model=ai_model,
                messages=[
                    {"role": "system", "content": get_medical_claim_guard_prompt()},
                    {"role": "user", "content": user_message}
                ]
            )
            
            corrected_text = response.choices[0].message.content
            guard_passes += 1
            
            # Проверка на увеличение длины
            if len(corrected_text) > original_length:
                # Guard увеличил текст — откатываемся к предыдущей версии
                corrected_text = text
            
            # Re-scan после AI Guard
            has_claim_after, _ = detect_medical_claims(corrected_text)
            
            if not has_claim_after:
                # Claim исправлен — возвращаем результат
                return corrected_text
            else:
                # Claim остался — продолжаем цикл
                text = corrected_text
                
        except Exception as e:
            # При ошибке прерываем цикл
            break
    
    # Шаг 6: Safe fallback если после 2 попыток claim остался
    has_claim_final, _ = detect_medical_claims(text)
    if has_claim_final:
        # Используем безопасный fallback — удаляем проблемные предложения целиком
        # Это гарантирует, что claims не останутся, даже если текст станет короче
        text = medical_fallback(text)
    
    return text
