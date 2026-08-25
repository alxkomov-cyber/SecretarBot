from datetime import datetime, timedelta

def get_system_prompt():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d (%A)")
    
    calendar_str = "КАЛЕНДАРЬ НА 30 ДНЕЙ:\n"
    for i in range(0, 31):
        f_date = now + timedelta(days=i)
        calendar_str += f"{f_date.strftime('%Y-%m-%d')} ({f_date.strftime('%A')})\n"

    return f"""
    Сегодня: {today_str}.
    {calendar_str}
    
    Классифицируй запрос.
    ПРАВИЛО ОТМЕНЫ: Если передумал ("хотя нет", "забудь") — игнорируй отмененное.

    1. intent="save" (Запись задачи/идеи):
       - Триггеры: "Запиши", "Надо бы", "Хочу", "Купить", "Напомни СДЕЛАТЬ...".
       - ПРАВИЛО ОБЪЕДИНЕНИЯ: Если перечисляются шаги одного дела -> создай ОДНУ задачу (summary: общая суть, details: пошаговый список + фоновый контекст).
       - summary: ГЛАГОЛ + ОБЪЕКТ.
       - category: СТРОГО ОДНА ИЗ:[Работа, Личное, Идея, Покупки, Обучение]. Если не подходит -> Входящие.
       - tags: Массив из 2-4 ключевых слов (имена собственные, объекты).
       - details: Сохрани исходный текст или пошаговый список с фоновым контекстом.
       - date: "Завтра" -> дата из календаря. Абстрактно -> null.
       - isolated: true или false. (true если "разовая идея", "просто мысль").

    2. intent="search_calendar" (Планы):
       - Триггеры: "Какие планы", "Что на неделе".
       - query_text: null.
       - due_after / due_before: Границы поиска.

    3. intent="search_knowledge" (Знания / Поиск деталей):
       - Триггеры: "Напомни ЧТО БЫЛО", "Что я собирался", "В каком отеле", "Детали про...".
       - query_text: ОДИН КОРЕНЬ самого редкого слова ИЛИ Имя собственное (магазин, человек, город).
         Пример: "Что купить в магазине Семья" -> query_text="семья" или "семь".
       - need_details: true.

    4. intent="update_status" (Выполнение):
       - target_task: ОДНО КЛЮЧЕВОЕ СЛОВО (корень).
       - new_status: "Done", "In progress", "Not started".

    JSON FORMAT:
    {{ "intent": "save", "items":[ {{ "summary": "...", "details": "...", "tags":[], "category": "...", "date": "...", "isolated": false }} ] }}
    {{ "intent": "search_calendar", "due_after": "YYYY-MM-DD", "due_before": "YYYY-MM-DD" }}
    {{ "intent": "search_knowledge", "query_text": "...", "need_details": true }}
    {{ "intent": "update_status", "target_task": "...", "new_status": "Done" }}
    
    ВНИМАНИЕ: СТРОГО ЗАПРЕЩЕНО выводить свои рассуждения, теги <think>, комментарии или вводные слова. Выведи ТОЛЬКО валидный JSON!
    """
