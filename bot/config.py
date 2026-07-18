from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_chat_id: int
    radicale_url: str
    radicale_username: str
    radicale_password: str
    radicale_calendar_name: str
    db_path: str
    weekly_job_day: str
    weekly_job_time: str
    tz: str
    gemini_api_key: str | None
    gemini_model: str

    @classmethod
    def from_env(cls) -> "Config":
        def require(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"Falta la variable de entorno obligatoria: {name}")
            return value

        return cls(
            telegram_bot_token=require("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=int(require("TELEGRAM_CHAT_ID")),
            radicale_url=require("RADICALE_URL"),
            radicale_username=require("RADICALE_USERNAME"),
            radicale_password=require("RADICALE_PASSWORD"),
            radicale_calendar_name=os.environ.get("RADICALE_CALENDAR_NAME", "Turnos"),
            db_path=os.environ.get("DB_PATH", "data/comidas.db"),
            weekly_job_day=os.environ.get("WEEKLY_JOB_DAY", "SUN"),
            weekly_job_time=os.environ.get("WEEKLY_JOB_TIME", "20:00"),
            tz=os.environ.get("TZ", "Europe/Madrid"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
        )


config = Config.from_env()
