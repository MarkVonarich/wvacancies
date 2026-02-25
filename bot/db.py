from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


UTC = timezone.utc


@dataclass
class Vacancy:
    id: int
    source: str
    source_vacancy_id: str
    url: str
    employer_id: str | None
    employer_name: str
    title: str
    area: str
    remote_flag: int
    salary_from: int | None
    salary_to: int | None
    currency: str | None
    published_at: str
    description_text: str
    skills_text: str
    cluster_id: str
    fetched_at: str | None = None
    fingerprint: str | None = None


class DB:
    def __init__(self, path: str) -> None:
        self.path = path
        self.init_db()

    @contextmanager
    def conn(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    tg_user_id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    settings_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS vacancies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    source_vacancy_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    employer_id TEXT,
                    employer_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    area TEXT NOT NULL,
                    remote_flag INTEGER NOT NULL DEFAULT 0,
                    salary_from INTEGER,
                    salary_to INTEGER,
                    currency TEXT,
                    published_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    description_text TEXT NOT NULL,
                    skills_text TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    cluster_id TEXT NOT NULL,
                    UNIQUE(source, source_vacancy_id)
                );
                CREATE TABLE IF NOT EXISTS user_queue (
                    tg_user_id INTEGER NOT NULL,
                    vacancy_id INTEGER NOT NULL,
                    score INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    shown_at TEXT,
                    PRIMARY KEY (tg_user_id, vacancy_id)
                );
                CREATE TABLE IF NOT EXISTS user_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_user_id INTEGER NOT NULL,
                    vacancy_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    scope TEXT,
                    reason_code TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    expires_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_state (
                    tg_user_id INTEGER PRIMARY KEY,
                    weights_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def ensure_user(self, tg_user_id: int) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO users(tg_user_id, created_at) VALUES(?,?)",
                (tg_user_id, datetime.now(UTC).isoformat()),
            )

    def upsert_vacancy(self, row: dict[str, Any]) -> int:
        with self.conn() as c:
            c.execute(
                """
                INSERT INTO vacancies(source, source_vacancy_id, url, employer_id, employer_name, title, area, remote_flag,
                  salary_from, salary_to, currency, published_at, fetched_at, description_text, skills_text, fingerprint, cluster_id)
                VALUES(:source,:source_vacancy_id,:url,:employer_id,:employer_name,:title,:area,:remote_flag,
                  :salary_from,:salary_to,:currency,:published_at,:fetched_at,:description_text,:skills_text,:fingerprint,:cluster_id)
                ON CONFLICT(source, source_vacancy_id) DO UPDATE SET
                  url=excluded.url, employer_name=excluded.employer_name, title=excluded.title, area=excluded.area,
                  remote_flag=excluded.remote_flag, salary_from=excluded.salary_from, salary_to=excluded.salary_to,
                  currency=excluded.currency, published_at=excluded.published_at, fetched_at=excluded.fetched_at,
                  description_text=excluded.description_text, skills_text=excluded.skills_text,
                  fingerprint=excluded.fingerprint, cluster_id=excluded.cluster_id
                """,
                row,
            )
            saved = c.execute(
                "SELECT id FROM vacancies WHERE source=? AND source_vacancy_id=?",
                (row["source"], row["source_vacancy_id"]),
            ).fetchone()
            return int(saved[0])

    def add_to_queue(self, tg_user_id: int, vacancy_id: int, score: int) -> bool:
        with self.conn() as c:
            existing = c.execute(
                "SELECT status FROM user_queue WHERE tg_user_id=? AND vacancy_id=?",
                (tg_user_id, vacancy_id),
            ).fetchone()
            if existing and existing["status"] == "acted":
                return False
            c.execute(
                """
                INSERT INTO user_queue(tg_user_id, vacancy_id, score, status) VALUES(?,?,?,'new')
                ON CONFLICT(tg_user_id, vacancy_id) DO UPDATE SET
                    score = excluded.score,
                    status = 'new'
                """,
                (tg_user_id, vacancy_id, score),
            )
            return True


    def reset_queue(self, tg_user_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM user_queue WHERE tg_user_id=? AND status!='acted'", (tg_user_id,))

    def next_queue_item(self, tg_user_id: int) -> Vacancy | None:
        with self.conn() as c:
            row = c.execute(
                """
                SELECT v.*
                FROM user_queue q
                JOIN vacancies v ON v.id = q.vacancy_id
                WHERE q.tg_user_id=? AND q.status IN ('new','shown')
                ORDER BY CASE WHEN q.status='new' THEN 0 ELSE 1 END, q.score DESC, v.published_at DESC
                LIMIT 1
                """,
                (tg_user_id,),
            ).fetchone()
            if not row:
                return None
            c.execute(
                "UPDATE user_queue SET status='shown', shown_at=? WHERE tg_user_id=? AND vacancy_id=?",
                (datetime.now(UTC).isoformat(), tg_user_id, row["id"]),
            )
            return Vacancy(**dict(row))

    def mark_acted(self, tg_user_id: int, vacancy_id: int) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE user_queue SET status='acted' WHERE tg_user_id=? AND vacancy_id=?",
                (tg_user_id, vacancy_id),
            )

    def record_action(
        self,
        tg_user_id: int,
        vacancy_id: int,
        action_type: str,
        scope: str | None = None,
        reason_code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO user_actions(tg_user_id,vacancy_id,action_type,scope,reason_code,payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    tg_user_id,
                    vacancy_id,
                    action_type,
                    scope,
                    reason_code,
                    json.dumps(payload or {}, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def add_blacklist(self, tg_user_id: int, kind: str, value: str, days: int | None = None) -> None:
        expires = None
        if days:
            expires = (datetime.now(UTC) + timedelta(days=days)).isoformat()
        with self.conn() as c:
            c.execute(
                "INSERT INTO user_blacklist(tg_user_id, kind, value, expires_at, created_at) VALUES(?,?,?,?,?)",
                (tg_user_id, kind, value.lower(), expires, datetime.now(UTC).isoformat()),
            )

    def list_blacklist(self, tg_user_id: int) -> list[sqlite3.Row]:
        with self.conn() as c:
            return c.execute(
                "SELECT id, kind, value, expires_at FROM user_blacklist WHERE tg_user_id=? ORDER BY created_at DESC",
                (tg_user_id,),
            ).fetchall()

    def get_weights(self, tg_user_id: int) -> dict[str, float]:
        with self.conn() as c:
            row = c.execute("SELECT weights_json FROM model_state WHERE tg_user_id=?", (tg_user_id,)).fetchone()
            if not row:
                return {"positive": 1.0, "negative": 1.0}
            return json.loads(row[0])

    def save_weights(self, tg_user_id: int, weights: dict[str, float]) -> None:
        with self.conn() as c:
            c.execute(
                """
                INSERT INTO model_state(tg_user_id, weights_json, updated_at) VALUES(?,?,?)
                ON CONFLICT(tg_user_id) DO UPDATE SET weights_json=excluded.weights_json, updated_at=excluded.updated_at
                """,
                (tg_user_id, json.dumps(weights), datetime.now(UTC).isoformat()),
            )

    def find_similar(self, vacancy: Vacancy, days: int = 60) -> list[int]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT id FROM vacancies WHERE cluster_id=? AND published_at >= datetime('now', ?)",
                (vacancy.cluster_id, f"-{days} days"),
            ).fetchall()
            return [int(r[0]) for r in rows]


    def is_blacklisted(self, tg_user_id: int, vacancy: Vacancy) -> bool:
        text = f"{vacancy.title} {vacancy.description_text} {vacancy.skills_text}".lower()
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT kind, value
                FROM user_blacklist
                WHERE tg_user_id=? AND (expires_at IS NULL OR expires_at > ?)
                """,
                (tg_user_id, datetime.now(UTC).isoformat()),
            ).fetchall()

        for row in rows:
            kind = row["kind"]
            value = (row["value"] or "").lower()
            if kind == "keyword" and value and value in text:
                return True
            if kind == "company" and value and value in vacancy.employer_name.lower():
                return True
            if kind == "title" and value and value in vacancy.title.lower():
                return True
            if kind == "cluster" and value and value == (vacancy.cluster_id or "").lower():
                return True
        return False
    def apply_queue_scope(self, tg_user_id: int, vacancy_ids: list[int]) -> None:
        if not vacancy_ids:
            return
        placeholders = ",".join("?" for _ in vacancy_ids)
        with self.conn() as c:
            c.execute(
                f"UPDATE user_queue SET status='acted' WHERE tg_user_id=? AND vacancy_id IN ({placeholders}) AND status != 'acted'",
                [tg_user_id, *vacancy_ids],
            )
