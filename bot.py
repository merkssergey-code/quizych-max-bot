import asyncio
import copy
import json
import logging
import os
import random
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
 
from fastapi import FastAPI
from maxapi import Bot, Dispatcher, F
from maxapi.filters.command import CommandStart
from maxapi.types import (
    BotStarted,
    CallbackButton,
    InputMedia,
    MessageCallback,
    MessageCreated,
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.webhook.fastapi import FastAPIMaxWebhook
 
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kvizych")
 
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "quiz_max.db"
QUESTIONS_PATH = BASE_DIR / "questions.json"
 
BOT_TOKEN = os.environ["MAX_BOT_TOKEN"].strip()
WEBHOOK_BASE_URL = os.environ["WEBHOOK_BASE_URL"].strip().rstrip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"].strip()
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"
 
QUESTIONS_PER_GAME = 10
MAX_POINTS = 15
 
if not BOT_TOKEN:
    raise RuntimeError("MAX_BOT_TOKEN пустой")
if not WEBHOOK_BASE_URL.startswith("https://"):
    raise RuntimeError("WEBHOOK_BASE_URL должен начинаться с https://")
if not (5 <= len(WEBHOOK_SECRET) <= 256):
    raise RuntimeError("WEBHOOK_SECRET должен содержать от 5 до 256 символов")
 
QUESTIONS = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
CATEGORY_NAMES = {
    "minecraft": "⛏ Minecraft",
    "roblox": "🎮 Roblox",
    "brawl_stars": "⭐ Brawl Stars",
    "sport": "⚽ Спорт",
    "space": "🚀 Космос",
    "math": "➗ Математика",
    "russian": "📖 Русский язык",
    "english": "🇬🇧 Английский язык",
}
 
for category, pool in QUESTIONS.items():
    if category not in CATEGORY_NAMES:
        CATEGORY_NAMES[category] = category
    if len(pool) != 50:
        raise RuntimeError(f"Категория {category} должна содержать ровно 50 вопросов")
    ids = set()
    for q in pool:
        if not isinstance(q.get("id"), str):
            raise RuntimeError(f"У вопроса в {category} нет id")
        if q["id"] in ids:
            raise RuntimeError(f"Дубликат id {q['id']}")
        ids.add(q["id"])
        if len(q.get("options", [])) != 4:
            raise RuntimeError(f"Вопрос {q['id']} должен иметь 4 варианта")
        if not 0 <= q.get("answer", -1) < 4:
            raise RuntimeError(f"Неверный answer у {q['id']}")
 
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
webhook = FastAPIMaxWebhook(dp=dp, bot=bot, secret=WEBHOOK_SECRET)
 
games: dict[int, dict] = {}
 
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
 
def init_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            games INTEGER NOT NULL DEFAULT 0,
            correct INTEGER NOT NULL DEFAULT 0,
            questions INTEGER NOT NULL DEFAULT 0,
            total_score INTEGER NOT NULL DEFAULT 0,
            best_score INTEGER NOT NULL DEFAULT 0
        );
 
        CREATE TABLE IF NOT EXISTS category_stats (
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            games INTEGER NOT NULL DEFAULT 0,
            correct INTEGER NOT NULL DEFAULT 0,
            questions INTEGER NOT NULL DEFAULT 0,
            score INTEGER NOT NULL DEFAULT 0,
            best_score INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, category)
        );
 
        CREATE TABLE IF NOT EXISTS seen_questions (
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            question_id TEXT NOT NULL,
            PRIMARY KEY (user_id, category, question_id)
        );
        """
    )
    conn.commit()
    conn.close()
 
def upsert_player(user_id: int, username: str = "", name: str = ""):
    conn = db()
    conn.execute(
        """
        INSERT INTO players(user_id, username, name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            name=CASE WHEN excluded.name != '' THEN excluded.name ELSE players.name END
        """,
        (user_id, username or "", name or ""),
    )
    conn.commit()
    conn.close()
 
def get_overall_stats(user_id: int):
    conn = db()
    row = conn.execute("SELECT * FROM players WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row
 
def get_category_stats(user_id: int, category: str):
    conn = db()
    row = conn.execute(
        "SELECT * FROM category_stats WHERE user_id=? AND category=?",
        (user_id, category),
    ).fetchone()
    conn.close()
    return row
 
def mark_seen(user_id: int, category: str, question_ids: list[str]):
    conn = db()
    conn.executemany(
        "INSERT OR IGNORE INTO seen_questions(user_id, category, question_id) VALUES (?, ?, ?)",
        [(user_id, category, qid) for qid in question_ids],
    )
    conn.commit()
    conn.close()
 
def get_seen_ids(user_id: int, category: str) -> set[str]:
    conn = db()
    rows = conn.execute(
        "SELECT question_id FROM seen_questions WHERE user_id=? AND category=?",
        (user_id, category),
    ).fetchall()
    conn.close()
    return {row[0] for row in rows}
 
def reset_seen(user_id: int, category: str):
    conn = db()
    conn.execute(
        "DELETE FROM seen_questions WHERE user_id=? AND category=?",
        (user_id, category),
    )
    conn.commit()
    conn.close()
 
def choose_questions(user_id: int, category: str) -> list[dict]:
    pool = QUESTIONS[category]
    seen = get_seen_ids(user_id, category)
    unseen = [q for q in pool if q["id"] not in seen]
 
    # 50 questions делятся ровно на 5 игр по 10.
    # Поэтому при нормальном прохождении цикла здесь всегда будет >=10.
    # Если игрок прервал старый цикл или база была повреждена, начинаем новый цикл.
    if len(unseen) < QUESTIONS_PER_GAME:
        reset_seen(user_id, category)
        unseen = list(pool)
 
    selected = random.sample(unseen, QUESTIONS_PER_GAME)
    mark_seen(user_id, category, [q["id"] for q in selected])
    return [shuffle_question(q) for q in selected]
 
def shuffle_question(question: dict) -> dict:
    q = copy.deepcopy(question)
    pairs = list(enumerate(q["options"]))
    random.shuffle(pairs)
    q["options"] = [text for _, text in pairs]
    q["answer"] = next(new for new, (old, _) in enumerate(pairs) if old == question["answer"])
    return q
 
def update_stats(user_id: int, category: str, correct: int, total: int, score: int):
    conn = db()
    conn.execute(
        """
        INSERT INTO players(user_id) VALUES (?)
        ON CONFLICT(user_id) DO NOTHING
        """,
        (user_id,),
    )
    conn.execute(
        """
        UPDATE players
        SET games=games+1,
            correct=correct+?,
            questions=questions+?,
            total_score=total_score+?,
            best_score=MAX(best_score, ?)
        WHERE user_id=?
        """,
        (correct, total, score, score, user_id),
    )
    conn.execute(
        """
        INSERT INTO category_stats(user_id, category, games, correct, questions, score, best_score)
        VALUES (?, ?, 1, ?, ?, ?, ?)
        ON CONFLICT(user_id, category) DO UPDATE SET
            games=games+1,
            correct=correct+excluded.correct,
            questions=questions+excluded.questions,
            score=score+excluded.score,
            best_score=MAX(best_score, excluded.best_score)
        """,
        (user_id, category, correct, total, score, score),
    )
    conn.commit()
    conn.close()
 
def overall_leaderboard(limit=10):
    conn = db()
    rows = conn.execute(
        """
        SELECT name, username, best_score, games, correct, questions
        FROM players
        WHERE games > 0
        ORDER BY best_score DESC, correct DESC, questions DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return rows
 
def category_leaderboard(category: str, limit=10):
    conn = db()
    rows = conn.execute(
        """
        SELECT p.name, p.username, s.best_score, s.games, s.correct, s.questions
        FROM category_stats s
        JOIN players p ON p.user_id=s.user_id
        WHERE s.category=? AND s.games > 0
        ORDER BY s.best_score DESC, s.correct DESC, s.questions DESC
        LIMIT ?
        """,
        (category, limit),
    ).fetchall()
    conn.close()
    return rows
 
def main_keyboard():
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🎮 Играть", payload="play"))
    kb.row(
        CallbackButton(text="🏆 Рейтинг", payload="leaderboard"),
        CallbackButton(text="📊 Моя статистика", payload="stats"),
    )
    return kb.as_markup()
 
def categories_keyboard():
    kb = InlineKeyboardBuilder()
    for key, name in CATEGORY_NAMES.items():
        kb.row(CallbackButton(text=name, payload=f"cat:{key}"))
    return kb.as_markup()
 
def answer_keyboard(question: dict):
    kb = InlineKeyboardBuilder()
    for index, option in enumerate(question["options"]):
        kb.row(CallbackButton(text=option, payload=f"answer:{index}"))
    return kb.as_markup()
 
def after_game_keyboard():
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🎮 Играть снова", payload="play"))
    kb.row(
        CallbackButton(text="🏆 Рейтинг", payload="leaderboard"),
        CallbackButton(text="📊 Статистика", payload="stats"),
    )
    return kb.as_markup()
 
def safe_name(row):
    name = row["name"] or row["username"] or "Игрок"
    return str(name).replace("<", "&lt;").replace(">", "&gt;")
 
async def send_question(event, user_id: int):
    game = games.get(user_id)
    if not game:
        return
 
    q = game["questions"][game["current"]]
    game["asked_at"] = time.monotonic()
    game["answered"] = False
 
    text = (
        f"<b>{CATEGORY_NAMES.get(game['category'], game['category'])}</b>\n"
        f"Вопрос {game['current'] + 1}/{len(game['questions'])}\n\n"
        f"{q['q']}"
    )
 
    attachments = []
    image_url = q.get("image_url")
    if image_url:
        try:
            attachments.append(InputMedia(url=image_url))
        except Exception as exc:
            log.warning("Не удалось подготовить изображение %s: %s", image_url, exc)
 
    attachments.append(answer_keyboard(q))
    await event.message.answer(text=text, attachments=attachments)
 
@dp.message_created(CommandStart())
async def start(event: MessageCreated):
    user = await event.fetch_from_user()
    if user is not None:
        upsert_player(user.user_id, user.username or "", user.name or "")
        user_id = user.user_id
    else:
        user_id = event.from_user.user_id
        upsert_player(user_id)
 
    await event.message.answer(
        "<b>🎮 Квизыч</b>\n\n"
        "10 вопросов, скорость важна.\n"
        "15 очков — до 3 сек, 10 — до 6 сек, 5 — позже.\n\n"
        "Выбирай тему и начинай.",
        attachments=[main_keyboard()],
    )
 
@dp.bot_started()
async def bot_started(event: BotStarted):
    user = getattr(event, "user", None)
    if user is not None:
        upsert_player(user.user_id, getattr(user, "username", "") or "", getattr(user, "name", "") or "")
    await bot.send_message(
        chat_id=event.chat_id,
        text="Привет! Это «Квизыч». Нажми /start, чтобы начать игру.",
        attachments=[main_keyboard()],
    )
 
@dp.message_callback(F.callback.payload == "play")
async def play(event: MessageCallback):
    await event.message.answer("<b>Выбери категорию:</b>", attachments=[categories_keyboard()])
    await event.answer()
 
@dp.message_callback(F.callback.payload.startswith("cat:"))
async def category(event: MessageCallback):
    user = await event.fetch_from_user()
    if user is None:
        await event.answer(new_text="Не удалось определить игрока")
        return
    user_id = user.user_id
    category_key = event.callback.payload.split(":", 1)[1]
    if category_key not in QUESTIONS:
        await event.answer(new_text="Эта категория недоступна")
        return
 
    upsert_player(user_id, user.username or "", user.name or "")
    selected = choose_questions(user_id, category_key)
    games[user_id] = {
        "category": category_key,
        "questions": selected,
        "current": 0,
        "score": 0,
        "correct": 0,
        "answered": False,
    }
    await event.answer()
    await send_question(event, user_id)
 
@dp.message_callback(F.callback.payload.startswith("answer:"))
async def answer(event: MessageCallback):
    user = await event.fetch_from_user()
    if user is None:
        await event.answer(new_text="Не удалось определить игрока")
        return
    user_id = user.user_id
    game = games.get(user_id)
    if not game:
        await event.answer(new_text="Игра уже закончилась. Нажми «Играть снова».")
        return
    if game.get("answered"):
        await event.answer(new_text="Этот вопрос уже засчитан")
        return
 
    try:
        selected_answer = int(event.callback.payload.split(":", 1)[1])
    except (ValueError, IndexError):
        await event.answer(new_text="Некорректный ответ")
        return
 
    question = game["questions"][game["current"]]
    game["answered"] = True
    elapsed = max(0.0, time.monotonic() - game.get("asked_at", time.monotonic()))
 
    if selected_answer == question["answer"]:
        if elapsed <= 3:
            points = 15
            speed = "⚡ Молниеносно!"
        elif elapsed <= 6:
            points = 10
            speed = "🔥 Быстро!"
        else:
            points = 5
            speed = "✅ Правильно, но можно быстрее."
        game["correct"] += 1
        game["score"] += points
        result = f"✅ <b>Правильно!</b>\n{speed} +{points}"
    else:
        correct_text = question["options"][question["answer"]]
        result = f"❌ <b>Неправильно.</b>\nПравильный ответ: <b>{correct_text}</b>"
 
    game["current"] += 1
    total = len(game["questions"])
 
    if game["current"] >= total:
        score = game["score"]
        correct = game["correct"]
        category_key = game["category"]
        update_stats(user_id, category_key, correct, total, score)
        games.pop(user_id, None)
 
        max_score = total * MAX_POINTS
        if score == max_score:
            title = "🏆 Идеальная игра!"
        elif score >= int(max_score * 0.75):
            title = "🔥 Отличный результат!"
        elif score >= int(max_score * 0.5):
            title = "👍 Неплохо!"
        else:
            title = "💪 Попробуй ещё раз!"
 
        await event.message.answer(
            f"{result}\n\n"
            f"<b>{title}</b>\n"
            f"Результат: <b>{score}</b> из {max_score}\n"
            f"Правильных: <b>{correct}/{total}</b>",
            attachments=[after_game_keyboard()],
        )
        await event.answer()
        return
 
    await event.answer()
    await event.message.answer(result)
    await send_question(event, user_id)
 
@dp.message_callback(F.callback.payload == "stats")
async def stats(event: MessageCallback):
    user = await event.fetch_from_user()
    if user is None:
        await event.answer(new_text="Не удалось определить игрока")
        return
    row = get_overall_stats(user.user_id)
    if row is None:
        upsert_player(user.user_id, user.username or "", user.name or "")
        row = get_overall_stats(user.user_id)
 
    accuracy = round((row["correct"] / row["questions"]) * 100) if row["questions"] else 0
    await event.message.answer(
        "<b>📊 Моя статистика</b>\n\n"
        f"🎮 Игр: {row['games']}\n"
        f"❓ Вопросов: {row['questions']}\n"
        f"✅ Правильных: {row['correct']}\n"
        f"🎯 Точность: {accuracy}%\n"
        f"⭐ Всего очков: {row['total_score']}\n"
        f"🏆 Лучший результат: {row['best_score']}",
        attachments=[main_keyboard()],
    )
    await event.answer()
 
@dp.message_callback(F.callback.payload == "leaderboard")
async def leaderboard(event: MessageCallback):
    rows = overall_leaderboard()
    if not rows:
        text = "<b>🏆 Рейтинг</b>\n\nПока никто не сыграл."
    else:
        lines = ["<b>🏆 Рейтинг</b>", ""]
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows):
            place = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{place} {safe_name(row)} — <b>{row['best_score']}</b> очков")
        text = "\n".join(lines)
    await event.message.answer(text, attachments=[main_keyboard()])
    await event.answer()
 
@dp.message_created()
async def fallback(event: MessageCreated):
    text = (event.message.body.text or "").strip() if event.message.body else ""
    if not text:
        return
    if text.startswith("/"):
        await event.message.answer("Используй /start, чтобы открыть меню.")
    else:
        await event.message.answer("Нажми /start и выбери категорию.")
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # MAX принимает webhook по HTTPS. Один и тот же URL/secret безопасно
    # регистрируем при каждом старте: это устраняет рассинхронизацию после деплоя.
    await bot.subscribe_webhook(
        url=WEBHOOK_URL,
        secret=WEBHOOK_SECRET,
        update_types=["message_created", "message_callback", "bot_started"],
    )
    log.info("MAX webhook subscribed: %s", WEBHOOK_URL)
 
    async with webhook.lifespan(app):
        yield
 
app = FastAPI(lifespan=lifespan)
 
@app.get("/")
async def health():
    return {"status": "ok", "service": "kvizych"}
 
webhook.setup(app, path=WEBHOOK_PATH)
