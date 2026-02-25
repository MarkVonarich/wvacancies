from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_path: str = os.getenv("DATABASE_PATH", "bot.db")
    hh_base_url: str = os.getenv("HH_BASE_URL", "https://api.hh.ru")
    min_score_to_queue: int = int(os.getenv("MIN_SCORE_TO_QUEUE", "58"))



def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is missing. Add BOT_TOKEN in .env before starting bot.")
    return Settings(bot_token=token)
