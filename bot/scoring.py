from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from bot.db import Vacancy


@dataclass
class ScoreResult:
    score: int
    triggers_plus: list[str]
    triggers_minus: list[str]


class Scorer:
    def __init__(self, triggers_path: str) -> None:
        self.config = yaml.safe_load(Path(triggers_path).read_text())

    @staticmethod
    def _norm(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s+-]", " ", text.lower())).strip()

    def _contains(self, text: str, phrase: str) -> bool:
        return phrase.lower() in text

    def score(self, vacancy: Vacancy, weights: dict[str, float]) -> ScoreResult:
        text = self._norm(" ".join([vacancy.title, vacancy.description_text, vacancy.skills_text, vacancy.employer_name]))
        plus: list[str] = []
        minus: list[str] = []
        raw = 50.0

        for token in self.config.get("stop_words", []):
            if self._contains(text, token):
                return ScoreResult(0, [], [f"stop-word: {token}"])

        for token in self.config.get("positive_strong", []):
            if self._contains(text, token):
                raw += 10 * weights.get("positive", 1.0)
                plus.append(token)

        for token in self.config.get("positive_medium", []):
            if self._contains(text, token):
                raw += 5 * weights.get("positive", 1.0)
                plus.append(token)

        for token in self.config.get("negative_strong", []):
            if self._contains(text, token):
                raw -= 12 * weights.get("negative", 1.0)
                minus.append(token)

        for token in self.config.get("negative_medium", []):
            if self._contains(text, token):
                raw -= 6 * weights.get("negative", 1.0)
                minus.append(token)

        if vacancy.area.lower() != "москва" and vacancy.remote_flag == 0:
            raw = 0
            minus.append("geo-filter")

        return ScoreResult(max(0, min(100, int(raw))), plus[:3], minus[:2])

    def keyword_candidates(self, vacancy: Vacancy) -> list[str]:
        base = [w.strip() for w in vacancy.skills_text.split(",") if w.strip()]
        text = self._norm(vacancy.description_text)
        words = [w for w in text.split() if len(w) > 4]
        seen = set()
        out = []
        for w in [*base, *words]:
            lw = w.lower()
            if lw in seen:
                continue
            if lw in {"команда", "ответственность", "разработка"}:
                continue
            seen.add(lw)
            out.append(w)
            if len(out) >= 12:
                break
        return out[:12]
