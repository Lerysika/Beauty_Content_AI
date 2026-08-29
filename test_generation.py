"""Тестовый скрипт для проверки генерации постов."""

import asyncio
import os
import sys
from datetime import datetime
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Добавляем корневую директорию в path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prompts import (
    STRATEGY_PROMPT,
    FORMATTING_PROMPT,
    CTA_PROMPT,
    NATURAL_FLOW_PROMPT,
    EMOTION_BALANCE_PROMPT,
    HUMAN_STYLE_PROMPT,
    HUMAN_EDITOR_PROMPT,
    FINAL_QUALITY_PROMPT,
    ANTI_AI_PROMPT,
    build_profile_prompt,
    get_selling_prompt,
    get_expert_prompt,
    get_personal_prompt,
    get_plan_prompt,
    get_system_prompt,
    get_story_prompt,
)
from prompts.post_length_prompt import get_post_length_prompt
from prompts.history_prompt import build_history_prompt
from utils.telegram_html import sanitize_for_telegram_html
from utils.length_validator import get_length_limits, count_chars, validate_length, fallback_truncate
from utils.api_retry import retry_with_backoff
from services.editor_service import editor_pass

load_dotenv()

AI_API_KEY = os.getenv("AI_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.aitunnel.ru/v1")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.5-flash")

ai_client = AsyncOpenAI(
    api_key=AI_API_KEY,
    base_url=AI_BASE_URL,
)


async def call_beauty_ai(
    prompt_text: str, text_type: str, profile: dict | None = None, history: list[dict] | None = None, post_length: str = "medium"
) -> dict:
    """Генерация поста с метриками."""
    profile_prompt = build_profile_prompt(profile)
    history_prompt = build_history_prompt(history)
    system_prompt = get_system_prompt(post_length)

    if text_type == "plan":
        type_prompt = get_plan_prompt()
    elif text_type == "selling":
        type_prompt = get_selling_prompt(post_length=post_length)
    elif text_type == "expert":
        type_prompt = get_expert_prompt(post_length=post_length)
    else:  # personal
        type_prompt = get_personal_prompt(post_length=post_length)

    length_prompt = get_post_length_prompt(post_length)
    story_prompt = get_story_prompt(post_length)

    if text_type == "plan":
        system_instruction_text = (
            system_prompt + STRATEGY_PROMPT + profile_prompt + history_prompt + type_prompt + story_prompt + CTA_PROMPT + HUMAN_STYLE_PROMPT + NATURAL_FLOW_PROMPT + EMOTION_BALANCE_PROMPT + ANTI_AI_PROMPT + FORMATTING_PROMPT
        )
    elif post_length == "short":
        system_instruction_text = (
            system_prompt + profile_prompt + history_prompt + type_prompt + length_prompt + story_prompt + HUMAN_STYLE_PROMPT + NATURAL_FLOW_PROMPT + EMOTION_BALANCE_PROMPT + ANTI_AI_PROMPT + HUMAN_EDITOR_PROMPT + FINAL_QUALITY_PROMPT + FORMATTING_PROMPT
        )
    else:
        system_instruction_text = (
            system_prompt + STRATEGY_PROMPT + profile_prompt + history_prompt + type_prompt + length_prompt + story_prompt + CTA_PROMPT + HUMAN_STYLE_PROMPT + NATURAL_FLOW_PROMPT + EMOTION_BALANCE_PROMPT + ANTI_AI_PROMPT + HUMAN_EDITOR_PROMPT + FINAL_QUALITY_PROMPT + FORMATTING_PROMPT
        )

    metrics = {
        "mode": post_length,
        "type": text_type,
        "topic": prompt_text,
        "api_calls": 0,
        "editor_pass": False,
        "fallback": False,
        "initial_length": 0,
        "final_length": 0,
        "target_max": 0,
        "is_valid": False,
        "error": None
    }

    try:
        metrics["api_calls"] += 1
        response = await retry_with_backoff(
            ai_client.chat.completions.create,
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": system_instruction_text},
                {"role": "user", "content": f"Запрос пользователя: {prompt_text}"}
            ],
            max_retries=3,
            base_delay=1.0,
            max_delay=8.0
        )
        text = response.choices[0].message.content
        text = sanitize_for_telegram_html(text)
        
        metrics["initial_length"] = count_chars(text)
        _, _, metrics["target_max"] = get_length_limits(post_length)
        
        if text_type != "plan":
            is_valid, actual_length, hard_max = validate_length(text, post_length)
            metrics["is_valid"] = is_valid
            metrics["final_length"] = actual_length
            
            if not is_valid:
                try:
                    metrics["api_calls"] += 1
                    metrics["editor_pass"] = True
                    text = await retry_with_backoff(
                        editor_pass,
                        text, post_length, ai_client, AI_MODEL,
                        max_retries=2,
                        base_delay=1.0,
                        max_delay=4.0
                    )
                    text = sanitize_for_telegram_html(text)
                    
                    is_valid_after, actual_length_after, _ = validate_length(text, post_length)
                    metrics["final_length"] = actual_length_after
                    metrics["is_valid"] = is_valid_after
                    
                    if not is_valid_after:
                        metrics["fallback"] = True
                        text = fallback_truncate(text, hard_max)
                        metrics["final_length"] = count_chars(text)
                        metrics["is_valid"] = True
                        
                except Exception as e:
                    metrics["error"] = f"Editor pass failed: {e}"
                    metrics["fallback"] = True
                    text = fallback_truncate(text, hard_max)
                    metrics["final_length"] = count_chars(text)
                    metrics["is_valid"] = True
        else:
            metrics["final_length"] = count_chars(text)
            metrics["is_valid"] = True
        
        metrics["text"] = text
        return metrics
        
    except Exception as e:
        metrics["error"] = str(e)
        return metrics


