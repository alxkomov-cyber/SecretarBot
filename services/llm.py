import json
from groq import Groq
import config
import prompts

client = Groq(api_key=config.GROQ_API_KEY)

def analyze_text(text):
    """Классифицирует намерение и извлекает данные"""
    try:
        system_msg = prompts.get_system_prompt()
        
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": text}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        return json.loads(chat_completion.choices[0].message.content)
    except Exception as e:
        print(f"LLM Error: {e}")
        return {"intent": "error", "error": str(e)}

def summarize_answer(query, context_text, title):
    """Генерирует ответ на вопрос по найденному тексту (RAG)"""
    try:
        ans_prompt = f"""
Пользователь задал вопрос: {query}
Вот текст найденной заметки '{title}':
{context_text[:5000]}

Твоя задача: Ответь на вопрос пользователя, используя только информацию из этой заметки. 
Сформулируй ответ в виде полного, естественного предложения (как живой собеседник). Не отвечай просто сухими цифрами или обрывками фраз.
"""
        res = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Ты — вежливый и компетентный ассистент."},
                {"role": "user", "content": ans_prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.3 # Делаем ответы более предсказуемыми
        )
        return res.choices[0].message.content
    except Exception as e:
        return "Ошибка генерации ответа."

def synthesize_knowledge(ideas_json_str):
    """Анализирует список идей и объединяет связанные"""
    sys_prompt = """Ты — Аналитик Базы Знаний (Data Scientist).
Твоя задача — найти логические связи между разрозненными заметками и объединить их в общие концепции/статьи.
1. Ищи заметки, которые говорят об одном проекте или смежных темах (например: обе про 1С, отчеты, доработки, путешествия). Даже если связь косвенная — объединяй!
2. ИГНОРИРУЙ заметки, которые ни с чем не связаны (например, бытовые покупки).
3. Для найденной группы напиши емкое Summary (суть объединения).

Входные данные — это JSON. У каждой заметки есть 'id', 'title', 'content'.

Формат ответа СТРОГО JSON:
{
  "clusters":[
    {
       "title": "Синтезированный заголовок",
       "content": "Сводный текст, объединяющий суть...",
       "tags": ["тег1", "тег2"],
       "source_ids":["СЮДА СТРОГО СКОПИРУЙ ТОЧНЫЕ 'id' ИЗ ВХОДНЫХ ДАННЫХ"]
    }
  ]
}
Если связей нет вообще, верни {"clusters":[]}.
"""
    try:
        prompt = f"Проанализируй эти заметки и найди связи:\n{ideas_json_str}"
        res = client.chat.completions.create(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            temperature=0.2 # Понижаем фантазию, повышаем точность
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        print(f"Error synthesize: {e}")
        return {"clusters":[]}