import os
import json
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq
from notion_client import Client
from flask import Flask
from threading import Thread

# --- 1. ФУНКЦИЯ: Пинг сервера (чтобы Render не усыплял бота) ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive"

def run_http():
    # Запускаем маленький веб-сервер на порту 8080
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- 2. НАСТРОЙКИ И КЛИЕНТЫ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")

groq_client = Groq(api_key=GROQ_API_KEY)
notion = Client(auth=NOTION_TOKEN)

# --- 3. ФУНКЦИЯ: Добавление в Notion ---
def create_notion_task(text, category="Inbox"):
    try:
        notion.pages.create(
            parent={"database_id": NOTION_DB_ID},
            properties={
                # ВАЖНО: Убедитесь, что в Notion колонка называется "Задача" (как мы делали раньше)
                "Задача": {"title": [{"text": {"content": text}}]},
            }
        )
        return True
    except Exception as e:
        print(f"Ошибка Notion: {e}")
        return False

# --- 4. ФУНКЦИЯ: Обработка голосового ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🎧 Слушаю...")

    try:
        file_id = update.message.voice.file_id
        new_file = await context.bot.get_file(file_id)
        ogg_file_path = f"voice_{file_id}.ogg"
        await new_file.download_to_drive(ogg_file_path)

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="✍️ Расшифровываю...")
        
        with open(ogg_file_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(ogg_file_path, file.read()),
                model="whisper-large-v3",
                response_format="json",
                language="ru",
                temperature=0.0
            )
        text_from_voice = transcription.text

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="🧠 Анализирую задачи...")
        
        system_prompt = """
        Ты — помощник по продуктивности. Твоя цель — извлечь из текста список задач.
        Верни ответ СТРОГО в формате JSON.
        Формат: {"tasks": ["Задача 1", "Задача 2"], "ideas": ["Идея 1"]}
        """

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text_from_voice}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        
        data = json.loads(chat_completion.choices[0].message.content)
        tasks = data.get("tasks", [])
        ideas = data.get("ideas", [])
        
        report = f"📝 **Распознано:** {text_from_voice}\n\n"
        
        if tasks:
            report += "✅ **Добавлено в задачи:**\n"
            for task in tasks:
                create_notion_task(task, "Задача")
                report += f"— {task}\n"
        
        if ideas:
            report += "\n💡 **Идеи:**\n"
            for idea in ideas:
                create_notion_task(idea, "Идея")
                report += f"— {idea}\n"

        if not tasks and not ideas:
            report += "\n🤷‍♂️ Задач не найдено."

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=report)

        if os.path.exists(ogg_file_path):
            os.remove(ogg_file_path)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔥 Ошибка: {e}")
        print(e)

# --- 5. ФУНКЦИЯ: Старт ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Бот на сервере работает! Жду голосовое.")

# --- 6. ЗАПУСК ---
if __name__ == '__main__':
    keep_alive() # Запускаем фоновый сервер для Render
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    print("Бот запущен!")
    application.run_polling()
