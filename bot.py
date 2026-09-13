import asyncio
import json
import logging
import os
import random
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from maxapi import Bot, Dispatcher
from maxapi.filters.command import CommandStart
from maxapi.types import BotStarted, CallbackButton, MessageCallback, MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.webhook.fastapi import FastAPIMaxWebhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quizych")

BOT_TOKEN = os.environ["MAX_BOT_TOKEN"]
WEBHOOK_BASE_URL = os.environ["WEBHOOK_BASE_URL"].rstrip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"

DB_PATH = Path(os.getenv("QUIZ_DB_PATH", "quiz_max.db"))
QUESTIONS_PATH = Path(os.getenv("QUESTIONS_PATH", "questions.json"))
QUESTIONS_PER_GAME = 10

if not (5 <= len(WEBHOOK_SECRET) <= 256) or not all(
    c.isalnum() or c in "_-" for c in WEBHOOK_SECRET
):
    raise RuntimeError(
        "WEBHOOK_SECRET должен содержать 5–256 символов: A-Z, a-z, 0-9, _ или -"
    )

with QUESTIONS_PATH.open("r", encoding="utf-8") as f:
    DATA = json.load(f)

QUESTIONS = DATA["categories"]
CATEGORY_NAMES = DATA["category_names"]

# "Смешанный вызов" — особая категория: объединение вопросов всех
# остальных категорий, поэтому для неё не действует правило "ровно 50".
MIXED_CATEGORY_KEY = "mixed"

for category, pool in QUESTIONS.items():
    if category != MIXED_CATEGORY_KEY and len(pool) != 50:
        raise RuntimeError(f"Категория {category}: должно быть ровно 50 вопросов")
    for q in pool:
        if len(q.get("options", [])) != 4:
            raise RuntimeError(f"{category} вопрос {q.get('id')}: нужно 4 варианта")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
