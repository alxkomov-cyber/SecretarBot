import requests
from notion_client import Client
import config
from datetime import datetime, timedelta

notion = Client(auth=config.NOTION_TOKEN)

def safe_get(data, path_list):
    current = data
    for key in path_list:
        if isinstance(current, dict):
            current = current.get(key)
        else: return None
        if current is None: return None
    return current

def get_page_content(page_id):
    try:
        blocks = notion.blocks.children.list(block_id=page_id)
        content =[]
        for block in blocks.get("results"):
            b_type = block.get("type")
            text_list = safe_get(block,[b_type, "rich_text"])
            if text_list:
                text = "".join([t.get("plain_text", "") for t in text_list])
                if text: content.append(text)
        return "\n".join(content)
    except: return ""

def create_task(title, category="Входящие", due_date=None, content_text=None, tags=None, is_isolated=False):
    if not category: category = "Входящие"
    if not tags: tags = []
    if not title: title = content_text[:40] + "..." if content_text else "Новая заметка"

    tag_objs =[{"name": t} for t in tags]

    new_page = {
        "parent": {"database_id": config.NOTION_DB_ID},
        "properties": {
            "Задача": {"title":[{"text": {"content": title}}]},
            "Категория": {"select": {"name": category}},
            "Теги": {"multi_select": tag_objs},
            "Изолированно": {"checkbox": is_isolated}
        }
    }
    if due_date:
        new_page["properties"]["Дата"] = {"date": {"start": due_date}}
    
    final_content = content_text if content_text else "..."
    new_page["children"] =[{"object": "block", "type": "paragraph", "paragraph": {"rich_text":[{"type": "text", "text": {"content": final_content[:2000]}}]}}]

    try:
        notion.pages.create(**new_page)
        return True
    except Exception as e:
        print(f"Notion Write Error: {e}")
        return False

def search_advanced(text_query=None, due_after=None, due_before=None, return_raw=False):
    url = f"https://api.notion.com/v1/databases/{config.NOTION_DB_ID}/query"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    
    and_filters =[]
    if text_query: and_filters.append({"property": "Задача", "rich_text": {"contains": text_query}})
    if due_after: and_filters.append({"property": "Дата", "date": {"on_or_after": due_after}})
    if due_before: and_filters.append({"property": "Дата", "date": {"on_or_before": due_before}})
        
    payload = {"filter": {"and": and_filters}} if and_filters else {}

    try:
        r = requests.post(url, headers=headers, json=payload)
        data = r.json()
        results =[]
        for page in data.get("results", []):
            props = page["properties"]
            title_l = safe_get(props, ["Задача", "title"])
            title = title_l[0]["plain_text"] if title_l else "Без названия"
            status = safe_get(props,["Статус", "status", "name"]) or "Unknown"
            date = safe_get(props,["Дата", "date", "start"])
            results.append({'id': page['id'], 'title': title, 'status': status, 'date': date})
        return results
    except Exception as e:
        print(f"Notion Search Error: {e}")
        return[]

def update_status(task_name_query_or_id, new_status_key="Done", exact_status=False):
    if exact_status:
        page_id, page_title, final_status = task_name_query_or_id, "System", new_status_key
    else:
        found = search_advanced(text_query=task_name_query_or_id)
        if not found: return f"🤷‍♂️ Не нашел задачу '{task_name_query_or_id}'."
        page_id, page_title = found[0]['id'], found[0]['title']
        status_map = {"Done": "Done", "Completed": "Done", "In progress": "In progress", "Not started": "Not started"}
        final_status = status_map.get(new_status_key, "Done")
    
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    try:
        requests.patch(url, headers=headers, json={"properties": {"Статус": {"status": {"name": final_status}}}})
        return True if exact_status else f"✅ Задача '**{page_title}**' -> {final_status}."
    except: return False if exact_status else "Error"

# --- ФУНКЦИИ АНАЛИТИКА И ДВОРНИКА ---
def get_overdue_tasks(today_date_str):
    url = f"https://api.notion.com/v1/databases/{config.NOTION_DB_ID}/query"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    payload = {"filter": {"and":[{"property": "Дата", "date": {"before": today_date_str}},{"property": "Статус", "status": {"does_not_equal": "Done"}},{"property": "Статус", "status": {"does_not_equal": "Archived"}}]}}
    try:
        data = requests.post(url, headers=headers, json=payload).json()
        results =[]
        for page in data.get("results",[]):
            tags_data = safe_get(page["properties"],["Теги", "multi_select"]) or[]
            results.append({'id': page['id'], 'tags': [t["name"] for t in tags_data]})
        return results
    except: return[]

