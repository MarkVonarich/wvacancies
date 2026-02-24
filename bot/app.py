from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.config import load_settings
from bot.db import DB, Vacancy
from bot.hh import HHClient
from bot.research import ResearchService
from bot.scoring import Scorer


@dataclass
class SkipDraft:
    scope: str | None = None
    reason: str | None = None


def format_salary(v: Vacancy) -> str:
    if v.salary_from or v.salary_to:
        return f"{v.salary_from or '?'}-{v.salary_to or '?'} {v.currency or ''}".strip()
    return "не указана"


def vacancy_text(v: Vacancy, scorer: Scorer, db: DB, user_id: int) -> str:
    result = scorer.score(v, db.get_weights(user_id))
    plus = "\n".join([f"✅ {x}" for x in result.triggers_plus]) or "✅ —"
    minus = "\n".join([f"⚠️ {x}" for x in result.triggers_minus]) or "⚠️ —"
    return (
        f"🏢 Компания: {v.employer_name}\n\n"
        f"💼 Вакансия: {v.title}\n\n"
        f"📍 Локация / формат: {v.area} / {'удалёнка' if v.remote_flag else 'офис/гибрид'}\n\n"
        f"💰 Зарплата: {format_salary(v)}\n\n"
        f"🔗 Ссылка: {v.url}\n\n"
        f"🎯 Скор: {result.score}/100\n\n"
        f"Триггеры (что сработало):\n\n{plus}\n{minus}"
    )


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("клас5+", callback_data="like")],
            [InlineKeyboardButton("скип", callback_data="skip")],
            [InlineKeyboardButton("исключить ключевое слово", callback_data="exclude")],
        ]
    )


def nav_row(show_skip: bool = True):
    row = [InlineKeyboardButton("⬅️ Назад", callback_data="nav_back")]
    if show_skip:
        row.append(InlineKeyboardButton("⏭ Пропустить", callback_data="nav_skip"))
    return row


