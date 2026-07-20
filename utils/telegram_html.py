"""Приведение HTML из Gemini к тегам, поддерживаемым Telegram parse_mode=HTML."""

import re

# Telegram Bot API: b, strong, i, em, u, ins, s, strike, del, code, pre, a, tg-spoiler, span.tg-spoiler
_TELEGRAM_ALLOWED = frozenset({
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "a", "tg-spoiler",
})

_BLOCK_OPEN = re.compile(
    r"<(?:p|div|h[1-6]|section|article|header|footer|blockquote|table|thead|tbody|tr)(?:\s[^>]*)?>",
    re.IGNORECASE,
)
_BLOCK_CLOSE = re.compile(
    r"</(?:p|div|h[1-6]|section|article|header|footer|blockquote|table|thead|tbody|tr)>",
    re.IGNORECASE,
)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_ANY_TAG = re.compile(r"</?([^>\s/]+)(?:\s[^>]*)?>", re.IGNORECASE)


def _is_allowed_tag(full_tag: str, tag_name: str) -> bool:
    name = tag_name.lower()
    if name in _TELEGRAM_ALLOWED:
        return True
    if name == "span" and "tg-spoiler" in full_tag.lower():
        return True
    return False


def sanitize_for_telegram_html(text: str) -> str:
    """
    Убирает неподдерживаемые Telegram HTML-теги (<p>, <div>, <br> и т.д.),
    сохраняя <b>, <i>, <u>, <s>, <code>, <pre>, <a>, <tg-spoiler>.
    """
    text = _BR.sub("\n", text)
    text = _BLOCK_OPEN.sub("\n", text)
    text = _BLOCK_CLOSE.sub("\n", text)

    text = re.sub(r"<ul(?:\s[^>]*)?>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</ul>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<ol(?:\s[^>]*)?>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</ol>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li(?:\s[^>]*)?>", "• ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)

    def replace_tag(match: re.Match[str]) -> str:
        full = match.group(0)
        name = match.group(1)
        if _is_allowed_tag(full, name):
            return full
        return "" if full.startswith("</") else "\n"

    text = _ANY_TAG.sub(replace_tag, text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
