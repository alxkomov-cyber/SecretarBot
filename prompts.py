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

    1. intent="save" (Запись):
       - Триггеры: "Запиши", "Надо бы", "Хочу", "Купить", "Напомни".
       - summary: ГЛАГОЛ + ОБЪЕКТ ("Купить хлеб", "Изучить Python").
       - category: СТРОГО ОДНА ИЗ:[Работа, Личное, Идея, Покупки, Обучение]. Если не подходит -> Входящие.
       - tags: Массив из 2-4 ключевых слов.
       - details: Полный исходный текст.
       - date: "Завтра" -> дата из календаря. Абстрактно -> null.
       - isolated: true или false. Ставь true ТОЛЬКО если пользователь сказал "разовая идея", "просто мысль" или "не связывать". Иначе false.

    2. intent="search_calendar" (Планы):
       - Триггеры: "Какие планы", "Что на неделе".
       - due_after / due_before: Границы поиска.

    3. intent="search_knowledge" (Знания):
       - Триггеры: "В каком отеле", "Бюджет", "С кем обсудить".
       - query_text: ОДИН КОРЕНЬ самого редкого/важного слова БЕЗ ОКОНЧАНИЯ (с маленькой буквы).
       - need_details: true.

    4. intent="update_status" (Выполнение):
       - target_task: ОДНО КЛЮЧЕВОЕ СЛОВО (корень).
       - new_status: "Done", "In progress", "Not started".

    JSON FORMAT:
    {{ "intent": "save", "items":[ {{ "summary": "...", "details": "...", "tags":[], "category": "...", "date": "...", "isolated": false }} ] }}
    {{ "intent": "search_calendar", "due_after": "YYYY-MM-DD", "due_before": "YYYY-MM-DD" }}
    {{ "intent": "search_knowledge", "query_text": "...", "need_details": true }}
    {{ "intent": "update_status", "target_task": "...", "new_status": "Done" }}
    """