async def show_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = context.bot_data["db"]
    scorer: Scorer = context.bot_data["scorer"]
    user_id = update.effective_user.id
    v = db.next_queue_item(user_id)
    if not v:
        await update.effective_message.reply_text("Очередь пуста. Используй /now для ресёрча.")
        return
    context.user_data["current_vacancy_id"] = v.id
    await update.effective_message.reply_text(vacancy_text(v, scorer, db, user_id), reply_markup=main_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data["db"].ensure_user(update.effective_user.id)
    await update.message.reply_text("Привет! /now — ресёрч, /queue — показать вакансию, /blacklist — исключения.")


async def queue_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_next(update, context)


async def now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service: ResearchService = context.bot_data["research"]
    ok, n = service.run_now(update.effective_user.id)
    if not ok:
        await update.message.reply_text("Ресёрч уже выполняется.")
        return
    await update.message.reply_text(f"Ресёрч завершен, добавлено: {n}")


async def filters_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Текущий фильтр: Москва ИЛИ полная удалёнка вне Москвы.")


async def blacklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = context.bot_data["db"]
    rows = db.list_blacklist(update.effective_user.id)
    if not rows:
        await update.message.reply_text("Чёрный список пуст.")
        return
    text = "\n".join([f"- {r['kind']}: {r['value']}" for r in rows[:20]])
    await update.message.reply_text(text)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    db: DB = context.bot_data["db"]
    scorer: Scorer = context.bot_data["scorer"]
    data = q.data
    user_id = update.effective_user.id
    vac_id = context.user_data.get("current_vacancy_id")
    if not vac_id:
        await q.edit_message_text("Нет активной вакансии. Нажмите /queue")
        return

    if data == "like":
        db.record_action(user_id, vac_id, "like", scope="single")
        w = db.get_weights(user_id)
        w["positive"] = min(2.5, w.get("positive", 1.0) + 0.1)
        db.save_weights(user_id, w)
        db.mark_acted(user_id, vac_id)
        await q.edit_message_reply_markup(None)
        await show_next(update, context)
        return

    if data == "skip":
        context.user_data["skip_draft"] = SkipDraft()
        keyboard = [
            [InlineKeyboardButton("Только эту", callback_data="scope_single")],
            [InlineKeyboardButton("Все похожие", callback_data="scope_similar")],
            [InlineKeyboardButton("Все от этой компании 30 дней", callback_data="scope_company_30d")],
            nav_row(True),
        ]
        await q.edit_message_text("Применить скип к…", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("scope_"):
        draft: SkipDraft = context.user_data["skip_draft"]
        draft.scope = data.replace("scope_", "")
        keyboard = [
            [InlineKeyboardButton("Не мой домен", callback_data="reason_not_my_domain")],
            [InlineKeyboardButton("Не мой формат (офис/релокация)", callback_data="reason_not_my_format")],
            [InlineKeyboardButton("Не моя локация", callback_data="reason_not_my_location")],
            [InlineKeyboardButton("ЗП не ок / не указана", callback_data="reason_salary_not_ok")],
            [InlineKeyboardButton("Стек не подходит", callback_data="reason_not_my_stack")],
            [InlineKeyboardButton("Слишком junior/senior", callback_data="reason_not_my_grade")],
            [InlineKeyboardButton("Похоже на дубль", callback_data="reason_duplicate_like")],
            [InlineKeyboardButton("🚫 Не показывать такое", callback_data="reason_antispam")],
            nav_row(True),
        ]
        await q.edit_message_text("Причина скипа:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("reason_"):
        draft: SkipDraft = context.user_data["skip_draft"]
        reason = data.replace("reason_", "")
        draft.reason = reason
        if reason == "antispam":
            keyboard = [
                [InlineKeyboardButton("Не показывать эту компанию 30 дней", callback_data="antispam_company_30d")],
                [InlineKeyboardButton("Не показывать этот title 30 дней", callback_data="antispam_title_30d")],
                [InlineKeyboardButton("Скрыть похожие вакансии (дубликаты)", callback_data="antispam_cluster")],
                nav_row(True),
            ]
            await q.edit_message_text("Анти-спам действия:", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        await _apply_skip(update, context)
        return

    if data.startswith("antispam_"):
        context.user_data["skip_draft"].reason = data
        await _apply_skip(update, context)
        return

    if data == "exclude":
        vac = _load_vacancy(db, vac_id)
        candidates = scorer.keyword_candidates(vac)
        keyboard = [[InlineKeyboardButton(x, callback_data=f"kw_{x[:30]}")] for x in candidates[:10]]
        keyboard.append([InlineKeyboardButton("Ввести своё", callback_data="kw_custom")])
        keyboard.append(nav_row(True))
        await q.edit_message_text("Выбор слова:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("kw_"):
        kw = data.replace("kw_", "")
        if kw == "custom":
            kw = "manual_keyword"
        context.user_data["kw"] = kw
        keyboard = [
            [InlineKeyboardButton("Исключить для всех будущих вакансий", callback_data="kw_scope_global")],
            [InlineKeyboardButton("Исключить только для этой вакансии", callback_data="kw_scope_single")],
            nav_row(True),
        ]
        await q.edit_message_text("Охват исключения:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("kw_scope_"):
        scope = data.replace("kw_scope_", "")
        kw = context.user_data.get("kw", "manual_keyword")
        db.record_action(user_id, vac_id, "exclude_keyword", scope=scope, payload={"keyword": kw})
        db.add_blacklist(user_id, "keyword", kw)
        db.mark_acted(user_id, vac_id)
        await q.edit_message_reply_markup(None)
        await show_next(update, context)
        return

    if data == "nav_back":
        await q.edit_message_text("Вернитесь к карточке через /queue")
        return

    if data == "nav_skip":
        await q.edit_message_text("Действие пропущено. /queue")
        return


async def _apply_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    db: DB = context.bot_data["db"]
    user_id = update.effective_user.id
    vac_id = context.user_data["current_vacancy_id"]
    vac = _load_vacancy(db, vac_id)
    draft: SkipDraft = context.user_data["skip_draft"]
    scope = draft.scope or "single"
    reason = draft.reason or "none"
    db.record_action(user_id, vac_id, "skip", scope=scope, reason_code=reason)

    affected = [vac_id]
    if scope == "similar":
        affected = db.find_similar(vac)
    elif scope == "company_30d":
        db.add_blacklist(user_id, "company", vac.employer_name, days=30)
    if reason == "antispam_company_30d":
        db.add_blacklist(user_id, "company", vac.employer_name, days=30)
    if reason == "antispam_title_30d":
        db.add_blacklist(user_id, "title", vac.title, days=30)
    if reason == "antispam_cluster":
        db.add_blacklist(user_id, "cluster", vac.cluster_id)

    w = db.get_weights(user_id)
    w["negative"] = min(2.5, w.get("negative", 1.0) + 0.08)
    db.save_weights(user_id, w)

    db.apply_queue_scope(user_id, affected)
    await q.edit_message_reply_markup(None)
    await show_next(update, context)


def _load_vacancy(db: DB, vac_id: int) -> Vacancy:
    with db.conn() as c:
        row = c.execute("SELECT * FROM vacancies WHERE id=?", (vac_id,)).fetchone()
    return Vacancy(**dict(row))


def run() -> None:
    settings = load_settings()
    db = DB(settings.database_path)
    scorer = Scorer("bot/triggers.yml")
    hh = HHClient(settings, db)
    research = ResearchService(db, hh, scorer)

    app = Application.builder().token(settings.bot_token).build()
    app.bot_data["db"] = db
    app.bot_data["scorer"] = scorer
    app.bot_data["research"] = research

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("queue", queue_cmd))
    app.add_handler(CommandHandler("now", now_cmd))
    app.add_handler(CommandHandler("research", now_cmd))
    app.add_handler(CommandHandler("filters", filters_cmd))
    app.add_handler(CommandHandler("blacklist", blacklist_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling()


if __name__ == "__main__":
    run()
