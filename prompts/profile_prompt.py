def build_profile_prompt(profile: dict | None) -> str:
    """Формирует блок с информацией о мастере для системного промпта.

    Если профиль не заполнен (None или без значимых полей) — возвращает
    пустую строку, чтобы не засорять промпт пустыми полями.
    """
    if not profile:
        return ""

    specialization = profile.get("specialization")
    name = profile.get("name")
    experience = profile.get("experience")
    avg_check = profile.get("avg_check")
    services_to_promote = profile.get("services_to_promote")

    if not any([specialization, name, experience, avg_check, services_to_promote]):
        return ""

    return f"""Информация о мастере

Специализация:
{specialization or '-'}

Имя:
{name or '-'}

Опыт:
{experience or '-'}

Средний чек:
{avg_check or '-'}

Услуги, которые необходимо продвигать:
{services_to_promote or '-'}

При написании текста обязательно учитывай эту информацию.

Не пиши универсальный текст.

Пиши так, будто этот мастер сам рассказал тебе о себе.

"""
