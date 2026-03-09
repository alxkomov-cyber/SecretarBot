import asyncio
import requests
from flask import Flask
from threading import Thread
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

import config
from services import voice, llm, notion
from agents import janitor, analyst

# --- СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "I am alive"
def run_http(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): t = Thread(target=run_http); t.start()

# --- БЕЗОПАСНОСТЬ ---
def is_allowed(update: Update):
    """Проверяет, является ли отправитель Хозяином бота"""
    if not config.ALLOWED_USER_ID:
        return True # Если ID не задан в настройках, пускаем всех (для первого теста)
    return str(update.effective_user.id) == str(config.ALLOWED_USER_ID)

# --- ИНТЕРФЕЙС (КНОПКИ) ---
def get_main_keyboard():
    keyboard = [[KeyboardButton("🧹 Дворник"), KeyboardButton("🧠 Аналитик")],
        [KeyboardButton("💡 Сироты")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

# --- ИНТЕРФЕЙС (МЕНЮ КОМАНД СБОКУ) ---
async def post_init(application):
    """Устанавливает меню команд со слэшем при запуске бота"""
    await application.bot.set_my_commands([
        ("clean", "🧹 Запустить Дворника"),
        ("analyze", "🧠 Запустить Аналитика"),
        ("orphans", "💡 Показать идеи-сироты")
    ])

# --- НОЧНЫЕ ОТЧЕТЫ (ТИХИЕ) ---
def send_silent_notification(text):
    """Отправляет сообщение без звука напрямую через API"""
    if not config.ALLOWED_USER_ID:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.ALLOWED_USER_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_notification": True # БЕЗ ЗВУКА!
    }
    requests.post(url, json=payload)

def scheduled_janitor_job():
    res = janitor.run_janitor()
    send_silent_notification(res)

def scheduled_analyst_job():
    res = analyst.run_analyst()
    send_silent_notification(res)

# --- ОБРАБОТЧИКИ КОМАНД ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text="Бот V28 (Security & UI) готов к работе!",
        reply_markup=get_main_keyboard() # Показываем кнопки
    )

async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Вызываю Дворника... 🧹")
    result = janitor.run_janitor()
    await context.bot.send_message(chat_id=update.effective_chat.id, text=result)

async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Запускаю Аналитика... 🧠")
    result = analyst.run_analyst()
    await context.bot.send_message(chat_id=update.effective_chat.id, text=result, parse_mode='Markdown')

async def cmd_orphans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🔍 Ищу одинокие идеи...")
    orphans = notion.get_orphan_ideas()
    if not orphans:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Сирот нет. Все идеи пристроены!")
    else:
        msg = "💡 **Необработанные идеи-сироты:**\n"
        for i, item in enumerate(orphans, 1):
            msg += f"{i}. [{item['title']}]({item['url']})\n"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='Markdown')

# --- ОБРАБОТЧИК КНОПОК И ТЕКСТА ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    text = update.message.text
    
    if text == "🧹 Дворник":
        await cmd_clean(update, context)
    elif text == "🧠 Аналитик":
        await cmd_analyze(update, context)
    elif text == "💡 Сироты":
        await cmd_orphans(update, context)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Пожалуйста, используйте кнопки меню или голосовые сообщения.")

# --- ОБРАБОТЧИК ГОЛОСА ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return # Чужаков игнорируем
    
    status_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🎧...", disable_notification=True)
    full_text = await voice.transcribe_voice(update, context)
    if not full_text:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="❌ Ошибка голоса.")
        return

    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="🧠 Анализ...")
    resp = llm.analyze_text(full_text)
    intent = resp.get("intent")

    try:
        if intent == "save":
            items = resp.get("items",[])
            report = f"📝 **Текст:** {full_text}\n\n"
            for item in items:
                cat = item.get("category") or "Входящие"
                details = item.get("details")
                if not details or len(details) < 5: details = full_text
                
                iso = item.get("isolated", False)
                if notion.create_task(item.get("summary"), cat, item.get("date"), details, item.get("tags"), is_isolated=iso):
                    iso_str = " 🚫 Изолировано" if iso else ""
                    report += f"✅ {item.get('summary')} [{cat}]{iso_str}\n"
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=report)

        elif intent == "search_calendar":
            results = notion.search_advanced(due_after=resp.get("due_after"), due_before=resp.get("due_before"))
            if not results:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="📅 Планов нет.")
            else:
                results.sort(key=lambda x: x['date'] if x['date'] else '9999-99-99')
                msg = f"📅 **Планы:**\n"
                for r in results:
                    d_str = datetime.strptime(r['date'], "%Y-%m-%d").strftime("%d.%m") if r['date'] else ""
                    icon = "✅" if r['status'] != 'Done' else "☑️"
                    msg += f"{icon} {r['title']} ({d_str})\n"
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=msg)

        elif intent == "search_knowledge":
            results = notion.search_advanced(text_query=resp.get("query_text"))
            if not results:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="🔍 Ничего не найдено.")
            else:
                top_page = results[0]
                content = notion.get_page_content(top_page['id'])
                answer = llm.summarize_answer(full_text, content, top_page['title'])
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=f"📖 **{top_page['title']}**:\n{answer}")

        elif intent == "update_status":
             res = notion.update_status(resp.get("target_task"), resp.get("new_status"))
             await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=res)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔥 System Error: {e}")
        print(e)

if __name__ == '__main__':
    keep_alive() 
    
    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    # Передаем обновленные функции тихих отчетов!
    scheduler.add_job(scheduled_janitor_job, 'cron', hour=4, minute=0)
    scheduler.add_job(scheduled_analyst_job, 'cron', hour=4, minute=30)
    scheduler.start()

    # post_init добавляет меню команд
    application = ApplicationBuilder().token(config.TELEGRAM_TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('clean', cmd_clean))
    application.add_handler(CommandHandler('analyze', cmd_analyze))
    application.add_handler(CommandHandler('orphans', cmd_orphans))
    
    # Обработчик кнопок меню (Текст)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    # Обработчик голоса
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    print("Бот V28 (Security + UI) запущен!")
    application.run_polling()
