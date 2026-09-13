import os
import sqlite3
import random
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from maxapi import Bot, Dispatcher
from maxapi.filters.command import CommandStart
from maxapi.types import BotStarted, MessageCreated, MessageCallback, CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.webhook.fastapi import FastAPIMaxWebhook

# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.environ["MAX_BOT_TOKEN"]
WEBHOOK_BASE_URL = os.environ["WEBHOOK_BASE_URL"].rstrip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
WEBHOOK_PATH = "/webhook"

DB = Path("quiz_max.db")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

QUESTIONS_PER_GAME = 10
MAX_POINTS_PER_QUESTION = 15


# =========================
# ВОПРОСЫ
# =========================

QUESTIONS = {
    "minecraft": [
        {
            "q": "Какой моб взрывается рядом с игроком?",
            "options": [
                "Крипер",
                "Скелет",
                "Зомби",
                "Паук"
            ],
            "answer": 0
        },
        {
            "q": "Как называется измерение с лавой и крепостями?",
            "options": [
                "Энд",
                "Незер",
                "Лунный мир",
                "Пустошь"
            ],
            "answer": 1
        },
        {
            "q": "Какой предмет нужен для создания верстака?",
            "options": [
                "Камень",
                "Железо",
                "Доски",
                "Алмазы"
            ],
            "answer": 2
        },
        {
            "q": "Какой моб стреляет из лука?",
            "options": [
                "Скелет",
                "Крипер",
                "Корова",
                "Железный голем"
            ],
            "answer": 0
        },
        {
            "q": "Что нужно для создания алмазной кирки?",
            "options": [
                "2 алмаза",
                "3 алмаза",
                "4 алмаза",
                "5 алмазов"
            ],
            "answer": 1
        },
        {
            "q": "Как называется главный босс в Энде?",
            "options": [
                "Иссушитель",
                "Дракон Края",
                "Страж",
                "Варден"
            ],
            "answer": 1
        },
        {
            "q": "Какой моб появляется из яйца дракона?",
            "options": [
                "Крипер",
                "Никто",
                "Дракон",
                "Варден"
            ],
            "answer": 1
        },
        {
            "q": "Какой ресурс нужен для факела?",
            "options": [
                "Уголь",
                "Алмаз",
                "Золото",
                "Редстоун"
            ],
            "answer": 0
        },
        {
            "q": "Как называется зелёный моб Minecraft?",
            "options": [
                "Крипер",
                "Слизень",
                "Зомби",
                "Скелет"
            ],
            "answer": 0
        },
        {
            "q": "Сколько блоков обсидиана нужно минимум для обычного портала в Незер?",
            "options": [
                "8",
                "10",
                "12",
                "14"
            ],
            "answer": 1
        },
        {
            "q": "Как называется главный ресурс для крафта инструментов в начале игры?",
            "options": [
                "Дерево",
                "Золото",
                "Алмаз",
                "Незерит"
            ],
            "answer": 0
        },
        {
            "q": "Сколько единиц здоровья у игрока (в сердечках)?",
            "options": [
                "10",
                "5",
                "20",
                "15"
            ],
            "answer": 0
        },
        {
            "q": "Какой моб можно приручить с помощью костей?",
            "options": [
                "Волк",
                "Курица",
                "Корова",
                "Овца"
            ],
            "answer": 0
        },
        {
            "q": "Что нужно, чтобы приручить кошку в Minecraft?",
            "options": [
                "Сырая рыба",
                "Кость",
                "Пшеница",
                "Морковь"
            ],
            "answer": 0
        },
        {
            "q": "Какой блок взрывается, если по нему ударить огнём?",
            "options": [
                "Блок ТНТ",
                "Камень",
                "Земля",
                "Песок"
            ],
            "answer": 0
        },
        {
            "q": "Какой моб дает шерсть?",
            "options": [
                "Овца",
                "Корова",
                "Курица",
                "Свинья"
            ],
            "answer": 0
        },
        {
            "q": "Из чего делают хлеб в Minecraft?",
            "options": [
                "Пшеница",
                "Морковь",
                "Картофель",
                "Свёкла"
            ],
            "answer": 0
        },
        {
            "q": "Какой инструмент нужен, чтобы добыть алмаз?",
            "options": [
                "Железная кирка",
                "Деревянная кирка",
                "Каменная кирка",
                "Золотая кирка"
            ],
            "answer": 0
        },
        {
            "q": "Как называется враждебный моб-паук с ядом?",
            "options": [
                "Паук пещерный",
                "Крипер",
                "Скелет",
                "Иссушитель"
            ],
            "answer": 0
        },
        {
            "q": "Что произойдёт, если зомби укусит жителя (villager)?",
            "options": [
                "Житель станет зомби-жителем",
                "Ничего",
                "Житель исчезнет",
                "Житель станет крипером"
            ],
            "answer": 0
        },
        {
            "q": "Какой блок нужен для создания портала в Незер?",
            "options": [
                "Обсидиан",
                "Камень",
                "Кирпич",
                "Булыжник"
            ],
            "answer": 0
        },
        {
            "q": "Чем поджигают портал в Незер?",
            "options": [
                "Огниво",
                "Факел",
                "Лава",
                "Спичка"
            ],
            "answer": 0
        },
        {
            "q": "Какой моб охраняет подводные храмы?",
            "options": [
                "Страж",
                "Кальмар",
                "Дельфин",
                "Рыба"
            ],
            "answer": 0
        },
        {
            "q": "Как называется еда, которую можно найти в океанских руинах?",
            "options": [
                "Мокрая губка",
                "Хлеб",
                "Яблоко",
                "Печенье"
            ],
            "answer": 0
        },
        {
            "q": "Каким инструментом добывают дерево быстрее всего?",
            "options": [
                "Топор",
                "Кирка",
                "Лопата",
                "Мотыга"
            ],
            "answer": 0
        },
        {
            "q": "Что делает мотыга (hoe)?",
            "options": [
                "Вспахивает землю",
                "Рубит дерево",
                "Копает землю",
                "Добывает камень"
            ],
            "answer": 0
        },
        {
            "q": "Какой моб взрывается и наносит урон постройкам?",
            "options": [
                "Крипер",
                "Зомби",
                "Скелет",
                "Паук"
            ],
            "answer": 0
        },
        {
            "q": "Сколько слотов в стандартном инвентаре игрока (без брони и щита)?",
            "options": [
                "36",
                "27",
                "45",
                "20"
            ],
            "answer": 0
        },
        {
            "q": "Какой блок можно использовать как источник света под водой?",
            "options": [
                "Морской фонарь",
                "Факел",
                "Костёр",
                "Лава"
            ],
            "answer": 0
        },
        {
            "q": "Как называется твёрдая версия лавы?",
            "options": [
                "Обсидиан",
                "Базальт",
                "Камень",
                "Гранит"
            ],
            "answer": 0
        },
        {
            "q": "Какое животное можно доить в Minecraft?",
            "options": [
                "Корова",
                "Курица",
                "Овца",
                "Лошадь"
            ],
            "answer": 0
        },
        {
            "q": "Что выпадает из курицы после её убийства?",
            "options": [
                "Сырая курятина и перья",
                "Шерсть",
                "Кожа",
                "Молоко"
            ],
            "answer": 0
        },
        {
            "q": "Какой моб может летать в Энде и наносить урон?",
            "options": [
                "Эндермен",
                "Дракон Края",
                "Гаст",
                "Крипер"
            ],
            "answer": 1
        },
        {
            "q": "Что произойдёт, если посмотреть эндермену в глаза?",
            "options": [
                "Он разозлится и нападёт",
                "Ничего",
                "Он убежит",
                "Он подарит предмет"
            ],
            "answer": 0
        },
        {
            "q": "Какой моб обитает в Незере и стреляет огненными шарами?",
            "options": [
                "Гаст",
                "Крипер",
                "Скелет",
                "Зомби"
            ],
            "answer": 0
        },
        {
            "q": "Что нужно скрафтить, чтобы спать ночью?",
            "options": [
                "Кровать",
                "Костёр",
                "Дом",
                "Факел"
            ],
            "answer": 0
        },
        {
            "q": "Какой блок можно превратить в камень, поставив рядом с лавой?",
            "options": [
                "Булыжник",
                "Земля",
                "Песок",
                "Дерево"
            ],
            "answer": 0
        },
        {
            "q": "Что получится, если расплавить песок в печи?",
            "options": [
                "Стекло",
                "Камень",
                "Кирпич",
                "Железо"
            ],
            "answer": 0
        },
        {
            "q": "Какой моб превращает деревни, если его не остановить — заражает жителей?",
            "options": [
                "Зомби",
                "Крипер",
                "Скелет",
                "Паук"
            ],
            "answer": 0
        },
        {
            "q": "Из чего состоит зачарованный стол (enchanting table)?",
            "options": [
                "Алмазы, книга и обсидиан",
                "Золото и железо",
                "Дерево и камень",
                "Кожа и бумага"
            ],
            "answer": 0
        },
        {
            "q": "Что можно приготовить в печи из сырого мяса?",
            "options": [
                "Жареное мясо",
                "Хлеб",
                "Пирог",
                "Суп"
            ],
            "answer": 0
        },
        {
            "q": "Как называется структура, где можно найти сокровища и ловушки со стрелами?",
            "options": [
                "Подземелье (данжн)",
                "Деревня",
                "Храм",
                "Крепость"
            ],
            "answer": 0
        },
        {
            "q": "Какой инструмент используют для добычи камня и руды?",
            "options": [
                "Кирка",
                "Топор",
                "Лопата",
                "Меч"
            ],
            "answer": 0
        },
        {
            "q": "Как называется самый прочный материал для брони до незерита?",
            "options": [
                "Алмаз",
                "Золото",
                "Железо",
                "Кожа"
            ],
            "answer": 0
        },
        {
            "q": "Какой моб можно найти только в биоме пустыни, живущий в храмах-пирамидах?",
            "options": [
                "Здесь нет уникального моба, но есть ловушки",
                "Дракон",
                "Страж",
                "Иссушитель"
            ],
            "answer": 0
        },
        {
            "q": "Что случится, если игрок утонет?",
            "options": [
                "Начнёт терять здоровье",
                "Ничего не произойдёт",
                "Появится в другом месте",
                "Получит броню"
            ],
            "answer": 0
        },
        {
            "q": "Каким способом можно телепортироваться в Minecraft без модов?",
            "options": [
                "С помощью эндер-жемчуга",
                "Просто прыгнуть",
                "Построить портал в обычном мире",
                "Никак"
            ],
            "answer": 0
        },
        {
            "q": "Что даёт зачарование «Острота» (Sharpness) для меча?",
            "options": [
                "Увеличивает урон",
                "Увеличивает скорость атаки",
                "Даёт защиту",
                "Восстанавливает здоровье"
            ],
            "answer": 0
        },
        {
            "q": "Какой блок используют, чтобы хранить много предметов?",
            "options": [
                "Сундук",
                "Кровать",
                "Печь",
                "Стол"
            ],
            "answer": 0
        },
        {
            "q": "Как называется явление, когда вода превращается в лёд в холодном биоме?",
            "options": [
                "Замерзание",
                "Таяние",
                "Испарение",
                "Кипение"
            ],
            "answer": 0
        }
    ]
}


