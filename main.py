from flask import Flask
from threading import Thread
import os
import json
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq
from notion_client import Client

# --- НАСТРОЙКИ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")

# Инициализация клиентов
groq_client = Groq(api_key=GROQ_API_KEY)
notion = Client(auth=NOTION_TOKEN)

# --- ФУНКЦИЯ: Добавление в Notion ---
def create_notion_task(text, category="Inbox"):
    """Создает новую страницу в базе данных Notion"""
    try:
        notion.pages.create(
            parent={"database_id": NOTION_DB_ID},
            properties={
                # ВАЖНО: В Notion первая колонка обычно называется "Name" или "Title". 
                # Если у вас "Название", поменяйте "Name" ниже на "Название" или "aa" (см. подсказку ниже)
                "Задача": {"title": [{"text": {"content": text}}]},
                
                # Можно добавлять теги, если в базе есть колонка "Tags" или "Категория" (Select)
                # "Tags": {"select": {"name": category}} 
            }
        )
        return True
    except Exception as e:
        print(f"Ошибка Notion: {e}")
        return False

# --- ФУНКЦИЯ: Пинг сервера (чтобы не спал) ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive"

def run_http():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- ФУНКЦИЯ: Обработка голосового ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🎧 Слушаю...")

    try:
        # 1. Скачиваем файл
        file_id = update.message.voice.file_id
        new_file = await context.bot.get_file(file_id)
        ogg_file_path = f"voice_{file_id}.ogg"
        await new_file.download_to_drive(ogg_file_path)

        # 2. Whisper: Голос -> Текст
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

        # 3. Llama: Текст -> Структура (JSON)
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="🧠 Анализирую задачи...")
        
        system_prompt = """
        Ты — помощник по продуктивности. Твоя цель — извлечь из текста список задач.
        Верни ответ СТРОГО в формате JSON. Не пиши ничего лишнего.
        Формат:
        {
            "tasks": ["Задача 1", "Задача 2"],
            "ideas": ["Идея 1"]
        }
        Если задач нет, верни пустые списки.
        """

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text_from_voice}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"} # Заставляем AI вернуть чистый JSON
        )
        
        ai_response_text = chat_completion.choices[0].message.content
        data = json.loads(ai_response_text) # Превращаем текст в словарь Python

        # 4. Сохраняем в Notion
        tasks = data.get("tasks", [])
        ideas = data.get("ideas", [])
        
        report = f"📝 **Распознано:** {text_from_voice}\n\n"
        
        if tasks:
            report += "✅ **Добавлено в задачи:**\n"
            for task in tasks:
                if create_notion_task(task, "Задача"):
                    report += f"— {task}\n"
                else:
                    report += f"— ❌ Ошибка добавления: {task}\n"
        
        if ideas:
            report += "\n💡 **Идеи (тоже добавил):**\n"
            for idea in ideas:
                create_notion_task(idea, "Идея")
                report += f"— {idea}\n"

        if not tasks and not ideas:
            report += "\n🤷‍♂️ Задач не найдено."

        # Отправляем отчет
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=report)

        # Уборка
        if os.path.exists(ogg_file_path):
            os.remove(ogg_file_path)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔥 Ошибка: {e}")
        print(e)

# --- ЗАПУСК ---

if __name__ == '__main__':
    keep_alive()  # <--- ДОБАВИЛИ ВОТ ЭТО
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    # ... (дальше ваш старый код)
    if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    print("Бот (Telegram + Groq + Notion) запущен!")
    application.run_polling()
