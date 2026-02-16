from dotenv import load_dotenv
load_dotenv()  # Must be called before reading env vars

import os


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {'true', 'on', '1', 'yes'}


def env_int(name, default=0):
    value = os.environ.get(name)
    if value is None or value.strip() == '':
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name, default=0.0):
    value = os.environ.get(name)
    if value is None or value.strip() == '':
        return default
    try:
        return float(value)
    except ValueError:
        return default


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-please-change'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = env_bool('MAIL_USE_TLS', True)
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    NEA_API_KEY = os.environ.get('NEA_API_KEY')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE') or 'Lax'
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = os.environ.get('REMEMBER_COOKIE_SAMESITE') or 'Lax'
    REMEMBER_COOKIE_SECURE = False
    WTF_CSRF_TIME_LIMIT = int(os.environ.get('WTF_CSRF_TIME_LIMIT') or 3600)
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH') or (2 * 1024 * 1024))
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL')
    OPENAI_CHAT_MODEL = os.environ.get('OPENAI_CHAT_MODEL') or 'gpt-4o-mini'
    OPENAI_EMBED_MODEL = os.environ.get('OPENAI_EMBED_MODEL') or 'text-embedding-3-small'
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
    SUPABASE_DOCS_TABLE = os.environ.get('SUPABASE_DOCS_TABLE') or 'pool_documents'
    SUPABASE_MATCH_FUNCTION = os.environ.get('SUPABASE_MATCH_FUNCTION') or 'match_documents'
    CHATBOT_TOP_K = env_int('CHATBOT_TOP_K', 3)
    CHATBOT_MIN_SCORE = env_float('CHATBOT_MIN_SCORE', 0.65)
    CHATBOT_MAX_CONTEXT_CHARS = env_int('CHATBOT_MAX_CONTEXT_CHARS', 4000)

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or os.environ.get('SQLALCHEMY_DATABASE_URI') or 'sqlite:///dev.db'

class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or os.environ.get('SQLALCHEMY_DATABASE_URI')
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = 'https'

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
