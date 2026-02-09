import os
import json
import asyncio
import requests
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq
from notion_client import Client
from flask import Flask
from threading import Thread

# --- 1. СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "I am alive"
def run_http(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): t = Thread(target=run_http); t.start()

# --- 2. НАСТРОЙКИ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")

groq_client = Groq(api_key=GROQ_API_KEY)
notion = Client(auth=NOTION_TOKEN)

# --- 3. ЧТЕНИЕ NOTION ---
def get_page_content(page_id):
    try:
        blocks = notion.blocks.children.list(block_id=page_id)
        content = []
        for block in blocks.get("results"):
            b_type = block.get("type")
            if "rich_text" in block.get(b_type, {}):
                text_list = block[b_type]["rich_text"]
                text = "".join([t["plain_text"] for t in text_list])
                if text: content.append(text)
        return "\n".join(content)
    except Exception as e:
        return ""

# --- 4. ЗАПИСЬ ---
def create_notion_task(title, category="Входящие", due_date=None, content_text=None, tags=None):
    if not category: category = "Входящие"
    if not tags: tags = []
    
    # ЗАЩИТА: Если ИИ не прислал заголовок, берем первые слова текста
    if not title and content_text:
        title = content_text[:50] + "..."
    elif not title:
        title = "Новая заметка"

    tag_objs = [{"name": t} for t in tags]

    new_page = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Задача": {"title": [{"text": {"content": title}}]},
            "Категория": {"select": {"name": category}},
            "Теги": {"multi_select": tag_objs}
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
        print(f"Write Error: {e}")
        return False

# --- 5. ОБНОВЛЕНИЕ СТАТУСА ---
def update_notion_status(task_name_query, new_status_key="Done"):
    search_res = search_notion_advanced(text_query=task_name_query, return_raw=True)
    if not search_res: return f"🤷‍♂️ Не нашел задачу '{task_name_query}'."
    
    page_id = search_res[0]['id']
    page_title = search_res[0]['title']
    
    status_map = {"Done": "Done", "Completed": "Done", "In progress": "In progress", "Not started": "Not started"}
    final_status = status_map.get(new_status_key, "Done")

    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    payload = {"properties": {"Статус": {"status": {"name": final_status}}}}

    try:
        requests.patch(url, headers=headers, json=payload)
        return f"✅ Задача '**{page_title}**' -> {final_status}."
    except Exception as e:
        return f"Update Error: {e}"

# --- 6. ПОИСК ---
def search_notion_advanced(text_query=None, created_after=None, created_before=None, due_after=None, due_before=None, return_raw=False):
    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

    and_filters = []

    if text_query:
        and_filters.append({"property": "Задача", "rich_text": {"contains": text_query}})

    if created_after: and_filters.append({"property": "Дата создания", "created_time": {"on_or_after": created_after}})
    if created_before: and_filters.append({"property": "Дата создания", "created_time": {"on_or_before": created_before}})
    if due_after: and_filters.append({"property": "Дата", "date": {"on_or_after": due_after}})
    if due_before: and_filters.append({"property": "Дата", "date": {"on_or_before": due_before}})

    payload = {}
    if and_filters: payload["filter"] = {"and": and_filters} if len(and_filters) > 1 else and_filters[0]

    try:
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()
        results = []
        
        for page in data.get("results", []):
            props = page["properties"]
            p_id = page['id']
            
            title_l = props.get("Задача", {}).get("title", [])
            title = title_l[0]["plain_text"] if title_l else "Без названия"
            status = props.get("Статус", {}).get("status", {}).get("name", "Unknown")
            cat = props.get("Категория", {}).get("select", {}).get("name", "Общее")
            date_obj = props.get("Дата", {}).get("date")
            deadline = date_obj.get("start") if date_obj else None

            results.append({'id': p_id, 'title': title, 'status': status, 'date': deadline})

        return results
    except Exception as e:
        print(f"Search Error: {e}")
        return []

