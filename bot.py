import os
import time
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters
from openai import OpenAI
from telegram.error import Conflict

# -------------------------
# 🔑 Ключи
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------
# ✅ Flask health-check (без reloader!)
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI bot is alive"

def run_flask():
    app.run(host="0.0.0.0", port=10000, debug=False, use_reloader=False, threaded=True)

# -------------------------
# ✅ Telegram logic
# -------------------------
WELCOME_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем драгоценные дары, которые Аллах уже вложил "
    "в твою Душу — силы, таланты, намерения, которые ждут, когда ты увидишь их Свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Напиши любую фразу — и я начну диалог с тобой."
)

async def start(update, context):
    await update.message.reply_text(WELCOME_TEXT)

async def handle_message(update, context):
    user_text = update.message.text
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты — мягкий, спокойный и добрый проводник AILVI. "
                    "Ты помогаешь человеку распаковывать личность шаг за шагом, "
                    "задаёшь вопросы, мягко направляешь и не отвечаешь за него."
                ),
            },
            {"role": "user", "content": user_text},
        ],
    )
    answer = resp.choices[0].message["content"]
    await update.message.reply_text(answer)

def build_app():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application

def run_telegram():
    """Единичный запуск polling + жёсткая защита от 409-конфликта."""
    while True:
        try:
            app_tg = build_app()
            # На старте гарантированно убираем возможный webhook
            # и сбрасываем очередь апдейтов.
            app_tg.run_polling(
                drop_pending_updates=True,
                allowed_updates=None,   # все типы
                stop_signals=None       # управляем сами, без двойных сигналов
            )
            break  # нормально завершили
        except Conflict:
            # Короткая перекрывашка при деплое/рестарте — подождём и повторим.
            print("⚠️ Detected 409 Conflict (another getUpdates). Retrying in 3s...")
            time.sleep(3)
        except Exception as e:
            print(f"⚠️ Unexpected error in polling: {e}. Retrying in 3s...")
            time.sleep(3)

# -------------------------
# ✅ Main
# -------------------------
if __name__ == "__main__":
    th = threading.Thread(target=run_flask, daemon=True)
    th.start()
    run_telegram()
