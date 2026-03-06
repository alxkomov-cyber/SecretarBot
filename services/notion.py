import requests
from notion_client import Client
import config

notion = Client(auth=config.NOTION_TOKEN)

# Вспомогательная функция для безопасного чтения
def safe_get(data, path_list):
    current = data
    for key in path_list:
        if isinstance(current, dict):
            current = current.get(key)
        else: return None
        if current is None: return None
    return current

def get_page_content(page_id):
    """Получает текст внутри страницы"""
    try:
        blocks = notion.blocks.children.list(block_id=page_id)
        content = []
        for block in blocks.get("results"):
            b_type = block.get("type")
            text_list = safe_get(block, [b_type, "rich_text"])
            if text_list:
                text = "".join([t.get("plain_text", "") for t in text_list])
                if text: content.append(text)
        return "\n".join(content)
    except Exception as e:
        return ""

def create_task(title, category="Входящие", due_date=None, content_text=None, tags=None):
    if not category: category = "Входящие"
    if not tags: tags = []
    
    # Защита от пустого заголовка
    if not title:
        title = "Новая заметка"
        if content_text: title = content_text[:40] + "..."

    tag_objs = [{"name": t} for t in tags]

    new_page = {
        "parent": {"database_id": config.NOTION_DB_ID},
        "properties": {
            "Задача": {"title": [{"text": {"content": title}}]},
            "Категория": {"select": {"name": category}},
            "Теги": {"multi_select": tag_objs}
        }
    }
    if due_date:
        new_page["properties"]["Дата"] = {"date": {"start": due_date}}
    
    final_content = content_text if content_text else "..."
    new_page["children"] = [{
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": final_content[:2000]}}]}
    }]

    try:
        notion.pages.create(**new_page)
        return True
    except Exception as e:
        print(f"Notion Write Error: {e}")
        return False

def search_advanced(text_query=None, due_after=None, due_before=None, return_raw=False):
    url = f"https://api.notion.com/v1/databases/{config.NOTION_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {config.NOTION_TOKEN}", 
        "Notion-Version": "2022-06-28", 
        "Content-Type": "application/json"
    }
    
    and_filters =[]
    if text_query:
        and_filters.append({"property": "Задача", "rich_text": {"contains": text_query}})
    if due_after:
        and_filters.append({"property": "Дата", "date": {"on_or_after": due_after}})
    if due_before:
        and_filters.append({"property": "Дата", "date": {"on_or_before": due_before}})
        
    payload = {}
    if and_filters: payload["filter"] = {"and": and_filters} if len(and_filters) > 1 else and_filters[0]

    try:
        r = requests.post(url, headers=headers, json=payload)
        data = r.json()
        results = []
        for page in data.get("results",[]):
            props = page["properties"]
            
            # --- ИСПРАВЛЕННОЕ ИЗВЛЕЧЕНИЕ ЗАГОЛОВКА КАК В V25 ---
            title_l = safe_get(props, ["Задача", "title"])
            title = title_l[0]["plain_text"] if title_l else "Без названия"
            # --------------------------------------------------
            
            status = safe_get(props, ["Статус", "status", "name"]) or "Unknown"
            date = safe_get(props, ["Дата", "date", "start"])
            
            results.append({'id': page['id'], 'title': title, 'status': status, 'date': date})
        return results
    except Exception as e:
        print(f"Notion Search Error: {e}")
        return

# --- ФУНКЦИИ ДЛЯ АГЕНТА "ДВОРНИК" ---

def get_overdue_tasks(today_date_str):
    """Ищет задачи с датой в прошлом, которые не Done и не Archived"""
    url = f"https://api.notion.com/v1/databases/{config.NOTION_DB_ID}/query"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    
    payload = {
        "filter": {
            "and":[
                {"property": "Дата", "date": {"before": today_date_str}},
                {"property": "Статус", "status": {"does_not_equal": "Done"}},
                {"property": "Статус", "status": {"does_not_equal": "Archived"}}
            ]
        }
    }
    
    try:
        r = requests.post(url, headers=headers, json=payload)
        data = r.json()
        results =[]
        for page in data.get("results", []):
            props = page["properties"]
            # ИСПРАВЛЕНИЕ: Передаем 2 аргумента, а пустой список ставим через or
            tags_data = safe_get(props,["Теги", "multi_select"]) or []
            tags = [t["name"] for t in tags_data]
            results.append({'id': page['id'], 'tags': tags})
        return results
    except Exception as e:
        print(f"Error get_overdue_tasks: {e}")
        return

def update_task_overdue(page_id, new_date, tags_list):
    """Обновляет дату и теги просроченной задачи"""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    
    tag_objs = [{"name": t} for t in tags_list]
    payload = {
        "properties": {
            "Дата": {"date": {"start": new_date}},
            "Теги": {"multi_select": tag_objs}
        }
    }
    try:
        r = requests.patch(url, headers=headers, json=payload)
        return r.status_code == 200
    except:
        return False

def get_tasks_to_archive(cutoff_date_iso):
    """Ищет задачи Done, которые не менялись дольше cutoff_date"""
    url = f"https://api.notion.com/v1/databases/{config.NOTION_DB_ID}/query"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    
    payload = {
        "filter": {
            "and":[
                {"property": "Статус", "status": {"equals": "Done"}},
                {"property": "Изменено", "last_edited_time": {"before": cutoff_date_iso}}
            ]
        }
    }
    try:
        r = requests.post(url, headers=headers, json=payload)
        data = r.json()
        return [{'id': page['id']} for page in data.get("results",[])]
    except Exception as e:
        print(f"Error get_tasks_to_archive: {e}")
        return[]

# Мы также слегка обновим старую update_status, добавив параметр exact_status
def update_status(task_name_query_or_id, new_status_key="Done", exact_status=False):
    """exact_status=True означает, что мы передаем ID страницы и точное название статуса (для скриптов)"""
    if exact_status:
        page_id = task_name_query_or_id
        final_status = new_status_key
        page_title = "System Update"
    else:
        found = search_advanced(text_query=task_name_query_or_id)
        if not found: return f"🤷‍♂️ Не нашел задачу '{task_name_query_or_id}'."
        page_id = found[0]['id']
        page_title = found[0]['title']
        status_map = {"Done": "Done", "Completed": "Done", "In progress": "In progress", "Not started": "Not started"}
        final_status = status_map.get(new_status_key, "Done")
    
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    payload = {"properties": {"Статус": {"status": {"name": final_status}}}}
    
    try:
        requests.patch(url, headers=headers, json=payload)
        return True if exact_status else f"✅ Задача '**{page_title}**' -> {final_status}."
    except Exception as e:
        return False if exact_status else f"Error: {e}"