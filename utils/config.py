import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram
    API_ID = int(os.getenv('TELEGRAM_API_ID'))
    API_HASH = os.getenv('TELEGRAM_API_HASH')
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    SESSION_NAME = 'chunwu_short_bot'
    TARGET_GROUP_ID = int(os.getenv('TARGET_GROUP_ID', 0))
    
    # Fintel
    FINTEL_USER = os.getenv('FINTEL_USERNAME')
    FINTEL_PASS = os.getenv('FINTEL_PASSWORD')
    
    # Paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    PROFILE_DIR = os.path.join(BASE_DIR, "fintel_profile")
    CSV_OUTPUT = os.path.join(BASE_DIR, "short_squeeze_top10.csv")

config = Config()