games = {}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL DEFAULT 'Игрок',
        games INTEGER NOT NULL DEFAULT 0,
        questions INTEGER NOT NULL DEFAULT 0,
        correct INTEGER NOT NULL DEFAULT 0,
        points INTEGER NOT NULL DEFAULT 0,
        best_game INTEGER NOT NULL DEFAULT 0,
        total_time REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS seen_questions (
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        question_id INTEGER NOT NULL,
        PRIMARY KEY (user_id, category, question_id)
    );

    CREATE TABLE IF NOT EXISTS category_stats (
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        games INTEGER NOT NULL DEFAULT 0,
        questions INTEGER NOT NULL DEFAULT 0,
        correct INTEGER NOT NULL DEFAULT 0,
        points INTEGER NOT NULL DEFAULT 0,
        total_time REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, category)
    );
    """)
    conn.commit()
    conn.close()


def upsert_player(user_id, name):
    name = (name or "Игрок").strip()[:80] or "Игрок"
    conn = db()
    conn.execute(
        """INSERT INTO players(user_id, name) VALUES(?, ?)
           ON CONFLICT(user_id) DO UPDATE SET name=excluded.name""",
        (user_id, name),
    )
    conn.commit()
    conn.close()


def get_player(user_id):
    conn = db()
    row = conn.execute(
        "SELECT name,games,questions,correct,points,best_game,total_time FROM players WHERE user_id=?",
        (user_id,),
    ).fetchone()
    conn.close()
    return row


def get_seen_ids(user_id, category):
    conn = db()
    rows = conn.execute(
        "SELECT question_id FROM seen_questions WHERE user_id=? AND category=?",
        (user_id, category),
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def select_questions(user_id, category):
    pool = QUESTIONS[category]
    seen = get_seen_ids(user_id, category)
    unseen = [q for q in pool if q["id"] not in seen]

    # Если до конца цикла осталось меньше 10 вопросов, сначала берём остаток,
    # затем начинаем новый цикл. Повтор внутри одного цикла не допускается.
    selected = []
    if len(unseen) >= QUESTIONS_PER_GAME:
        selected = random.sample(unseen, QUESTIONS_PER_GAME)
    else:
        selected.extend(unseen)
        remaining_count = QUESTIONS_PER_GAME - len(selected)
        if remaining_count:
            conn = db()
            conn.execute(
                "DELETE FROM seen_questions WHERE user_id=? AND category=?",
                (user_id, category),
            )
            conn.commit()
            conn.close()
            fresh_pool = pool[:]
            selected.extend(random.sample(fresh_pool, remaining_count))

    # Отмечаем вопросы увиденными сразу при старте игры.
    conn = db()
    conn.executemany(
        "INSERT OR IGNORE INTO seen_questions(user_id,category,question_id) VALUES(?,?,?)",
        [(user_id, category, q["id"]) for q in selected],
    )
    conn.commit()
    conn.close()

    return [shuffle_question(q) for q in selected]


def shuffle_question(question):
    indices = list(range(4))
    random.shuffle(indices)
    options = [question["options"][i] for i in indices]
    answer = indices.index(question["answer"])
    return {"id": question["id"], "q": question["q"], "options": options, "answer": answer}


def update_stats(user_id, category, correct, questions_count, points, elapsed):
    conn = db()
    conn.execute(
        """INSERT INTO players(user_id,name) VALUES(?, 'Игрок')
           ON CONFLICT(user_id) DO NOTHING""",
        (user_id,),
    )
    conn.execute(
        """UPDATE players
           SET games=games+1, questions=questions+?, correct=correct+?,
               points=points+?, best_game=MAX(best_game, ?), total_time=total_time+?
           WHERE user_id=?""",
        (questions_count, correct, points, points, elapsed, user_id),
    )
    conn.execute(
        """INSERT INTO category_stats(user_id,category,games,questions,correct,points,total_time)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(user_id,category) DO UPDATE SET
             games=games+1,
             questions=questions+excluded.questions,
             correct=correct+excluded.correct,
             points=points+excluded.points,
             total_time=total_time+excluded.total_time""",
        (user_id, category, 1, questions_count, correct, points, elapsed),
    )
    conn.commit()
    conn.close()


def leaderboard(limit=10):
    conn = db()
    rows = conn.execute(
        "SELECT name,points,games,correct,questions FROM players WHERE games>0 ORDER BY points DESC, correct DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def category_stats(user_id, category):
    conn = db()
    row = conn.execute(
        "SELECT games,questions,correct,points,total_time FROM category_stats WHERE user_id=? AND category=?",
        (user_id, category),
    ).fetchone()
    conn.close()
    return row


def main_keyboard():
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🎮 Играть", payload="menu:play"))
    kb.row(
        CallbackButton(text="🏆 Рейтинг", payload="menu:rating"),
        CallbackButton(text="📊 Моя статистика", payload="menu:stats"),
    )
    return kb.as_markup()


def categories_keyboard():
    kb = InlineKeyboardBuilder()
    items = list(CATEGORY_NAMES.items())
    for i in range(0, len(items), 2):
        row = [CallbackButton(text=items[i][1], payload=f"cat:{items[i][0]}")]
        if i + 1 < len(items):
            row.append(CallbackButton(text=items[i + 1][1], payload=f"cat:{items[i + 1][0]}"))
        kb.row(*row)
    kb.row(CallbackButton(text="⬅️ В меню", payload="menu:home"))
    return kb.as_markup()


def answers_keyboard(question):
    kb = InlineKeyboardBuilder()
    for i, option in enumerate(question["options"]):
        kb.row(CallbackButton(text=option, payload=f"ans:{i}"))
    return kb.as_markup()


def after_game_keyboard():
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🎮 Ещё раз", payload="menu:play"))
    kb.row(
        CallbackButton(text="📊 Статистика", payload="menu:stats"),
        CallbackButton(text="🏆 Рейтинг", payload="menu:rating"),
    )
    return kb.as_markup()


def name_from_event(event):
    user = getattr(event, "user", None) or getattr(event, "from_user", None)
    if user is None:
        return "Игрок"
    return getattr(user, "name", None) or getattr(user, "first_name", None) or "Игрок"


def user_id_from_message(event):
    user = getattr(event, "from_user", None)
    if user is not None and getattr(user, "user_id", None) is not None:
        return user.user_id
    sender = getattr(event.message, "sender", None)
    return getattr(sender, "user_id", None)


async def send_main(event, user_id=None, name=None):
    if user_id is not None:
        upsert_player(user_id, name or "Игрок")
    await event.message.answer(
        "<b>🧠 Квизыч</b>\n\n"
        "10 вопросов за игру.\n"
        "Чем быстрее отвечаешь — тем больше очков.\n\n"
        "Выбирай категорию и начинай!",
        attachments=[main_keyboard()],
    )


async def send_categories(event):
    await event.message.answer("<b>Выбери категорию:</b>", attachments=[categories_keyboard()])


async def send_question(event, user_id):
    game = games.get(user_id)
    if not game:
        await send_categories(event)
        return

    idx = game["current"]
    question = game["questions"][idx]
    category_name = CATEGORY_NAMES[game["category"]]
    text = (
        f"<b>{category_name}</b>\n\n"
        f"❓ <b>Вопрос {idx + 1}/{QUESTIONS_PER_GAME}</b>\n\n"
        f"{question['q']}\n\n"
        f"⭐ Очки: {game['score']}"
    )
    await event.message.answer(text, attachments=[answers_keyboard(question)])
    game["asked_at"] = time.monotonic()


async def show_stats(event, user_id):
    row = get_player(user_id)
    if not row:
        await event.message.answer("Пока статистики нет.", attachments=[main_keyboard()])
        return
    name, games_count, questions_count, correct, points, best_game, total_time = row
    accuracy = (correct / questions_count * 100) if questions_count else 0
    avg_time = (total_time / questions_count) if questions_count else 0
    text = (
        f"<b>📊 Статистика {name}</b>\n\n"
        f"🎮 Игр: {games_count}\n"
        f"❓ Вопросов: {questions_count}\n"
        f"✅ Правильных: {correct}\n"
        f"🎯 Точность: {accuracy:.0f}%\n"
        f"⭐ Очков: {points}\n"
        f"🏅 Лучший результат за игру: {best_game}\n"
        f"⚡ Среднее время ответа: {avg_time:.1f} сек"
    )
    await event.message.answer(text, attachments=[main_keyboard()])


async def show_rating(event):
    rows = leaderboard()
    if not rows:
        text = "<b>🏆 Рейтинг</b>\n\nПока никто не сыграл. Будь первым!"
    else:
        lines = ["<b>🏆 Рейтинг игроков</b>", ""]
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, points, games_count, correct, questions_count) in enumerate(rows, 1):
            medal = medals[i - 1] if i <= 3 else f"{i}."
            lines.append(f"{medal} <b>{name}</b> — {points} ⭐ ({correct}/{questions_count})")
        text = "\n".join(lines)
    await event.message.answer(text, attachments=[main_keyboard()])


@dp.message_created(CommandStart())
async def start(event: MessageCreated):
    user_id = user_id_from_message(event)
    if user_id is not None:
        upsert_player(user_id, name_from_event(event))
    await send_main(event)


@dp.bot_started()
async def bot_started(event: BotStarted):
    await bot.send_message(
        chat_id=event.chat_id,
        text="👋 Привет! Я Квизыч. Нажми /start, чтобы начать игру.",
    )


@dp.message_callback()
async def callbacks(event: MessageCallback):
    payload = getattr(event.callback, "payload", "") or ""
    user = getattr(event.callback, "user", None)
    user_id = getattr(user, "user_id", None)
    if user_id is None:
        return
    upsert_player(user_id, getattr(user, "name", None) or getattr(user, "first_name", None) or "Игрок")

    try:
        await event.answer(notification="")
    except Exception:
        pass

    if payload == "menu:home":
        await event.message.delete()
        await send_main(event, user_id=user_id)
        return

    if payload == "menu:play":
        games.pop(user_id, None)
        await event.message.delete()
        await send_categories(event)
        return

    if payload == "menu:rating":
        await event.message.delete()
        await show_rating(event)
        return

    if payload == "menu:stats":
        await event.message.delete()
        await show_stats(event, user_id)
        return

    if payload.startswith("cat:"):
        category = payload[4:]
        if category not in QUESTIONS:
            return
        selected = select_questions(user_id, category)
        games[user_id] = {
            "category": category,
            "questions": selected,
            "current": 0,
            "score": 0,
            "correct": 0,
            "started_at": time.monotonic(),
            "asked_at": None,
        }
        await event.message.delete()
        await send_question(event, user_id)
        return

    if payload.startswith("ans:"):
        game = games.get(user_id)
        if not game:
            await event.message.delete()
            await send_categories(event)
            return

        try:
            answer_index = int(payload[4:])
        except ValueError:
            return

        question = game["questions"][game["current"]]
        elapsed = max(0.0, time.monotonic() - (game["asked_at"] or time.monotonic()))
        correct = answer_index == question["answer"]
        points = 0
        if correct:
            if elapsed <= 3:
                points = 15
            elif elapsed <= 6:
                points = 10
            else:
                points = 5
            game["correct"] += 1
            game["score"] += points

        result = "✅ Правильно!" if correct else f"❌ Неверно. Правильный ответ: {question['options'][question['answer']]}"
        speed = f"⏱ {elapsed:.1f} сек"
        gained = f"+{points} ⭐" if correct else "+0 ⭐"

        game["total_time"] = game.get("total_time", 0.0) + elapsed
        game["current"] += 1

        await event.message.delete()

        if game["current"] >= QUESTIONS_PER_GAME:
            update_stats(
                user_id,
                game["category"],
                game["correct"],
                QUESTIONS_PER_GAME,
                game["score"],
                game.get("total_time", 0.0),
            )
            category_name = CATEGORY_NAMES[game["category"]]
            final_text = (
                f"<b>🏁 Игра окончена</b>\n\n"
                f"{category_name}\n\n"
                f"✅ Правильных: {game['correct']}/{QUESTIONS_PER_GAME}\n"
                f"⭐ Результат: {game['score']}\n\n"
                f"Последний ответ: {result}\n{speed} · {gained}"
            )
            games.pop(user_id, None)
            await event.message.answer(final_text, attachments=[after_game_keyboard()])
            return

        await event.message.answer(
            f"{result}\n{speed} · {gained}\n\nПереходим дальше...",
        )
        await send_question(event, user_id)
        return


# -------------------------
# Webhook / FastAPI
# -------------------------
webhook = FastAPIMaxWebhook(dp=dp, bot=bot, secret=WEBHOOK_SECRET)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    async with webhook.lifespan(app):
        # Не переподписываемся на вебхук без необходимости при каждом
        # перезапуске (сон/пробуждение на Render, каждый передеплой).
        # Платформа может временно ограничивать частые повторные
        # подписки — поэтому сначала проверяем текущее состояние и
        # подписываемся заново только если адрес реально отличается.
        try:
            current = await bot.get_subscriptions()
            existing_urls = [
                getattr(s, "url", None) for s in getattr(current, "subscriptions", [])
            ]

            if WEBHOOK_URL not in existing_urls:
                await bot.subscribe_webhook(
                    url=WEBHOOK_URL,
                    secret=WEBHOOK_SECRET,
                    update_types=["message_created", "message_callback", "bot_started"],
                )
                logger.info("MAX webhook подписан: %s", WEBHOOK_URL)
            else:
                logger.info("MAX webhook уже был подписан: %s", WEBHOOK_URL)

        except Exception as exc:
            logger.exception("Не удалось проверить/подписать webhook: %s", exc)

        yield


app = FastAPI(lifespan=lifespan)
webhook.setup(app, path=WEBHOOK_PATH)


@app.get("/")
async def health():
    return {"status": "ok", "bot": "quizych"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
