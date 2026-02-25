# wvacancies bot

Telegram-бот для подбора вакансий с обучением по действиям пользователя.

## Запуск

1. Создайте `.env`:

```env
BOT_TOKEN=...
DATABASE_PATH=bot.db
MIN_SCORE_TO_QUEUE=58
```

2. Установите зависимости и запустите:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Поддерживаемые команды

- `/start`
- `/queue`
- `/now` (`/research`)
- `/filters`
- `/blacklist`
