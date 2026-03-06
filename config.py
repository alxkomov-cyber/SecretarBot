import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")

# ID базы знаний (пока заглушка, в будущем сюда впишем ID новой базы)
KNOWLEDGE_DB_ID = os.getenv("KNOWLEDGE_DB_ID", None)