import datetime
from services import notion

def run_janitor():
    """Логика автономного Дворника"""
    print("🧹 Дворник: Начинаю обход...")
    
    # Считаем даты (в формате UTC, как требует Notion API)
    now = datetime.datetime.utcnow()
    today_str = datetime.datetime.now().strftime("%Y-%m-%d") # Локальная дата для переноса
    
    # Дата 7 дней назад в формате ISO 8601 (напр. 2026-02-26T12:00:00.000Z)
    cutoff_date = (now - datetime.timedelta(days=7)).isoformat() + "Z"

    # --- 1. ПЕРЕНОС ПРОСРОЧКИ ---
    overdue_tasks = notion.get_overdue_tasks(today_str)
    overdue_count = 0
    for task in overdue_tasks:
        tags = task['tags']
        if "🔥 Просрочено" not in tags:
            tags.append("🔥 Просрочено")
        
        # Обновляем: ставим сегодняшнюю дату и новые теги
        if notion.update_task_overdue(task['id'], today_str, tags):
            overdue_count += 1

    # --- 2. АРХИВАЦИЯ СТАРЫХ ЗАДАЧ ---
    archive_tasks = notion.get_tasks_to_archive(cutoff_date)
    archive_count = 0
    for task in archive_tasks:
        if notion.update_status(task['id'], "Archived", exact_status=True):
            archive_count += 1

    result_msg = f"🧹 **Дворник закончил обход:**\n🔥 Перенесено на сегодня: {overdue_count}\n📦 Отправлено в архив: {archive_count}"
    print(result_msg.replace("**", ""))
    return result_msg