import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

class Config:
    # Telegram
    API_ID = int(os.getenv('TELEGRAM_API_ID'))
    API_HASH = os.getenv('TELEGRAM_API_HASH')
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    DATABASE_URL = os.getenv('DATABASE_URL')
    SESSION_NAME = 'chunwu_short_bot'
    TARGET_GROUP_ID = int(os.getenv('TARGET_GROUP_ID', 0))
    
    # Fintel
    FINTEL_USER = os.getenv('FINTEL_USERNAME')
    FINTEL_PASS = os.getenv('FINTEL_PASSWORD')

    # Moomoo OpenD
    MOOMOO_HOST = os.getenv('MOOMOO_HOST', '127.0.0.1')
    MOOMOO_PORT = int(os.getenv('MOOMOO_PORT', '11111'))
    MOOMOO_PASSWORD = os.getenv('MOOMOO_PASSWORD', '')
    MOOMOO_ACC_ID = int(os.getenv('MOOMOO_ACC_ID', '0') or 0)

    # TAMU OpenAI-compatible chat endpoint
    TAMU_API_KEY = os.getenv('TAMU_API_KEY', '')
    TAMU_API_ENDPOINT = os.getenv(
        'TAMU_API_ENDPOINT',
        'https://chat-api.tamu.ai/openai/chat/completions',
    )
    TAMU_MODEL = os.getenv('TAMU_MODEL', 'protected.Claude Sonnet 4.6')
    TAMU_MODEL_FALLBACKS = [
        model.strip()
        for model in os.getenv(
            'TAMU_MODEL_FALLBACKS',
            'protected.gpt-5.4,protected.gpt-5.2,protected.gpt-5.1,protected.gpt-5,'
            'protected.Claude Opus 4.6,protected.Claude Sonnet 4.5,protected.gpt-4.1,'
            'protected.gpt-4o,protected.gemini-2.5-pro,protected.gemini-2.5-flash',
        ).split(',')
        if model.strip()
    ]
    TAMU_ALT_API_KEY = os.getenv('TAMU_ALT_API_KEY', '')
    TAMU_ALT_BASE_URL = os.getenv('TAMU_ALT_BASE_URL', 'https://tti-api.tamus.ai')
    TAMU_DAILY_CREDIT_USD = float(os.getenv('TAMU_DAILY_CREDIT_USD', '0') or 0)
    TAMU_ALT_DAILY_CREDIT_USD = float(os.getenv('TAMU_ALT_DAILY_CREDIT_USD', '0') or 0)
    
    # Paths
    BASE_DIR = BASE_DIR
    PROFILE_DIR = os.path.join(BASE_DIR, "fintel_profile")
    CSV_OUTPUT = os.path.join(BASE_DIR, "short_squeeze_top10.csv")

config = Config()