# --- 7. ОБРАБОТКА ГОЛОСА ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🎧...", disable_notification=True)

    try:
        file_id = update.message.voice.file_id
        new_file = await context.bot.get_file(file_id)
        ogg_file_path = f"voice_{file_id}.ogg"
        await new_file.download_to_drive(ogg_file_path)

        with open(ogg_file_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(ogg_file_path, file.read()), model="whisper-large-v3", response_format="json", language="ru"
            )
        full_text = transcription.text
        
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d (%A)")
        
        calendar_str = "КАЛЕНДАРЬ НА 30 ДНЕЙ:\n"
        for i in range(0, 31):
            f_date = now + timedelta(days=i)
            calendar_str += f"{f_date.strftime('%Y-%m-%d')} ({f_date.strftime('%A')})\n"

        # --- MEGA PROMPT V19 (Semantic Search + Intent Fix) ---
        system_prompt = f"""
        Сегодня: {today_str}.
        {calendar_str}
        
        Твоя цель: Классифицировать намерение (intent).

        1. intent="search_knowledge" (ПОИСК ИНФОРМАЦИИ):
           - Триггеры: "В каком отеле...", "Сколько стоил...", "Напомни детали...", "Что я говорил про...".
           - Если фраза "Напомни, в каком отеле..." -> это ПОИСК, а не сохранение.
           - query_text: ТЕМА ЗАМЕТКИ (Subject), а не деталь (Attribute).
             * ПЛОХО: искать "отель", "бюджет", "цена". (Таких заголовков нет).
             * ХОРОШО: искать "Казань", "Тимбилдинг", "Проект".
             * Пример: "Бюджет тимбилдинга" -> query_text="Тимбилдинг".
             * Пример: "Отель в Казани" -> query_text="Казань".

        2. intent="search_calendar" (ПОИСК ПЛАНОВ):
           - Триггеры: "Какие планы", "Список задач", "Что на неделе".
           - query_text: ВСЕГДА null.
           - dates: Используй календарь. "Ближайшая неделя" = сегодня + 7 дней.

        3. intent="save" (СОХРАНЕНИЕ):
           - Триггеры: "Напомни МНЕ СДЕЛАТЬ...", "Запиши...", "Купить...", "Надо...".
           - date: Бери БЛИЖАЙШУЮ дату из календаря.

        4. intent="update_status" (ВЫПОЛНЕНИЕ):
           - Триггеры: "Сделал", "Готово", "Отметь".

        JSON FORMAT:
        {{ "intent": "save", "items": [...] }}
        {{ "intent": "search_calendar", "query_text": null, "due_after": "...", "due_before": "..." }}
        {{ "intent": "search_knowledge", "query_text": "..." }}
        {{ "intent": "update_status", "target_task": "...", "new_status": "..." }}
        """

        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": full_text}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        
        resp = json.loads(chat_completion.choices[0].message.content)
        intent = resp.get("intent")

        # --- LOGIC ---

        if intent == "save":
            items = resp.get("items", [])
            report = f"📝 **Текст:** {full_text}\n\n"
            if items:
                report += "✅ **Сохранено:**\n"
                for item in items:
                    cat = item.get("category", "Входящие")
                    # Защита от null заголовка внутри функции create_notion_task уже есть
                    if create_notion_task(item.get("summary"), cat, item.get("date"), item.get("details"), item.get("tags")):
                        d_disp = f" 📅 {item.get('date')}" if item.get('date') else ""
                        report += f"— {item.get('summary')} [{cat}]{d_disp}\n"
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=report)

        elif intent == "update_status":
            res = update_notion_status(resp.get("target_task"), resp.get("new_status"))
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=res)

        elif intent == "search_calendar":
            # Чистый поиск по датам без слов
            found = search_notion_advanced(
                text_query=None,
                due_after=resp.get("due_after"),
                due_before=resp.get("due_before"),
                return_raw=True
            )
            if not found:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="🔍 Планов нет.")
            else:
                found.sort(key=lambda x: x['date'] if x['date'] else '9999-99-99')
                msg = f"📅 **Планы ({resp.get('due_after')} - {resp.get('due_before')}):**\n\n"
                for f in found:
                    d = f['date']
                    d_str = datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y") if d else ""
                    icon = "✅" if f['status'] != 'Done' else "☑️"
                    msg += f"{icon} **{f['title']}** — {d_str}\n"
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=msg)

        elif intent == "search_knowledge":
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=f"🧠 Ищу в заметках про '{resp.get('query_text')}'...")
            
            found = search_notion_advanced(
                text_query=resp.get("query_text"),
                return_raw=True
            )
            
            if not found:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=f"🔍 Заголовок '{resp.get('query_text')}' не найден.")
            else:
                # Берем ТОП-1 и читаем
                top_page = found[0]
                content = get_page_content(top_page['id'])
                
                ans_prompt = f"""
                Вопрос: "{full_text}"
                Заметка: "{top_page['title']}"
                Текст: {content[:5000]}
                
                Дай ответ на вопрос.
                """
                ans_res = groq_client.chat.completions.create(messages=[{"role": "user", "content": ans_prompt}], model="llama-3.3-70b-versatile")
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=f"📖 **{top_page['title']}**:\n{ans_res.choices[0].message.content}")

        if os.path.exists(ogg_file_path): os.remove(ogg_file_path)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔥 Ошибка: {e}")
        print(f"ERR: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Бот V19 (Sherlock Logic) готов.")

if __name__ == '__main__':
    keep_alive() 
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("Бот V19 запущен!")
    application.run_polling()
