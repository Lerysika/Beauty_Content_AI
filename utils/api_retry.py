"""Утилиты для retry с exponential backoff для API-запросов."""

import asyncio
import logging
from typing import Callable, TypeVar

T = TypeVar('T')

logger = logging.getLogger(__name__)


# Временные ошибки, которые можно повторить
RETRYABLE_ERRORS = (
    TimeoutError,
    asyncio.TimeoutError,
)

# HTTP статусы для retry
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


async def retry_with_backoff(
    func: Callable[..., T],
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
    **kwargs
) -> T:
    """
    Выполняет функцию с retry и exponential backoff.
    
    Args:
        func: Функция для выполнения
        *args: Аргументы функции
        max_retries: Максимальное количество попыток
        base_delay: Базовая задержка в секундах
        max_delay: Максимальная задержка в секундах
        **kwargs: Именованные аргументы функции
    
    Returns:
        Результат функции
    
    Raises:
        Последнее исключение, если все попытки неудачны
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            # Проверяем, можно ли повторить запрос
            if not _is_retryable_error(e):
                logger.error(f"Non-retryable error: {e}")
                raise
            
            if attempt < max_retries:
                # Exponential backoff
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    f"Retryable error (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"Max retries ({max_retries}) exceeded. Last error: {e}")
    
    raise last_exception


def _is_retryable_error(error: Exception) -> bool:
    """
    Проверяет, является ли ошибка повторяемой.
    
    Args:
        error: Исключение
    
    Returns:
        True, если ошибку можно повторить
    """
    # Проверяем тип ошибки
    if isinstance(error, RETRYABLE_ERRORS):
        return True
    
    # Проверяем HTTP статус (если есть)
    if hasattr(error, 'status'):
        return error.status in RETRYABLE_STATUS_CODES
    
    # Проверяем атрибут status_code (для некоторых библиотек)
    if hasattr(error, 'status_code'):
        return error.status_code in RETRYABLE_STATUS_CODES
    
    return False
