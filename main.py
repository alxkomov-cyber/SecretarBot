import os
import json
import asyncio
import requests # <--- Добавили стандартную библиотеку для запросов
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq
from notion_client import Client
from flask import Flask
from threading import Thread

# --- 1. СЕРВЕРНАЯ ЧАСТЬ ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive"

def run_http():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- 2. НАСТРОЙКИ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")

groq_client = Groq(api_key=GROQ_API_KEY)
notion = Client(auth=NOTION_TOKEN)

# --- 3. ФУНКЦИЯ: ЗАПИСЬ В NOTION ---
def create_notion_task(title, category="Входящие", due_date=None, content_text=None):
    if not category: category = "Входящие"
    
    new_page = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Задача": {"title": [{"text": {"content": title}}]},
            "Категория": {"select": {"name": category}}
        }
    }
    if due_date:
        new_page["properties"]["Дата"] = {"date": {"start": due_date}}
    
    if content_text:
        new_page["children"] = [{
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": content_text[:2000]}}]}
        }]

    try:
        notion.pages.create(**new_page)
        return True
    except Exception as e:
        print(f"❌ Ошибка записи: {e}")
        return False

# --- 4. ФУНКЦИЯ: ПОИСК В NOTION (Через requests) ---
def search_notion(query_text=None, query_date=None, search_mode="text"):
    """
    Используем requests напрямую, чтобы избежать ошибок библиотек.
    """
    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    filter_params = {"and": []}

    # Поиск по дате
    if query_date:
        if search_mode == "date_due":
            filter_params["and"].append({
                "property": "Дата",
                "date": {"equals": query_date}
            })
        elif search_mode == "date_created":
            # Ищем созданные в этот день (по Notion API)
            filter_params["and"].append({
                "property": "Дата создания", # Убедитесь, что в Notion колонка так и называется
                "date": {"equals": query_date} 
            })

    # Поиск по тексту
    if query_text:
        filter_params["and"].append({
            "property": "Задача",
            "rich_text": {"contains": query_text}
        })

    # Если фильтров нет — пустой список
    if not filter_params["and"]:
        return []

    try:
        response = requests.post(url, headers=headers, json={"filter": filter_params})
        
        if response.status_code != 200:
            print(f"Ошибка API Notion: {response.text}")
            return [f"Ошибка Notion: {response.status_code}"]

        data = response.json()
        results = []
        
        for page in data.get("results", []):
            props = page["properties"]
            
            # Достаем данные (безопасно)
            title_list = props.get("Задача", {}).get("title", [])
            title = title_list[0]["plain_text"] if title_list else "Без названия"
            
            status = props.get("Статус", {}).get("status", {}).get("name", "Нет статуса")
            cat_obj = props.get("Категория", {}).get("select")
            category = cat_obj.get("name") if cat_obj else "Без категории"
            
            results.append(f"- {title} ({category}, Статус: {status})")
            
        return results
    except Exception as e:
        print(f"❌ Ошибка поиска requests: {e}")
        return [f"Ошибка: {e}"]

# --- 5. ОБРАБОТКА ГОЛОСА ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🎧 Слушаю...", disable_notification=True)

    try:
        # 1. Транскрибация
        file_id = update.message.voice.file_id
        new_file = await context.bot.get_file(file_id)
        ogg_file_path = f"voice_{file_id}.ogg"
        await new_file.download_to_drive(ogg_file_path)

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="✍️ Читаю мысли...")
        
        with open(ogg_file_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(ogg_file_path, file.read()),
                model="whisper-large-v3",
                response_format="json",
                language="ru",
                temperature=0.0
            )
        full_text = transcription.text
        print(f"Текст: {full_text}")

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="🧠 Думаю...")

        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # --- ОБНОВЛЕННЫЙ ПРОМПТ С КАТЕГОРИЯМИ ---
        system_prompt = f"""
        Сегодня: {current_date}.
        Ты — управляющий базой данных Notion. 
        
        Определи намерение (intent): "save" или "search".

        1. intent="save" (Добавить, напомни, идея, нужно сделать):
           - "category": Выбери СТРОГО из списка: Работа, Личное, Идея, Дневник, Обучение, Покупки, Здоровье.
             ЕСЛИ есть слова "купить", "заказать", "цена" -> ставь "Покупки".
             ЕСЛИ не подходит никуда -> ставь "Входящие".
           - "date": Ставь дату (YYYY-MM-DD) ТОЛЬКО если пользователь явно сказал "завтра", "в пятницу", "7 февраля". Если даты нет -> ставь null.

        2. intent="search" (Найди, какие планы, что я записал):
           - "query_text": что ищем (или null).
           - "query_date": дата YYYY-MM-DD (или null).
           - "search_mode": 
             * "date_due" (планы на будущее, дедлайны).
             * "date_created" (прошлое, "что я записал вчера").
             * "text" (поиск по смыслу).

        Формат JSON:
        ВАРИАНТ 1 (SAVE):
        {{ "intent": "save", "items": [ {{ "summary": "...", "details": "...", "category": "...", "date": "..." }} ] }}

        ВАРИАНТ 2 (SEARCH):
        {{ "intent": "search", "query_text": "...", "query_date": "...", "search_mode": "..." }}
        """

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": full_text}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        
        response_data = json.loads(chat_completion.choices[0].message.content)
        intent = response_data.get("intent")

        # --- ЛОГИКА: СОХРАНЕНИЕ ---
        if intent == "save":
            items = response_data.get("items", [])
            report = f"📝 **Услышал:** {full_text}\n\n"
            
            if items:
                report += "✅ **Сохранено:**\n"
                for item in items:
                    summary = item.get("summary")
                    details = item.get("details")
                    cat = item.get("category")
                    date = item.get("date")
                    
                    content_to_save = details if details else ""
                    
                    if create_notion_task(summary, cat, date, content_to_save):
                        date_str = f" 📅 {date}" if date else ""
                        report += f"— **{summary}** [{cat}]{date_str}\n"
                    else:
                        report += f"— ❌ Ошибка API: {summary}\n"
            else:
                report += "Не понял, что сохранить."
            
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=report)

        # --- ЛОГИКА: ПОИСК ---
        elif intent == "search":
            q_text = response_data.get("query_text")
            q_date = response_data.get("query_date")
            s_mode = response_data.get("search_mode", "text")

            found_rows = search_notion(q_text, q_date, s_mode)

            if found_rows:
                summary_prompt = f"Пользователь спросил: '{full_text}'. Найденные задачи: {found_rows}. Дай краткий ответ."
                
                summary_response = groq_client.chat.completions.create(
                    messages=[{"role": "user", "content": summary_prompt}],
                    model="llama-3.3-70b-versatile"
                )
                final_answer = summary_response.choices[0].message.content
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=f"🔍 **Результат:**\n\n{final_answer}")
            else:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=f"🔍 **Поиск:**\nНичего не найдено.")

        if os.path.exists(ogg_file_path):
            os.remove(ogg_file_path)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔥 Ошибка: {e}")
        print(f"ERROR: {e}")

# --- 6. ЗАПУСК ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Бот V6.2 (Requests) готов.")

if __name__ == '__main__':
    # keep_alive() 
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    print("Бот V6.2 запущен локально!")
    application.run_polling()
