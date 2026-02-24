from __future__ import annotations

import threading

from bot.db import DB, Vacancy
from bot.hh import HHClient
from bot.scoring import Scorer


class ResearchService:
    def __init__(self, db: DB, hh: HHClient, scorer: Scorer) -> None:
        self.db = db
        self.hh = hh
        self.scorer = scorer
        self._lock = threading.Lock()

    def run_now(self, tg_user_id: int) -> tuple[bool, int]:
        if not self._lock.acquire(blocking=False):
            return False, 0
        try:
            self.db.ensure_user(tg_user_id)
            inserted = 0
            weights = self.db.get_weights(tg_user_id)
            for row in self.hh.fetch():
                if row["area"].lower() != "москва" and int(row["remote_flag"]) == 0:
                    continue
                vacancy_id = self.db.upsert_vacancy(row)
                vac = Vacancy(
                    id=vacancy_id,
                    source=row["source"],
                    source_vacancy_id=row["source_vacancy_id"],
                    url=row["url"],
                    employer_id=row["employer_id"],
                    employer_name=row["employer_name"],
                    title=row["title"],
                    area=row["area"],
                    remote_flag=row["remote_flag"],
                    salary_from=row["salary_from"],
                    salary_to=row["salary_to"],
                    currency=row["currency"],
                    published_at=row["published_at"],
                    description_text=row["description_text"],
                    skills_text=row["skills_text"],
                    cluster_id=row["cluster_id"],
                )
                score = self.scorer.score(vac, weights).score
                if score <= 0:
                    continue
                self.db.add_to_queue(tg_user_id, vacancy_id, score)
                inserted += 1
            return True, inserted
        finally:
            self._lock.release()
