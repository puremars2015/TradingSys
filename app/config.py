import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Application configuration"""
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    
    # Database
    DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
    DATABASE_PATH = os.path.join(DATA_DIR, 'trading_signals.db')

    # Trading — webhook payload 是純數值陣列，不帶商品代號，固定使用這個標的
    DEFAULT_SYMBOL = os.getenv('DEFAULT_SYMBOL', 'TXF1!')
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8505755301:AAHdjoMsV18SMBkA5IR0BPnwd7L7UWAEXxg')
    TELEGRAM_USER_ID = os.getenv('TELEGRAM_USER_ID', '732924840')
    TELEGRAM_BOT_TOKEN_2 = os.getenv('TELEGRAM_BOT_TOKEN_2', '')
    TELEGRAM_USER_ID_2 = os.getenv('TELEGRAM_USER_ID_2', '')
    
    # OpenRouter (LLM)
    OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
    OPENROUTER_API_URL = os.getenv('OPENROUTER_API_URL', 'https://openrouter.ai/api/v1/chat/completions')
    OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'minimax/MiniMax-M2.7')
    
    # Agnes AI (LLM)
    AGNES_API_KEY = os.getenv('AGNES_API_KEY', '')
    AGNES_API_URL = os.getenv('AGNES_API_URL', 'https://apihub.agnes-ai.com/v1/chat/completions')
    AGNES_MODEL = os.getenv('AGNES_MODEL', 'mini-max-m2.5')
    
    # LLM Provider: 'openrouter' or 'agnes'
    LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'openrouter')
    
    # 外資期貨未平倉（期交所）
    FOREIGN_FUTURES_ENABLED = os.getenv('FOREIGN_FUTURES_ENABLED', 'true').lower() == 'true'
    FOREIGN_FUTURES_COMMODITY = os.getenv('FOREIGN_FUTURES_COMMODITY', 'TXF')

    # 加權指數與每日成交量（證交所）
    TAIEX_ENABLED = os.getenv('TAIEX_ENABLED', 'true').lower() == 'true'

    # LINE Bot
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
    LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '')
    
    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
