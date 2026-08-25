import json
import re
from groq import Groq
import config
import prompts

client = Groq(api_key=config.GROQ_API_KEY)
MODEL_NAME = "qwen/qwen3.6-27b" # Новая модель

def clean_llm_output(text):
    """Вырезает теги <think> и очищает Markdown"""
    if not text: return ""
    # Вырезаем всё между <think> и </think>
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = text.strip()
    # Убираем форматирование ```json если ИИ его добавил
    if text.startswith("```json"): text = text[7:]
    if text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    return text.strip()

def analyze_text(text):
    """Классифицирует намерение и извлекает данные"""
    try:
        system_msg = prompts.get_system_prompt()
        
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": text}
            ],
            model=MODEL_NAME,
            response_format={"type": "json_object"},
            max_tokens=4096 # Лимит
        )
        
        raw_response = chat_completion.choices[0].message.content
        cleaned_response = clean_llm_output(raw_response)
        
        return json.loads(cleaned_response)
    except Exception as e:
        print(f"LLM Error: {e}")
        return {"intent": "error", "error": str(e)}

def summarize_answer(query, context_text, title):
    """Генерирует ответ на вопрос по найденному тексту"""
    try:
        ans_prompt = f"""Пользователь задал вопрос: {query}
Вот текст найденной заметки '{title}':
{context_text[:5000]}

Ответь на вопрос, используя информацию из заметки.
ВНИМАНИЕ: СТРОГО ЗАПРЕЩЕНО использовать теги <think>, писать свои рассуждения или вводные фразы. Пиши только готовый ответ!
"""
        res = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Ты — вежливый ассистент."},
                {"role": "user", "content": ans_prompt}
            ],
            model=MODEL_NAME,
            temperature=0.2,
            max_tokens=4096
        )
        
        raw_response = res.choices[0].message.content
        return clean_llm_output(raw_response)
    except Exception as e:
        return "Ошибка генерации ответа."

def synthesize_knowledge(ideas_json_str):
    """Анализирует список идей и объединяет связанные"""
    sys_prompt = """Ты — Аналитик Базы Знаний.
Твоя задача — найти связи между разрозненными заметками и объединить их в статьи.
Ищи заметки об одном проекте или теме. Одиночные идеи игнорируй.

ВНИМАНИЕ: СТРОГО ЗАПРЕЩЕНО выводить свои рассуждения, теги <think> и комментарии. Выведи ТОЛЬКО чистый JSON.

Формат ответа СТРОГО JSON:
{
  "clusters":[
    {
       "title": "Синтезированный заголовок",
       "content": "Сводный текст...",
       "tags": ["тег1", "тег2"],
       "source_ids":["СТРОГО ТОЧНЫЕ 'id' ИЗ ВХОДНЫХ ДАННЫХ"]
    }
  ]
}
Если связей нет, верни {"clusters":[]}.
"""
    try:
        prompt = f"Проанализируй заметки:\n{ideas_json_str}"
        res = client.chat.completions.create(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt}
            ],
            model=MODEL_NAME,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=4096
        )
        
        raw_response = res.choices[0].message.content
        cleaned_response = clean_llm_output(raw_response)
        
        return json.loads(cleaned_response)
    except Exception as e:
        print(f"Error synthesize: {e}")
        return {"clusters":[]}
