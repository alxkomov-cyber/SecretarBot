import asyncio
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from apscheduler.schedulers.background import BackgroundScheduler
from agents import janitor

# Импортируем наши новые модули
import config
from services import voice, llm, notion
from datetime import datetime

# --- СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "I am alive"
def run_http(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): t = Thread(target=run_http); t.start()

# --- ЛОГИКА БОТА ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Бот V26 (Modular Architecture) готов.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🎧...", disable_notification=True)

    # 1. Голос -> Текст
    full_text = await voice.transcribe_voice(update, context)
    if not full_text:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="❌ Ошибка распознавания.")
        return

    # 2. Текст -> Намерение (JSON)
    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="🧠 Анализ...")
    resp = llm.analyze_text(full_text)
    intent = resp.get("intent")

    # 3. Маршрутизация
    try:
        if intent == "save":
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="📝 Сохраняю...")
            items = resp.get("items", [])
            report = f"📝 **Текст:** {full_text}\n\n"
            
            for item in items:
                cat = item.get("category") or "Входящие"
                details = item.get("details")
                if not details or len(details) < 5: details = full_text # Fallback
                
                if notion.create_task(item.get("summary"), cat, item.get("date"), details, item.get("tags")):
                    tags_d = f" 🏷 {', '.join(item.get('tags'))}" if item.get('tags') else ""
                    date_d = f" 📅 {item.get('date')}" if item.get('date') else ""
                    report += f"✅ {item.get('summary')} [{cat}]{tags_d}{date_d}\n"
            
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=report)

        elif intent == "search_calendar":
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="🔍 Проверяю календарь...")
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
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=f"🧠 Ищу '{resp.get('query_text')}'...")
            
            # Внимание: обращаемся к search_advanced из services/notion.py
            found = notion.search_advanced(text_query=resp.get("query_text"), return_raw=True)
            
            if not found:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=f"🔍 Заголовок со словом '{resp.get('query_text')}' не найден.")
            else:
                top_page = found[0]
                content = notion.get_page_content(top_page['id'])
                
                # Вызываем обновленную функцию из llm.py
                answer = llm.summarize_answer(full_text, content, top_page['title'])
                
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id, 
                    message_id=status_msg.message_id, 
                    text=f"📖 **{top_page['title']}**:\n{answer}"
                )

        elif intent == "update_status":
             res = notion.update_status(resp.get("target_task"), resp.get("new_status"))
             await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=res)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔥 System Error: {e}")
        print(e)

async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной вызов Дворника через команду /clean"""
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Вызываю Дворника... 🧹")
    # Поскольку это может занять пару секунд, запускаем в отдельном потоке (или просто вызываем)
    result = janitor.run_janitor()
    await context.bot.send_message(chat_id=update.effective_chat.id, text=result)

if __name__ == '__main__':
    keep_alive() 
    
    # Настройка и запуск планировщика
    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    # Запускаем дворника каждый день в 04:00 утра
    scheduler.add_job(janitor.run_janitor, 'cron', hour=4, minute=0)
    scheduler.start()
    print("⏰ Планировщик запущен (Очистка в 04:00 МСК).")

    application = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('clean', cmd_clean)) # Новая ручная команда
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    print("Бот V27 (Janitor Agent) запущен!")
    application.run_polling()