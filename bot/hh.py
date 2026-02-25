from __future__ import annotations

import hashlib
import re
from typing import Any

import requests

from bot.config import Settings
from bot.db import DB


class HHClient:
    def __init__(self, settings: Settings, db: DB) -> None:
        self.settings = settings
        self.db = db

    def fetch(self, text: str = "аналитик", per_page: int = 30, period_days: int = 30, max_pages: int = 4) -> list[dict[str, Any]]:
        url = f"{self.settings.hh_base_url}/vacancies"
        out: list[dict[str, Any]] = []
        for page in range(max_pages):
            r = requests.get(
                url,
                params={
                    "text": text,
                    "per_page": per_page,
                    "page": page,
                    "order_by": "publication_time",
                    "period": min(30, max(1, period_days)),
                },
                timeout=20,
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            if not items:
                break
            for item in items:
                details = requests.get(f"{url}/{item['id']}", timeout=20)
                if details.status_code != 200:
                    continue
                out.append(self._normalize(details.json()))
        return out

    def fetch_many(self, queries: list[str], period_days: int = 30) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for q in queries:
            for row in self.fetch(text=q, period_days=period_days):
                key = f"{row['source']}:{row['source_vacancy_id']}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(row)
        return out

    @staticmethod
    def _txt(val: str | None) -> str:
        return re.sub(r"<[^>]+>", " ", (val or "")).strip()

    def _cluster(self, employer_id: str | None, title: str, desc: str) -> str:
        base = f"{(employer_id or '').lower()}|{title.lower()}"
        fp = hashlib.md5((base + '|' + desc[:700]).encode()).hexdigest()
        return fp[:16]

    def _normalize(self, full: dict[str, Any]) -> dict[str, Any]:
        snippet = full.get("description") or ""
        skills = ", ".join([x.get("name", "") for x in full.get("key_skills", [])])
        schedule = (full.get("schedule") or {}).get("id", "")
        area_name = (full.get("area") or {}).get("name", "")
        remote = 1 if schedule == "remote" or "удален" in snippet.lower() else 0
        title = full.get("name", "")
        desc = self._txt(snippet)
        employer = full.get("employer") or {}
        employer_id = employer.get("id")
        cluster = self._cluster(employer_id, title, desc)
        return {
            "source": "hh",
            "source_vacancy_id": str(full.get("id")),
            "url": full.get("alternate_url", ""),
            "employer_id": str(employer_id) if employer_id else None,
            "employer_name": employer.get("name", "Unknown"),
            "title": title,
            "area": area_name,
            "remote_flag": remote,
            "salary_from": (full.get("salary") or {}).get("from"),
            "salary_to": (full.get("salary") or {}).get("to"),
            "currency": (full.get("salary") or {}).get("currency"),
            "published_at": full.get("published_at", ""),
            "fetched_at": full.get("published_at", ""),
            "description_text": desc,
            "skills_text": skills,
            "fingerprint": hashlib.md5(desc.encode()).hexdigest(),
            "cluster_id": cluster,
        }
