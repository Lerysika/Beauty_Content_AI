"""Тестовый скрипт для Medical Claim Guard — расширенная версия 30 тест-кейсов."""

import asyncio
from openai import AsyncOpenAI
from utils.medical_claim_detector import detect_medical_claims, is_high_risk_topic
from services.medical_claim_guard_service import medical_claim_guard
from prompts.medical_claim_guard_prompt import get_medical_claim_guard_prompt
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv()

AI_API_KEY = os.getenv("AI_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.aitunnel.ru/v1")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.5-flash")

ai_client = AsyncOpenAI(
    api_key=AI_API_KEY,
    base_url=AI_BASE_URL,
)


# Категория A — безопасные кейсы (10)
SAFE_CASES = [
    {
        "name": "Косметическое описание кожи",
        "text": "После процедуры кожа выглядит мягче и ухоженнее.",
        "expected": "pass",
        "description": "Косметическое описание результата"
    },
    {
        "name": "Визуальный эффект рук",
        "text": "После процедуры руки выглядят ухоженными.",
        "expected": "pass",
        "description": "Визуальный эффект без медицинских обещаний"
    },
    {
        "name": "Субъективное ощущение тепла",
        "text": "После процедуры ощущается приятное тепло.",
        "expected": "pass",
        "description": "Субъективное ощущение"
    },
    {
        "name": "Расслабление",
        "text": "Процедура помогает расслабиться.",
        "expected": "pass",
        "description": "Субъективное ощущение расслабления"
    },
    {
        "name": "Приятные ощущения",
        "text": "Сама процедура очень приятная.",
        "expected": "pass",
        "description": "Субъективное ощущение"
    },
    {
        "name": "Визуальное улучшение",
        "text": "Маникюр визуально улучшает состояние ногтей.",
        "expected": "pass",
        "description": "Визуальный эффект"
    },
    {
        "name": "Более аккуратный вид",
        "text": "После брови выглядят более аккуратными.",
        "expected": "pass",
        "description": "Визуальный эффект"
    },
    {
        "name": "Может понравиться",
        "text": "Процедура может понравиться.",
        "expected": "pass",
        "description": "Маркетинговый язык"
    },
    {
        "name": "Часто выбирают",
        "text": "Этот вариант часто выбирают.",
        "expected": "pass",
        "description": "Маркетинговый язык"
    },
    {
        "name": "Комфортно",
        "text": "Во время процедуры комфортно.",
        "expected": "pass",
        "description": "Субъективное ощущение"
    },
]


# Категория B — явные medical claims (10)
EXPLICIT_MEDICAL_CASES = [
    {
        "name": "Лечит воспаление",
        "text": "Процедура лечит воспаление кожи.",
        "expected": "flag",
        "description": "Лечебное обещание"
    },
    {
        "name": "Избавляет от",
        "text": "Сыворотка избавляет от акне.",
        "expected": "flag",
        "description": "Лечебное обещание"
    },
    {
        "name": "Устраняет заболевание",
        "text": "Процедура устраняет заболевание кожи.",
        "expected": "flag",
        "description": "Лечебное обещание"
    },
    {
        "name": "Восстанавливает ткани",
        "text": "Крем восстанавливает поврежденные ткани.",
        "expected": "flag",
        "description": "Лечебное обещание"
    },
    {
        "name": "Стимулирует рост волос",
        "text": "Сыворотка стимулирует рост волос.",
        "expected": "flag",
        "description": "Физиологическое обещание"
    },
    {
        "name": "Укрепляет ногтевую пластину",
        "text": "Наращивание укрепляет ногтевую пластину.",
        "expected": "flag",
        "description": "Физиологическое обещание"
    },
    {
        "name": "Снимает боль",
        "text": "Тепло парафина снимает боль в суставах.",
        "expected": "flag",
        "description": "Физиологическое обещание"
    },
    {
        "name": "Гарантированно помогает",
        "text": "Процедура гарантированно поможет.",
        "expected": "flag",
        "description": "Гарантия результата"
    },
    {
        "name": "Абсолютно безопасно",
        "text": "Процедура абсолютно безопасна.",
        "expected": "flag",
        "description": "Категоричная гарантия безопасности"
    },
    {
        "name": "Не вызывает аллергий",
        "text": "Никаких аллергий быть не может.",
        "expected": "flag",
        "description": "Категоричная гарантия безопасности"
    },
]