async def run_tests():
    """Запуск тестов."""
    test_cases = [
        # SHORT (10)
        ("short", "selling", "Свободные окошки на завтра"),
        ("short", "selling", "Акция на ресницы"),
        ("short", "expert", "Как ухаживать за бровями дома"),
        ("short", "expert", "Топ-3 мифа о маникюре"),
        ("short", "personal", "Мой самый забавный случай"),
        ("short", "personal", "Как я пришла в бьюти"),
        ("short", "selling", "Запись на сегодня"),
        ("short", "expert", "Почему быстро ломается гель"),
        ("short", "personal", "Вчера был интересный день"),
        ("short", "expert", "Секреты стойкого маникюра"),
        
        # MEDIUM (10)
        ("medium", "selling", "Акция на ресницы на август"),
        ("medium", "selling", "Свободные окошки на следующую неделю"),
        ("medium", "expert", "Как ухаживать за бровями дома"),
        ("medium", "expert", "Топ-3 мифа о наращивании"),
        ("medium", "personal", "Мой путь в бьюти-индустрии"),
        ("medium", "personal", "Самый забавный случай с клиенткой"),
        ("medium", "selling", "Почему стоит записаться сейчас"),
        ("medium", "expert", "Секреты стойкого маникюра"),
        ("medium", "personal", "Как я стала мастером"),
        ("medium", "expert", "Частые ошибки в уходе за ногтями"),
        
        # LONG (10)
        ("long", "selling", "Акция на ресницы и маникюр на август"),
        ("long", "selling", "Свободные окошки на весь месяц"),
        ("long", "expert", "Полный гайд по уходу за бровями дома"),
        ("long", "expert", "Топ-5 мифов о наращивании ресниц"),
        ("long", "personal", "Моя история становления мастером"),
        ("long", "personal", "Самый запоминающийся день в салоне"),
        ("long", "selling", "Почему стоит выбрать именно меня"),
        ("long", "expert", "Секреты стойкого маникюра и ухода"),
        ("long", "personal", "Как я открыла свой салон"),
        ("long", "expert", "Частые ошибки клиентов и как их избежать"),
    ]
    
    results = []
    
    print(f"Запуск тестов: {len(test_cases)} генераций")
    print("=" * 80)
    
    for i, (post_length, text_type, topic) in enumerate(test_cases, 1):
        print(f"\n[{i}/{len(test_cases)}] {post_length.upper()} | {text_type} | {topic}")
        
        metrics = await call_beauty_ai(topic, text_type, None, None, post_length)
        results.append(metrics)
        
        status = "✓" if metrics["is_valid"] else "✗"
        editor = "[E]" if metrics["editor_pass"] else ""
        fallback = "[F]" if metrics["fallback"] else ""
        
        print(f"  {status}{editor}{fallback} Initial: {metrics['initial_length']} | Final: {metrics['final_length']} | Target: {metrics['target_max']} | API calls: {metrics['api_calls']}")
        
        if metrics["error"]:
            print(f"  ERROR: {metrics['error']}")
        
        # Небольшая пауза между запросами
        await asyncio.sleep(0.5)
    
    print("\n" + "=" * 80)
    print("РЕЗУЛЬТАТЫ ТЕСТОВ")
    print("=" * 80)
    
    # Статистика по режимам
    for mode in ["short", "medium", "long"]:
        mode_results = [r for r in results if r["mode"] == mode]
        valid = sum(1 for r in mode_results if r["is_valid"])
        editor_pass = sum(1 for r in mode_results if r["editor_pass"])
        fallback = sum(1 for r in mode_results if r["fallback"])
        avg_api_calls = sum(r["api_calls"] for r in mode_results) / len(mode_results)
        avg_length = sum(r["final_length"] for r in mode_results) / len(mode_results)
        
        print(f"\n{mode.upper()}:")
        print(f"  Всего: {len(mode_results)}")
        print(f"  Валидных: {valid}/{len(mode_results)}")
        print(f"  Editor-pass: {editor_pass}")
        print(f"  Fallback: {fallback}")
        print(f"  Среднее API-вызовов: {avg_api_calls:.1f}")
        print(f"  Средняя длина: {avg_length:.0f}")
    
    # Общая статистика
    total_valid = sum(1 for r in results if r["is_valid"])
    total_editor = sum(1 for r in results if r["editor_pass"])
    total_fallback = sum(1 for r in results if r["fallback"])
    total_api = sum(r["api_calls"] for r in results)
    
    print(f"\nИТОГО:")
    print(f"  Всего генераций: {len(results)}")
    print(f"  Валидных: {total_valid}/{len(results)}")
    print(f"  Editor-pass: {total_editor}")
    print(f"  Fallback: {total_fallback}")
    print(f"  Всего API-вызовов: {total_api}")
    print(f"  Среднее API-вызовов на пост: {total_api / len(results):.1f}")
    
    # Сохранение результатов в файл
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"test_report_{timestamp}.txt"
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("ОТЧЕТ О ТЕСТИРОВАНИИ ГЕНЕРАЦИИ ПОСТОВ\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Всего тестов: {len(results)}\n\n")
        
        for i, r in enumerate(results, 1):
            f.write(f"\n[{i}] {r['mode'].upper()} | {r['type']} | {r['topic']}\n")
            f.write(f"  Initial length: {r['initial_length']}\n")
            f.write(f"  Final length: {r['final_length']}\n")
            f.write(f"  Target max: {r['target_max']}\n")
            f.write(f"  Is valid: {r['is_valid']}\n")
            f.write(f"  Editor pass: {r['editor_pass']}\n")
            f.write(f"  Fallback: {r['fallback']}\n")
            f.write(f"  API calls: {r['api_calls']}\n")
            if r['error']:
                f.write(f"  Error: {r['error']}\n")
            f.write(f"  Text:\n{r.get('text', 'N/A')}\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("СТАТИСТИКА\n")
        f.write("=" * 80 + "\n")
        
        for mode in ["short", "medium", "long"]:
            mode_results = [r for r in results if r["mode"] == mode]
            valid = sum(1 for r in mode_results if r["is_valid"])
            editor_pass = sum(1 for r in mode_results if r["editor_pass"])
            fallback = sum(1 for r in mode_results if r["fallback"])
            avg_api_calls = sum(r["api_calls"] for r in mode_results) / len(mode_results)
            avg_length = sum(r["final_length"] for r in mode_results) / len(mode_results)
            
            f.write(f"\n{mode.upper()}:\n")
            f.write(f"  Всего: {len(mode_results)}\n")
            f.write(f"  Валидных: {valid}/{len(mode_results)}\n")
            f.write(f"  Editor-pass: {editor_pass}\n")
            f.write(f"  Fallback: {fallback}\n")
            f.write(f"  Среднее API-вызовов: {avg_api_calls:.1f}\n")
            f.write(f"  Средняя длина: {avg_length:.0f}\n")
        
        f.write(f"\nИТОГО:\n")
        f.write(f"  Всего генераций: {len(results)}\n")
        f.write(f"  Валидных: {total_valid}/{len(results)}\n")
        f.write(f"  Editor-pass: {total_editor}\n")
        f.write(f"  Fallback: {total_fallback}\n")
        f.write(f"  Всего API-вызовов: {total_api}\n")
        f.write(f"  Среднее API-вызовов на пост: {total_api / len(results):.1f}\n")
    
    print(f"\nОтчет сохранен: {report_file}")


if __name__ == "__main__":
    asyncio.run(run_tests())