def update_task_overdue(page_id, new_date, tags_list):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    try:
        r = requests.patch(url, headers=headers, json={"properties": {"Дата": {"date": {"start": new_date}}, "Теги": {"multi_select":[{"name": t} for t in tags_list]}}})
        return r.status_code == 200
    except: return False

def get_tasks_to_archive(cutoff_date_iso):
    url = f"https://api.notion.com/v1/databases/{config.NOTION_DB_ID}/query"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    payload = {"filter": {"and":[{"property": "Статус", "status": {"equals": "Done"}},{"property": "Изменено", "last_edited_time": {"before": cutoff_date_iso}}]}}
    try:
        data = requests.post(url, headers=headers, json=payload).json()
        return [{'id': page['id']} for page in data.get("results",[])]
    except: return[]


# ========================================================
# О Б Н О В Л Е Н Н Ы Е   Ф У Н К Ц И И   (ФИЛЬТР КАТЕГОРИЙ)
# ========================================================

def get_unprocessed_ideas(days_limit=7):
    url = f"https://api.notion.com/v1/databases/{config.NOTION_DB_ID}/query"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    cutoff_date = (datetime.utcnow() - timedelta(days=days_limit)).isoformat() + "Z"
    
    payload = {
        "filter": {
            "and":[
                # Берем все категории, КРОМЕ "Покупки"
                {"property": "Категория", "select": {"does_not_equal": "Покупки"}},
                {"property": "Обработано ИИ", "checkbox": {"equals": False}},
                {"property": "Изолированно", "checkbox": {"equals": False}},
                {"property": "Дата создания", "created_time": {"on_or_after": cutoff_date}}
            ]
        }
    }
    try:
        data = requests.post(url, headers=headers, json=payload).json()
        ideas =[]
        for page in data.get("results",[]):
            title_l = safe_get(page["properties"], ["Задача", "title"])
            title = title_l[0]["plain_text"] if title_l else "Без названия"
            ideas.append({"id": page["id"], "title": title})
        return ideas
    except Exception as e: 
        print(f"Error get_unprocessed_ideas: {e}")
        return[]

def get_orphan_ideas():
    """Ищет неизолированные идеи без дат и связей (КРОМЕ Покупок)"""
    url = f"https://api.notion.com/v1/databases/{config.NOTION_DB_ID}/query"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    payload = {
        "filter": {
            "and":[
                # Тоже исключаем покупки
                {"property": "Категория", "select": {"does_not_equal": "Покупки"}},
                {"property": "Дата", "date": {"is_empty": True}},
                {"property": "Обработано ИИ", "checkbox": {"equals": False}},
                {"property": "Изолированно", "checkbox": {"equals": False}}
            ]
        }
    }
    try:
        data = requests.post(url, headers=headers, json=payload).json()
        results = []
        for page in data.get("results",[]):
            title_l = safe_get(page["properties"], ["Задача", "title"])
            title = title_l[0]["plain_text"] if title_l else "Без названия"
            results.append({"title": title, "url": page.get("url")})
        return results
    except Exception as e:
        print(f"Error get_orphan_ideas: {e}")
        return[]

# ========================================================

def mark_as_processed(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    requests.patch(url, headers=headers, json={"properties": {"Обработано ИИ": {"checkbox": True}}})

def create_knowledge_record(title, content, tags, source_ids):
    url = "https://api.notion.com/v1/pages"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    payload = {
        "parent": {"database_id": config.KNOWLEDGE_DB_ID},
        "properties": {
            "Name": {"title":[{"text": {"content": title}}]},
            "Текст": {"rich_text":[{"text": {"content": content[:2000]}}]},
            "Теги": {"multi_select":[{"name": t} for t in tags]},
            "Источники": {"relation":[{"id": sid} for sid in source_ids]}
        }
    }
    try:
        r = requests.post(url, headers=headers, json=payload)
        if r.status_code == 200:
            return r.json().get("url")
        return None
    except: return None