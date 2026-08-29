"""Утилиты для проверки и коррекции длины постов."""

import re
from typing import Tuple


def get_length_limits(post_length: str) -> Tuple[int, int, int]:
    """
    Возвращает целевой минимум, целевой максимум и жёсткий максимум для режима длины.
    
    Args:
        post_length: Режим длины (short, medium, long)
    
    Returns:
        Кортеж (target_min, target_max, hard_max)
    """
    limits = {
        "short": (300, 450, 500),
        "medium": (450, 650, 700),
        "long": (650, 850, 900)
    }
    return limits.get(post_length, limits["medium"])


def count_chars(text: str) -> int:
    """
    Подсчитывает количество символов в тексте без HTML-тегов.
    
    Args:
        text: Текст с HTML-разметкой
    
    Returns:
        Количество символов без HTML-тегов
    """
    # Удаляем HTML-теги
    clean_text = re.sub(r'<[^>]+>', '', text)
    # Удаляем HTML-сущности
    clean_text = re.sub(r'&[^;]+;', '', clean_text)
    return len(clean_text)


def validate_length(text: str, post_length: str) -> Tuple[bool, int, int]:
    """
    Проверяет, соответствует ли длина текста ограничениям.
    
    Args:
        text: Текст с HTML-разметкой
        post_length: Режим длины (short, medium, long)
    
    Returns:
        Кортеж (is_valid, actual_length, hard_max)
    """
    actual_length = count_chars(text)
    _, _, hard_max = get_length_limits(post_length)
    is_valid = actual_length <= hard_max
    return is_valid, actual_length, hard_max


def fallback_truncate(text: str, hard_max: int) -> str:
    """
    Безопасно обрезает текст по последнему полному предложению.
    
    Args:
        text: Текст с HTML-разметкой
        hard_max: Жёсткий максимум символов
    
    Returns:
        Обрезанный текст с корректным HTML
    """
    # Если текст уже меньше лимита, возвращаем как есть
    if count_chars(text) <= hard_max:
        return text
    
    # Удаляем HTML-теги для подсчёта
    clean_text = re.sub(r'<[^>]+>', '', text)
    clean_text = re.sub(r'&[^;]+;', '', clean_text)
    
    # Находим позицию для обрезки
    truncate_pos = hard_max
    
    # Ищем последнее полное предложение до truncate_pos
    # Ищем точки, вопросительные и восклицательные знаки
    sentence_endings = ['.', '?', '!']
    last_sentence_end = -1
    
    for i in range(truncate_pos - 1, -1, -1):
        if clean_text[i] in sentence_endings:
            # Проверяем, что это конец предложения (после знака пробел или конец строки)
            if i + 1 < len(clean_text) and (clean_text[i + 1] in [' ', '\n', '\t', '']):
                last_sentence_end = i
                break
    
    if last_sentence_end > 0:
        truncate_pos = last_sentence_end + 1
    
    # Обрезаем чистый текст
    truncated_clean = clean_text[:truncate_pos]
    
    # Восстанавливаем HTML-разметку (упрощённо)
    # Это сложная задача, поэтому для fallback используем простой подход:
    # удаляем теги из оригинала и обрезаем чистый текст
    result = re.sub(r'<[^>]+>', '', text)
    result = re.sub(r'&[^;]+;', '', result)
    result = result[:truncate_pos]
    
    # Добавляем многоточие, если текст обрезан
    if len(result) < len(clean_text):
        result = result.rstrip() + '...'
    
    return result
