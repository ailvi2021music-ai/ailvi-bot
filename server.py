import os
import threading
import logging
from flask import Flask
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from openai import OpenAI

# -------------------------
# 🔧 Логи в stdout (видно в Render Logs)
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ailvi-bot")

# -------------------------
# 🔑 Ключи из окружения
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Быстрая проверка наличия ключей (не падаем, но пишем в лог)
if not TELEGRAM_BOT_TOKEN:
    log.error("TELEGRAM_BOT_TOKEN отсутствует в переменных окружения.")
if not OPENAI_API_KEY:
    log.error("OPENAI_API_KEY отсутствует в переменных окружения.")

client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------
# ✅ Health-check (Render pings /)
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI bot is alive"

def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

# -------------------------
# ✅ Telegram logic
# -------------------------

SYSTEM_PROMPT = (
    "Ты — мягкий, спокойный и добрый проводник AILVI. "
    "Помогаешь человеку распаковывать личность шаг за шагом, задаёшь вопросы, "
    "мягко направляешь и не отвечаешь за него."
)

async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_text = update.message.text or ""
        user_id = update.effective_user.id if update.effective_user else "unknown"
        log.info(f"Incoming text from {user_id}: {user_text!r}")

        # Вызов OpenAI
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.7,
            max_tokens=600,
        )

        # В SDK v1 контент берётся так:
        answer = resp.choices[0].message.content if resp.choices else "…"
        if not answer:
            answer = "Мне нужно чуть больше контекста. Напиши, пожалуйста, мысль конкретнее."

        await update.message.reply_text(answer)

    except Exception as e:
        # Логируем полноценный трейс и даём понятный ответ пользователю
        log.exception("OpenAI handler error:")
        await update.message.reply_text(
            "Небольшая задержка с ответом. Попробуй ещё раз через минутку 🙏"
        )

async def start(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ассаламу Алейкум. Я готов работать с тобой.")

def run_telegram():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("✅ Telegram polling started")
    application.run_polling(close_loop=False)  # стабильнее внутри потока

# -------------------------
# ✅ Main
# -------------------------
if __name__ == "__main__":
    # Flask в отдельном потоке, чтобы Render видел health-check
    flask_thread = threading.Thread(target=run_flask, name="flask-thread", daemon=True)
    flask_thread.start()

    # Telegram-бот (polling)
    run_telegram()
