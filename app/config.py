import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Загружаем ID администраторов из .env.
# Это должна быть строка с ID, разделенными запятыми (e.g., "12345,67890")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [
    int(admin_id) for admin_id in ADMIN_IDS_STR.split(",") if admin_id.strip().isdigit()
]

