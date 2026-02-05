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
        return True
    except Exception as e:
        print(f"Ошибка Notion: {e}")
        return False

# --- 4. ОБРАБОТКА ГОЛОСА (Обновленная) ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🎧 Слушаю...")

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

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="🧠 Структурирую информацию...")
        
        current_date = datetime.now().strftime("%Y-%m-%d (%A)")

        # ОБНОВЛЕННЫЙ ПРОМПТ
        system_prompt = f"""
        Ты — профессиональный ассистент.
        СЕГОДНЯ: {current_date}.
        
        Твоя задача: Разбить текст пользователя на отдельные смысловые блоки (задачи, идеи, заметки).
        
        Инструкция по полям JSON:
        1. "summary": Короткий заголовок (суть в 3-7 словах).
        2. "details": Текст внутри задачи. 
           - Если это длинная мысль -> перескажи её или вставь полностью.
           - Если это простая задача (напр. "купить хлеб"), но она была сказана в контексте длинной истории -> скопируй сюда ТОЛЬКО то предложение, которое относилось к хлебу.
           - Если контекста нет -> оставь поле пустым (null). НЕ копируй сюда весь текст беседы.
        3. "category": Работа, Личное, Идея, Дневник, Обучение, Покупки, Здоровье.
        4. "date": YYYY-MM-DD (если есть привязка ко времени).
        
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
        
        data = json.loads(chat_completion.choices[0].message.content)
        items = data.get("items", [])
        
        report = f"📝 **Исходный текст:** {full_text[:100]}...\n\n"
        
        if items:
            report += "✅ **Сохранено:**\n"
            for item in items:
                summary = item.get("summary")
                details = item.get("details") # Теперь берем только то, что дал AI
                cat = item.get("category", "Входящие")
                date = item.get("date")
                
                # ИСПРАВЛЕНИЕ: Мы больше не используем full_text как запасной вариант
                content_to_save = details if details else "" 
                
                if create_notion_task(summary, cat, date, content_to_save):
                    date_str = f" 📅 {date}" if date else ""
                    report += f"— **{summary}** [{cat}]{date_str}\n"
                else:
                    report += f"— ❌ Ошибка Notion: {summary}\n"
        else:
            report += "\n🤷‍♂️ Ничего не смог выделить."

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=report)

        if os.path.exists(ogg_file_path):
            os.remove(ogg_file_path)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔥 Ошибка: {e}")
        print(e)

# --- 5. ЗАПУСК ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Бот готов (v4). Исправлено дублирование текста.")

if __name__ == '__main__':
    # keep_alive() 
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    print("Локальный бот v4 запущен!")
    application.run_polling()
