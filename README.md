# wvacancies bot

Telegram-бот для подбора вакансий с обучением по действиям пользователя.

## Запуск

1. Создайте `.env`:

```env
BOT_TOKEN=...
DATABASE_PATH=bot.db
MIN_SCORE_TO_QUEUE=70
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
- `/now [days]` (`/research [days]`), например `/now 30`
- `/filters`
- `/blacklist`
- `/period` (inline-меню: 1/7/30 дней)


## Команды в меню Telegram

Бот регистрирует команды в интерфейсе Telegram при старте (set_my_commands).


## Отладка

Для диагностики входящих команд/кнопок:

```bash
journalctl -u wvacancies-bot -f -o cat
```

Ищите строки вида `/period from user=...` и `callback user=... data=...`.