# =========================
# НАЗВАНИЯ КАТЕГОРИЙ
# =========================

CATEGORY_NAMES = {
    "minecraft": "⛏ Minecraft",
}


# =========================
# БАЗА
# =========================

def init_db():

    conn = sqlite3.connect(DB)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            games INTEGER DEFAULT 0,
            correct INTEGER DEFAULT 0,
            questions INTEGER DEFAULT 0,
            best_score INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


def get_player(user_id, name=""):

    conn = sqlite3.connect(DB)

    row = conn.execute(
        """
        SELECT user_id, name, games, correct, questions, best_score
        FROM players
        WHERE user_id=?
        """,
        (user_id,),
    ).fetchone()

    if not row:

        conn.execute(
            "INSERT INTO players (user_id, name) VALUES (?, ?)",
            (user_id, name),
        )

        conn.commit()

        row = conn.execute(
            """
            SELECT user_id, name, games, correct, questions, best_score
            FROM players
            WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()

    conn.close()

    return row


def update_stats(user_id, correct, questions, score):

    conn = sqlite3.connect(DB)

    row = conn.execute(
        "SELECT games, correct, questions, best_score FROM players WHERE user_id=?",
        (user_id,),
    ).fetchone()

    games = row[0] + 1
    total_correct = row[1] + correct
    total_questions = row[2] + questions
    best_score = max(row[3], score)

    conn.execute(
        """
        UPDATE players
        SET games=?, correct=?, questions=?, best_score=?
        WHERE user_id=?
        """,
        (games, total_correct, total_questions, best_score, user_id),
    )

    conn.commit()
    conn.close()


def get_leaderboard(limit=10):

    conn = sqlite3.connect(DB)

    rows = conn.execute(
        """
        SELECT name, best_score, games
        FROM players
        WHERE games > 0
        ORDER BY best_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()

    return rows


# =========================
# ПЕРЕМЕШИВАНИЕ ВАРИАНТОВ ОТВЕТА
# =========================

def shuffle_question(question):

    indices = list(range(len(question["options"])))
    random.shuffle(indices)

    new_question = dict(question)
    new_question["options"] = [question["options"][i] for i in indices]
    new_question["answer"] = indices.index(question["answer"])

    return new_question


# =========================
# КЛАВИАТУРЫ
# =========================

def main_keyboard():

    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🎮 Играть", payload="play"))
    kb.row(CallbackButton(text="🏆 Доска лидеров", payload="leaderboard"))
    kb.row(CallbackButton(text="📊 Моя статистика", payload="stats"))

    return kb.as_markup()


def categories_keyboard():

    kb = InlineKeyboardBuilder()

    for key, name in CATEGORY_NAMES.items():
        kb.row(CallbackButton(text=name, payload=f"cat:{key}"))

    return kb.as_markup()


def answer_keyboard(question):

    kb = InlineKeyboardBuilder()

    for i, option in enumerate(question["options"]):
        kb.row(CallbackButton(text=option, payload=f"answer:{i}"))

    return kb.as_markup()


def after_game_keyboard():

    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🎮 Играть снова", payload="play"))
    kb.row(CallbackButton(text="📊 Статистика", payload="stats"))

    return kb.as_markup()


# =========================
# ВРЕМЕННАЯ ПАМЯТЬ ИГР
# =========================

games = {}


# =========================
# СТАРТ (нажатие кнопки "Начать" или команда /start)
# =========================

MAIN_MENU_TEXT = (
    "🎮 Викторина\n\n"
    "Проверь свои знания и набери максимум очков!\n\n"
    "Выбирай категорию и начинай игру."
)


@dp.bot_started()
async def bot_started(event: BotStarted):

    # У события "Начать" пользователь уже приходит вместе с апдейтом,
    # в поле user (не нужно отдельно запрашивать fetch_from_user).
    user_id = event.user.user_id
    name = event.user.name or ""

    get_player(user_id, name)

    await bot.send_message(
        chat_id=event.chat_id,
        text=MAIN_MENU_TEXT,
        attachments=[main_keyboard()],
    )


@dp.message_created(CommandStart())
async def cmd_start(event: MessageCreated):

    from_user = await event.fetch_from_user()

    if from_user:
        get_player(from_user.user_id, from_user.name or "")

    # event.message.answer сам разбирается, кому и куда отвечать —
    # не нужно вручную собирать chat_id/user_id.
    await event.message.answer(
        text=MAIN_MENU_TEXT,
        attachments=[main_keyboard()],
    )


# =========================
# ОТПРАВКА ВОПРОСА
# =========================

async def send_question(event, user_id, prefix=""):

    game = games[user_id]
    question = game["questions"][game["current"]]

    number = game["current"] + 1
    total = len(game["questions"])
    category = CATEGORY_NAMES[game["category"]]

    text = ""
    if prefix:
        text += f"{prefix}\n\n"

    text += (
        f"{category}\n\n"
        f"❓ Вопрос {number}/{total}\n\n"
        f"{question['q']}\n\n"
        f"⭐ Очки: {game['score']}"
    )

    await event.answer(
        new_text=text,
        attachments=[answer_keyboard(question)],
    )

    game["asked_at"] = time.monotonic()


# =========================
# CALLBACK (нажатия на кнопки)
# =========================

@dp.message_callback()
async def callbacks(event: MessageCallback):

    payload = event.callback.payload
    user_id = event.callback.user.user_id
    name = event.callback.user.name or ""

    # -------------------------
    # ИГРАТЬ
    # -------------------------

    if payload == "play":

        await event.answer(
            new_text="Выбери категорию:",
            attachments=[categories_keyboard()],
        )

        return

    # -------------------------
    # ДОСКА ЛИДЕРОВ
    # -------------------------

    if payload == "leaderboard":

        rows = get_leaderboard()

        if not rows:

            text = (
                "🏆 Доска лидеров\n\n"
                "Пока никто не сыграл ни одной игры.\n"
                "Стань первым!"
            )

        else:

            medals = ["🥇", "🥈", "🥉"]
            lines = ["🏆 Доска лидеров", ""]

            for i, (player_name, best_score, games_count) in enumerate(rows):

                place = medals[i] if i < 3 else f"{i + 1}."
                display_name = player_name or "Игрок без имени"

                lines.append(
                    f"{place} {display_name} — "
                    f"{best_score} очков ({games_count} игр)"
                )

            text = "\n".join(lines)

        await event.answer(
            new_text=text,
            attachments=[main_keyboard()],
        )

        return

    # -------------------------
    # СТАТИСТИКА
    # -------------------------

    if payload == "stats":

        row = get_player(user_id, name)
        _, _, games_count, correct, questions_count, best_score = row

        percent = round(correct / questions_count * 100) if questions_count else 0

        await event.answer(
            new_text=(
                "📊 Твоя статистика\n\n"
                f"🎮 Игр: {games_count}\n"
                f"❓ Вопросов: {questions_count}\n"
                f"✅ Правильных ответов: {correct}\n"
                f"🎯 Точность: {percent}%\n"
                f"🏆 Лучший результат: {best_score} очков"
            ),
            attachments=[main_keyboard()],
        )

        return

    # -------------------------
    # КАТЕГОРИЯ
    # -------------------------

    if payload.startswith("cat:"):

        category = payload.split(":", 1)[1]
        pool = QUESTIONS[category]
        count = min(QUESTIONS_PER_GAME, len(pool))

        selected = random.sample(pool, count)
        selected = [shuffle_question(q) for q in selected]

        games[user_id] = {
            "category": category,
            "questions": selected,
            "current": 0,
            "score": 0,
            "correct": 0,
        }

        await send_question(event, user_id)

        return

    # -------------------------
    # ОТВЕТ
    # -------------------------

    if payload.startswith("answer:"):

        game = games.get(user_id)

        if not game:

            await event.answer(
                new_text="Начни новую игру",
                attachments=[main_keyboard()],
            )

            return

        total_questions = len(game["questions"])
        question = game["questions"][game["current"]]
        answer = int(payload.split(":")[1])

        explanation = question.get("explain", "")
        elapsed = time.monotonic() - game.get("asked_at", time.monotonic())

        if answer == question["answer"]:

            if elapsed <= 3:
                points = 15
                speed_note = "⚡ Молниеносно!"
            elif elapsed <= 6:
                points = 10
                speed_note = "🔥 Быстро!"
            else:
                points = 5
                speed_note = "✅ В цель, но можно быстрее."

            game["correct"] += 1
            game["score"] += points

            result = (
                f"✅ Правильно! ({elapsed:.1f} сек)\n"
                f"{speed_note} +{points} очков"
            )

        else:

            correct_answer = question["options"][question["answer"]]
            result = f"❌ Неправильно!\nПравильный ответ: {correct_answer}"

        if explanation:
            result += f"\n{explanation}"

        game["current"] += 1

        if game["current"] >= total_questions:

            update_stats(user_id, game["correct"], total_questions, game["score"])

            score = game["score"]
            correct_count = game["correct"]
            max_score = total_questions * MAX_POINTS_PER_QUESTION

            if score >= max_score * 0.9:
                message = "🔥 Невероятный результат!"
            elif score >= max_score * 0.7:
                message = "🏆 Отличная игра!"
            elif score >= max_score * 0.5:
                message = "👍 Неплохо!"
            else:
                message = "💪 В следующий раз будет лучше!"

            await event.answer(
                new_text=(
                    f"{result}\n\n"
                    "🏁 Игра закончена!\n\n"
                    f"Правильных ответов: {correct_count}/{total_questions}\n"
                    f"Очки: {score}/{max_score}\n\n"
                    f"{message}"
                ),
                attachments=[after_game_keyboard()],
            )

            del games[user_id]

            return

        await send_question(event, user_id, prefix=result)

        return


# =========================
# ЗАПУСК (webhook + healthcheck)
# =========================
# ВАЖНО: FastAPI не даёт одновременно использовать современный
# "lifespan" (которым управляет сама библиотека maxapi) и старый
# @app.on_event("startup") — при их совместном использовании код
# внутри on_event попросту не выполняется. Поэтому объединяем всё
# в один lifespan: сначала отрабатывает встроенный запуск maxapi,
# затем — наша подписка на вебхук.

from contextlib import asynccontextmanager

webhook = FastAPIMaxWebhook(dp=dp, bot=bot, secret=WEBHOOK_SECRET)


@asynccontextmanager
async def lifespan(app: FastAPI):

    init_db()

    async with webhook.lifespan(app):

        desired_url = WEBHOOK_BASE_URL + WEBHOOK_PATH

        # Не переустанавливаем вебхук без необходимости при каждом
        # перезапуске (сон/пробуждение, передеплой) — чтобы не
        # словить лишние ограничения от платформы. Ставим заново
        # только если он ещё не совпадает с нужным адресом.
        try:

            current = await bot.get_subscriptions()
            existing_urls = [s.url for s in getattr(current, "subscriptions", [])]

            if desired_url not in existing_urls:
                await bot.subscribe_webhook(url=desired_url, secret=WEBHOOK_SECRET)

        except Exception as error:
            print(f"Не удалось проверить/установить вебхук при старте: {error}")

        yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def health():
    return {"status": "ok"}


webhook.setup(app, path=WEBHOOK_PATH)


if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
    )
