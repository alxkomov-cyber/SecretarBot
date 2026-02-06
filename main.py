import os
import json
import asyncio
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

# --- 3. ФУНКЦИЯ NOTION ---
def create_notion_task(title, category="Входящие", due_date=None, content_text=None):
    # Если категория пришла пустая (None), ставим "Входящие"
    if not category: 
        category = "Входящие"

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
        new_page["children"] = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content_text[:2000]}}]
                }
            }
        ]

    try:
        notion.pages.create(**new_page)
        print(f"✅ Успешно создано в Notion: {title} [{category}]") # Лог для отладки
        return True
    except Exception as e:
        print(f"❌ Ошибка записи в Notion: {e}")
        return False

# --- 4. ОБРАБОТКА ГОЛОСА ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сообщение о статусе (без звука уведомления)
    status_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text="🎧 Слушаю...", 
        disable_notification=True
    )

    try:
        file_id = update.message.voice.file_id
        new_file = await context.bot.get_file(file_id)
        ogg_file_path = f"voice_{file_id}.ogg"
        await new_file.download_to_drive(ogg_file_path)

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="✍️ Транскрибация...")
        
        with open(ogg_file_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(ogg_file_path, file.read()),
                model="whisper-large-v3",
                response_format="json",
                language="ru",
                temperature=0.0
            )
        full_text = transcription.text
        print(f"Распознанный текст: {full_text}") # Лог в консоль сервера

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="🧠 Анализ (V5)...")
        
        current_date = datetime.now().strftime("%Y-%m-%d (%A)")

        # УЛУЧШЕННЫЙ ПРОМПТ (Борьба с дублями)
        system_prompt = f"""
        Ты — умный секретарь. Сегодня: {current_date}.
        
        Твоя задача: Превратить поток речи в ЧЕТКИЙ список задач.
        
        ВАЖНЫЕ ПРАВИЛА:
        1. ОБЪЕДИНЕНИЕ: Если пользователь говорит об одном и том же, но сбивчиво (возвращается к теме) — объедини это в ОДНУ задачу. Не создавай дубликаты!
           Пример: "Надо сделать отчет... кстати купить хлеб... и в отчет добавить диаграмму".
           Итог: 1 задача "Сделать отчет (с диаграммой)" и 1 задача "Купить хлеб".
        
        2. ПОЛЯ JSON:
           - "summary": Короткий заголовок (суть задачи).
           - "details": ВСЕ подробности, уточнения и контекст. Если пользователь долго рассуждал — всё это идет сюда.
           - "category": Работа, Личное, Идея, Дневник, Обучение, Покупки, Здоровье. (Если не понятно — ставь "Входящие").
           - "date": YYYY-MM-DD (только если названа конкретная дата типа "завтра", "в пятницу").
        
        Формат ответа JSON:
        {{
           "items": [
             {{ "summary": "...", "details": "...", "category": "...", "date": "..." }}
           ]
        }}
        """

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": full_text}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        
        response_content = chat_completion.choices[0].message.content
        print(f"Ответ AI: {response_content}") # Лог, чтобы видеть, что вернул AI

        data = json.loads(response_content)
        items = data.get("items", [])
        
        report = f"📝 **Текст:** {full_text[:100]}...\n\n"
        
        if items:
            report += "✅ **Сохранено:**\n"
            for item in items:
                summary = item.get("summary")
                details = item.get("details")
                cat = item.get("category")
                date = item.get("date")
                
                # Защита от пустых деталей
                content_to_save = details if details else "" 
                
                if create_notion_task(summary, cat, date, content_to_save):
                    date_str = f" 📅 {date}" if date else ""
                    report += f"— **{summary}** [{cat}]{date_str}\n"
                else:
                    report += f"— ❌ Ошибка Notion: {summary}\n"
        else:
            report += "\n🤷‍♂️ Задач не найдено."

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=report)

        if os.path.exists(ogg_file_path):
            os.remove(ogg_file_path)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔥 Ошибка: {e}")
        print(f"CRITICAL ERROR: {e}")

# --- 5. ЗАПУСК ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Бот V5 (Stable) перезапущен и готов.")

if __name__ == '__main__':
    keep_alive() 
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    print("Бот запущен!")
    application.run_polling()