# Категория C — замаскированные / перефразированные claims (10)
MASKED_MEDICAL_CASES = [
    {
        "name": "Становится легче в области кистей",
        "text": "После процедуры становится легче в области кистей.",
        "expected": "flag",
        "description": "Перефразированное обещание уменьшения боли"
    },
    {
        "name": "Убирает неприятные ощущения",
        "text": "Процедура помогает убрать неприятные ощущения.",
        "expected": "flag",
        "description": "Перефразированное обещание уменьшения боли"
    },
    {
        "name": "Улучшает состояние изнутри",
        "text": "Сыворотка улучшает состояние кожи изнутри.",
        "expected": "flag",
        "description": "Медицинское объяснение без оснований"
    },
    {
        "name": "Активирует рост волос",
        "text": "Маска активирует рост волос.",
        "expected": "flag",
        "description": "Перефразированное физиологическое обещание"
    },
    {
        "name": "Запускает работу фолликулов",
        "text": "Сыворотка запускает работу фолликулов.",
        "expected": "flag",
        "description": "Перефразированное физиологическое обещание"
    },
    {
        "name": "Выводит всё лишнее из кожи",
        "text": "Процедура выводит всё лишнее из кожи.",
        "expected": "flag",
        "description": "Медицинское объяснение без оснований"
    },
    {
        "name": "Пробуждает спящие луковицы",
        "text": "Сыворотка пробуждает спящие луковицы.",
        "expected": "flag",
        "description": "Физиологическое обещание"
    },
    {
        "name": "Ускоряет рост ногтей",
        "text": "Витамины ускоряют рост ногтей.",
        "expected": "flag",
        "description": "Физиологическое обещание"
    },
    {
        "name": "Восстанавливает фолликулы",
        "text": "Процедура восстанавливает фолликулы.",
        "expected": "flag",
        "description": "Физиологическое обещание"
    },
    {
        "name": "Подходит всем",
        "text": "Эта процедура подходит всем без исключения.",
        "expected": "flag",
        "description": "Категоричная гарантия безопасности"
    },
]


# Все тест-кейсы
ALL_TEST_CASES = SAFE_CASES + EXPLICIT_MEDICAL_CASES + MASKED_MEDICAL_CASES


async def test_single_case(test_case, index):
    """Тестирует один кейс с полным pipeline."""
    text = test_case["text"]
    expected = test_case["expected"]
    
    # Pre-check
    has_suspicious, patterns = detect_medical_claims(text)
    is_high_risk = is_high_risk_topic(text)
    
    result = {
        "index": index,
        "name": test_case["name"],
        "input": text,
        "expected": expected,
        "pre_check": "FLAG" if has_suspicious else "PASS",
        "patterns": patterns,
        "high_risk": is_high_risk,
        "guard_passes": 0,
        "output": text,
        "remaining_claims": False,
        "final_status": "",
        "api_calls": 0,
    }
    
    if has_suspicious:
        # AI Guard
        try:
            corrected_text = await medical_claim_guard(text, "expert", ai_client, AI_MODEL)
            result["output"] = corrected_text
            result["api_calls"] = 1  # Упрощённо, считаем 1 вызов
            
            # Re-scan
            has_claim_after, _ = detect_medical_claims(corrected_text)
            result["remaining_claims"] = has_claim_after
            
            if not has_claim_after:
                result["final_status"] = "CORRECTED"
            else:
                result["final_status"] = "REMAINING_CLAIM"
                
        except Exception as e:
            result["final_status"] = f"ERROR: {e}"
    else:
        result["final_status"] = "PASSED_PRE_CHECK"
    
    return result


async def test_all_cases():
    """Тестирует все 30 кейсов."""
    print("=" * 80)
    print("ТЕСТИРОВАНИЕ MEDICAL CLAIM GUARD — 30 ТЕСТ-КЕЙСОВ")
    print("=" * 80)
    
    results = []
    
    for i, test_case in enumerate(ALL_TEST_CASES, 1):
        print(f"\n[{i}] {test_case['name']}")
        print(f"Категория: {test_case['expected']}")
        print(f"Текст: {test_case['text']}")
        
        result = await test_single_case(test_case, i)
        results.append(result)
        
        print(f"Pre-check: {result['pre_check']}")
        print(f"Final status: {result['final_status']}")
        
        if result['api_calls'] > 0:
            print(f"API calls: {result['api_calls']}")
        
        if result['output'] != result['input']:
            print(f"Output: {result['output']}")
    
    return results


def calculate_statistics(results):
    """Рассчитывает статистику по результатам."""
    stats = {
        "total_cases": len(results),
        "safe_cases": len([r for r in results if r["expected"] == "pass"]),
        "suspicious_cases": len([r for r in results if r["expected"] == "flag"]),
        "safe_cases_detected": 0,
        "safe_cases_blocked": 0,
        "suspicious_cases_detected": 0,
        "suspicious_cases_corrected": 0,
        "suspicious_cases_remaining": 0,
        "total_api_calls": 0,
    }
    
    for result in results:
        stats["total_api_calls"] += result["api_calls"]
        
        if result["expected"] == "pass":
            if result["pre_check"] == "PASS":
                stats["safe_cases_detected"] += 1
            else:
                stats["safe_cases_blocked"] += 1
        else:
            if result["pre_check"] == "FLAG":
                stats["suspicious_cases_detected"] += 1
                if result["final_status"] == "CORRECTED":
                    stats["suspicious_cases_corrected"] += 1
                elif result["remaining_claims"]:
                    stats["suspicious_cases_remaining"] += 1
    
    return stats


