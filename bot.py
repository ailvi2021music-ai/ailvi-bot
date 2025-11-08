import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# -------------------------
# 🔑 Ключи (OpenAI тут не нужен для курса-скрипта)
# -------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# -------------------------
# ✅ Flask health-check
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI bot is alive"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# -------------------------
# 📘 Сценарий курса (пример — подставь свои реальные шаги)
# -------------------------
COURSE_QUESTIONS = [
    "Начнём мягко. Как ты сейчас? В двух-трёх предложениях опиши своё внутреннее состояние.",
    "Назови три вещи, за которые ты благодарен сегодня (кратко).",
    "Что даёт тебе спокойствие в сложный день? Пример из жизни.",
    "Какая одна привычка мешает двигаться к цели?",
    "Какую сильную сторону ты в себе особенно ценишь?",
]

INTRO_TEXT = (
    "Ассаляму Алейкум. Я AILVI Guide. Я буду вести тебя шаг за шагом. "
    "Отвечай коротко и честно — и мы сразу пойдём дальше."
)

FINISH_TEXT = (
    "Спасибо, ты прошёл текущий блок вопросов. Если хочешь — напиши /start, "
    "и мы начнём заново или продолжим с новыми вопросами."
)

# -------------------------
# 🧠 Хранилище шага (в памяти на пользователя)
# -------------------------
def get_step(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.user_data.get("step", 0)

def set_step(context: ContextTypes.DEFAULT_TYPE, step: int):
    context.user_data["step"] = step

def current_question(step: int) -> str:
    idx = min(step, len(COURSE_QUESTIONS) - 1)
    return COURSE_QUESTIONS[idx]

# -------------------------
# 🤖 Handlers
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сброс и старт курса
    set_step(context, 0)
    await update.message.reply_text(INTRO_TEXT)
    await update.message.reply_text(current_question(0))

async def repeat_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Повтор текущего вопроса (на случай «а что отвечать?»)
    step = get_step(context)
    if step >= len(COURSE_QUESTIONS):
        await update.message.reply_text("Блок пройден. Напиши /start, чтобы начать заново.")
        return
    await update.message.reply_text(current_question(step))

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Получили ответ — двигаем шаг и задаём следующий вопрос
    step = get_step(context)

    # Если блок уже завершён — предлагаем перезапуск
    if step >= len(COURSE_QUESTIONS):
        await update.message.reply_text(FINISH_TEXT)
        return

    # Мягкое подтверждение (без оценки)
    # Текст ответа пользователя мы не сохраняем тут — можно подключить БД, если нужно.
    await update.message.reply_text("Спасибо. Идём дальше.")

    # Переходим на следующий вопрос
    step += 1
    set_step(context, step)

    if step >= len(COURSE_QUESTIONS):
        await update.message.reply_text(FINISH_TEXT)
    else:
        await update.message.reply_text(current_question(step))

# -------------------------
# 🚀 Telegram runner
# -------------------------
def run_telegram():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("repeat", repeat_question))  # опционально
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer))

    print("✅ Telegram polling started")
    application.run_polling()

# -------------------------
# ✅ Main
# -------------------------
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    run_telegram()
