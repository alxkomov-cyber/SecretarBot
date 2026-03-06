import json
from services import notion, llm

def run_analyst():
    print("🧠 Аналитик: Ищу необработанные идеи (до 7 дней)...")
    
    raw_ideas = notion.get_unprocessed_ideas(days_limit=7)
    if len(raw_ideas) < 2:
        return "🧠 Аналитик: Мало данных для поиска связей (<2 заметок)."

    ideas_for_ai =[]
    for idea in raw_ideas:
        content = notion.get_page_content(idea['id'])
        ideas_for_ai.append({"id": idea['id'], "title": idea['title'], "content": content[:2000]})

    ideas_json_str = json.dumps(ideas_for_ai, ensure_ascii=False)
    analysis_result = llm.synthesize_knowledge(ideas_json_str)
    clusters = analysis_result.get("clusters",[])
    
    if not clusters:
        return "🧠 Аналитик: Связей не найдено. Оставил заметки ждать пары."

    created_articles =[]
    processed_ids = set()

    for cluster in clusters:
        title = cluster.get("title", "Новая концепция")
        content = cluster.get("content", "")
        tags = cluster.get("tags",[])
        source_ids = cluster.get("source_ids",[])
        
        valid_ids =[sid for sid in source_ids if any(i['id'] == sid for i in raw_ideas)]
        
        if len(valid_ids) > 1:
            # Получаем URL созданной записи
            page_url = notion.create_knowledge_record(title, content, tags, valid_ids)
            if page_url:
                processed_ids.update(valid_ids)
                # Формируем Markdown ссылку
                created_articles.append(f"[{title}]({page_url})")

    for pid in processed_ids:
        notion.mark_as_processed(pid)

    if created_articles:
        result_msg = "🧠 **Аналитик создал новые статьи в Базе Знаний:**\n"
        for i, article in enumerate(created_articles, 1):
            result_msg += f"{i}. {article}\n"
    else:
        result_msg = "🧠 Аналитик отработал, но статьи не были сохранены."
        
    return result_msg