def print_statistics(stats):
    """Выводит статистику."""
    print("\n" + "=" * 80)
    print("СТАТИСТИКА")
    print("=" * 80)
    
    print(f"\nВсего кейсов: {stats['total_cases']}")
    print(f"Безопасных кейсов: {stats['safe_cases']}")
    print(f"Подозрительных кейсов: {stats['suspicious_cases']}")
    
    print(f"\nБезопасные кейсы:")
    print(f"  Обнаружены как безопасные: {stats['safe_cases_detected']}/{stats['safe_cases']} ({stats['safe_cases_detected']/stats['safe_cases']*100:.1f}%)")
    print(f"  Ложно заблокированы: {stats['safe_cases_blocked']}/{stats['safe_cases']} ({stats['safe_cases_blocked']/stats['safe_cases']*100:.1f}%)")
    
    print(f"\nПодозрительные кейсы:")
    print(f"  Обнаружены pre-check: {stats['suspicious_cases_detected']}/{stats['suspicious_cases']} ({stats['suspicious_cases_detected']/stats['suspicious_cases']*100:.1f}%)")
    print(f"  Исправлены AI Guard: {stats['suspicious_cases_corrected']}/{stats['suspicious_cases']} ({stats['suspicious_cases_corrected']/stats['suspicious_cases']*100:.1f}%)")
    print(f"  Остались claims: {stats['suspicious_cases_remaining']}/{stats['suspicious_cases']} ({stats['suspicious_cases_remaining']/stats['suspicious_cases']*100:.1f}%)")
    
    print(f"\nAPI-вызовы:")
    print(f"  Всего: {stats['total_api_calls']}")
    print(f"  Среднее на кейс: {stats['total_api_calls']/stats['total_cases']:.2f}")


def save_report(results, stats):
    """Сохраняет отчёт в файл."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"medical_guard_report_{timestamp}.txt"
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("MEDICAL CLAIM GUARD — ОТЧЁТ ТЕСТИРОВАНИЯ\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Всего кейсов: {stats['total_cases']}\n\n")
        
        f.write("СТАТИСТИКА\n")
        f.write("-" * 80 + "\n")
        f.write(f"Безопасные кейсы: {stats['safe_cases']}\n")
        f.write(f"  Обнаружены как безопасные: {stats['safe_cases_detected']}/{stats['safe_cases']} ({stats['safe_cases_detected']/stats['safe_cases']*100:.1f}%)\n")
        f.write(f"  Ложно заблокированы: {stats['safe_cases_blocked']}/{stats['safe_cases']} ({stats['safe_cases_blocked']/stats['safe_cases']*100:.1f}%)\n\n")
        
        f.write(f"Подозрительные кейсы: {stats['suspicious_cases']}\n")
        f.write(f"  Обнаружены pre-check: {stats['suspicious_cases_detected']}/{stats['suspicious_cases']} ({stats['suspicious_cases_detected']/stats['suspicious_cases']*100:.1f}%)\n")
        f.write(f"  Исправлены AI Guard: {stats['suspicious_cases_corrected']}/{stats['suspicious_cases']} ({stats['suspicious_cases_corrected']/stats['suspicious_cases']*100:.1f}%)\n")
        f.write(f"  Остались claims: {stats['suspicious_cases_remaining']}/{stats['suspicious_cases']} ({stats['suspicious_cases_remaining']/stats['suspicious_cases']*100:.1f}%)\n\n")
        
        f.write(f"API-вызовы: {stats['total_api_calls']}\n")
        f.write(f"Среднее на кейс: {stats['total_api_calls']/stats['total_cases']:.2f}\n\n")
        
        f.write("ДЕТАЛЬНЫЕ РЕЗУЛЬТАТЫ\n")
        f.write("-" * 80 + "\n\n")
        
        for result in results:
            f.write(f"[{result['index']}] {result['name']}\n")
            f.write(f"Категория: {result['expected']}\n")
            f.write(f"Input: {result['input']}\n")
            f.write(f"Pre-check: {result['pre_check']}\n")
            f.write(f"Final status: {result['final_status']}\n")
            f.write(f"API calls: {result['api_calls']}\n")
            if result['output'] != result['input']:
                f.write(f"Output: {result['output']}\n")
            f.write("\n")
    
    print(f"\nОтчёт сохранён: {filename}")


async def main():
    """Запускает все тесты."""
    print("ТЕСТИРОВАНИЕ MEDICAL CLAIM GUARD — РАСШИРЕННАЯ ВЕРСИЯ")
    print("=" * 80)
    
    results = await test_all_cases()
    stats = calculate_statistics(results)
    
    print_statistics(stats)
    save_report(results, stats)
    
    print("\n" + "=" * 80)
    print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
