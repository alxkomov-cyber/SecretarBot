import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")
KNOWLEDGE_DB_ID = os.getenv("KNOWLEDGE_DB_ID", None)
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")
