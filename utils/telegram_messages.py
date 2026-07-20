"""Безопасная отправка длинных HTML-сообщений в Telegram (лимит 4096 символов)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup, Message

TELEGRAM_MAX_LENGTH = 4096
TELEGRAM_SAFE_LIMIT = 3800

_TAG_PATTERN = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)(?:\s[^>]*)?(/?)>")
_SELF_CLOSING = frozenset({"br"})


def _tag_name(opening_tag: str) -> str:
    match = re.match(r"<(\w+)", opening_tag, re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _is_inside_html_tag(text: str, pos: int) -> bool:
    last_lt = text.rfind("<", 0, pos)
    last_gt = text.rfind(">", 0, pos)
    return last_lt > last_gt


def _get_open_tags(text: str) -> list[str]:
    stack: list[str] = []
    for match in _TAG_PATTERN.finditer(text):
        full_tag = match.group(0)
        is_close = match.group(1) == "/"
        is_self_close = match.group(3) == "/" or full_tag.endswith("/>")
        name = match.group(2).lower()

        if is_self_close or name in _SELF_CLOSING:
            continue
        if is_close:
            for i in range(len(stack) - 1, -1, -1):
                if _tag_name(stack[i]) == name:
                    stack = stack[:i]
                    break
        else:
            stack.append(full_tag)
    return stack


def _close_open_tags(text: str) -> tuple[str, list[str]]:
    open_tags = _get_open_tags(text)
    if not open_tags:
        return text, []
    closers = "".join(f"</{_tag_name(tag)}>" for tag in reversed(open_tags))
    return text + closers, open_tags


def _find_split_index(text: str, max_length: int) -> int:
    if len(text) <= max_length:
        return len(text)

    def try_separator(separator: str, advance: int) -> int | None:
        search_end = max_length
        while search_end > 0:
            pos = text.rfind(separator, 0, search_end)
            if pos <= 0:
                return None
            split_at = pos + advance
            if split_at <= max_length and not _is_inside_html_tag(text, split_at):
                return split_at
            search_end = pos
        return None

    split_at = try_separator("\n\n", 2)
    if split_at:
        return split_at

    split_at = try_separator("\n", 1)
    if split_at:
        return split_at

    pos = max_length
    while pos > 0 and _is_inside_html_tag(text, pos):
        pos -= 1
    return pos if pos > 0 else max_length


def split_html_text(text: str, max_length: int = TELEGRAM_SAFE_LIMIT) -> list[str]:
    """
    Разбивает HTML-текст на части не длиннее max_length.
    Разрыв по \\n\\n, затем по \\n; HTML-теги не разрываются — открытые теги закрываются
    в конце части и восстанавливаются в начале следующей.
    """
    text = text.strip()
    if not text:
        return [""]
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remainder = text
    prev_remainder_len = len(remainder) + 1

    while remainder:
        if len(remainder) <= max_length:
            closed, _ = _close_open_tags(remainder)
            chunks.append(closed)
            break

        split_at = _find_split_index(remainder, max_length)
        if split_at <= 0:
            split_at = min(max_length, len(remainder))

        part = remainder[:split_at]
        closed_part, open_tags = _close_open_tags(part)
        chunks.append(closed_part)

        remainder = "".join(open_tags) + remainder[split_at:]
        remainder = remainder.lstrip("\n")

        if len(remainder) >= prev_remainder_len:
            # защита от бесконечного цикла
            closed, _ = _close_open_tags(remainder[:max_length])
            chunks.append(closed)
            remainder = remainder[max_length:]
            if not remainder:
                break
        prev_remainder_len = len(remainder)

    return chunks


async def send_long_message(
    message: Message,
    text: str,
    *,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
    max_length: int = TELEGRAM_SAFE_LIMIT,
) -> list[Message]:
    """Отправляет текст одним или несколькими сообщениями. Клавиатура — только к последнему."""
    parts = split_html_text(text, max_length=max_length)
    sent: list[Message] = []

    for index, part in enumerate(parts):
        kwargs: dict = {"parse_mode": parse_mode}
        if index == len(parts) - 1 and reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        sent.append(await message.answer(part, **kwargs))

    return sent


async def send_long_text(
    message: Message,
    text: str,
    *,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
    max_length: int = TELEGRAM_SAFE_LIMIT,
    edit: bool = False,
) -> None:
    """
    Отправляет длинный текст. Если edit=True — первая часть через edit_text,
    остальные через answer (удобно для callback-сообщений).
    """
    parts = split_html_text(text, max_length=max_length)
    if not parts:
        return

    if edit:
        await message.edit_text(
            parts[0],
            parse_mode=parse_mode,
            reply_markup=reply_markup if len(parts) == 1 else None,
        )
        for index, part in enumerate(parts[1:], start=1):
            await message.answer(
                part,
                parse_mode=parse_mode,
                reply_markup=reply_markup if index == len(parts) - 1 else None,
            )
        return

    await send_long_message(
        message,
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        max_length=max_length,
    )
