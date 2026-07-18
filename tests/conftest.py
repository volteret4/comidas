import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-token-not-real")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")
os.environ.setdefault("RADICALE_URL", "https://example.invalid")
os.environ.setdefault("RADICALE_USERNAME", "test")
os.environ.setdefault("RADICALE_PASSWORD", "test")
os.environ.setdefault("DB_PATH", ":memory:")
