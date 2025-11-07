import os, json, asyncio, threading
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from openai import OpenAI
from flask import Flask

# ---------------------------------------------------------
#                НАСТРОЙКИ
# ---------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Белый список ID, которым лимит НЕ нужен
SUBSCRIBER_IDS = set([int(x) for x in os.getenv("SUBSCRIBER_IDS","").split(",") if x.strip().isdigit()])

# Сколько бесплатных сообщений каждому пользователю
FREE_MSG_LIMIT = int(os.getenv("FREE_MSG_LIMIT", "10"))

# Хранилище счётчиков
STORE_PATH = Path("store.json")

# ---------------------------------------------------------
#                ХРАНИЛИЩЕ СЧЁТЧИКОВ
# ---------------------------------------------------------

def load_store():
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except:
            return {}
    return {}

def save_store(data: dict):
    try:
        STORE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except:
        pass

store = load_store()
if "users" not in store:
    store["users"] = {}

def get_count(user_id: int) -> int:
    return store["users"].get(str(user_id), {}).get("count", 0)

def inc_count(user_id: int):
    u = store["users"].setdefault(str(user_id), {"count": 0})
    u["count"] = u.get("count", 0) + 1
    save_store(store)

def reset_count(user_id: int):
    store["users"][str(user_id)] = {"count": 0}
    save_store(store)

# ---------------------------------------------------------
#                OpenAI КЛИЕНТ
# ---------------------------------------------------------

client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------------------------------------
#                ПРИВЕТСТВИЕ + PAYWALL
# ---------------------------------------------------------

WELCOME = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе — спокойно, мягко, шаг за шагом — откроем драгоценные дары, "
    "которые Аллах уже вложил в твою Душу: силы, таланты и намерения, "
    "которые ждут, когда ты увидишь их Свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием! 🚀"
)

def paywall_message(current_count: int, limit: int) -> str:
    return (
        "Ты уже отправил несколько сообщений, и видно, что тебе важно продолжать путь.\n\n"
        "Чтобы я мог отвечать так же полно и глубоко, активируй подписку — "
        "и количество сообщений станет неограниченным.\n\n"
        f"Сейчас у тебя {current_count} из {limit} бесплатных сообщений.\n"
        "Если подписка уже активна — напиши /restore."
    )

# ---------------------------------------------------------
#                ХЭНДЛЕРЫ КОМАНД
# ---------------------------------------------------------

async def start(update: Update, context):
    await update.message.reply_text(WELCOME)

async def restore(update: Update, context):
    user_id = update.effective_user.id
    if user_id in SUBSCRIBER_IDS:
        reset_count(user_id)
        await update.message.reply_text("Готово. Лимит сброшен ✅")
    else:
        await update.message.reply_text("Твой ID отсутствует в SUBSCRIBER_IDS.")

# ---------------------------------------------------------
#                ЛОГИКА ОБРАБОТКИ СООБЩЕНИЙ
# ---------------------------------------------------------

async def handle_message(update: Update, context):
    user_text = update.message.text or ""
    user_id = update.effective_user.id

    # Проверяем лимит сообщений
    if user_id not in SUBSCRIBER_IDS:
        current = get_count(user_id)
        if current >= FREE_MSG_LIMIT:
            await update.message.reply_text(paywall_message(current, FREE_MSG_LIMIT))
            return
        if user_text.strip():
            inc_count(user_id)

    # Генерация ответа через OpenAI
    try:
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "You are AILVI — a gentle, concise guide. Speak warmly and clearly."},
                {"role": "user", "content": user_text},
            ],
            temperature=0.3,
        )
        answer = response.choices[0].message["content"]
    except Exception as e:
        err = str(e)
        if "insufficient_quota" in err:
            await update.message.reply_text("Квота API временно исчерпана. Я скоро вернусь 🙏")
            return
        await update.message.reply_text("Сервис временно недоступен. Попробуй ещё раз чуть позже.")
        return

    await update.message.reply_text(answer)

# ---------------------------------------------------------
#                ТЕЛЕГРАМ-БОТ
# ---------------------------------------------------------

def run_telegram_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restore", restore))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot is running...")
    app.run_polling()

# ---------------------------------------------------------
#                FLASK HEALTHCHECK
# ---------------------------------------------------------

flask_app = Flask(__name__)

@flask_app.get("/")
def health():
    return "OK", 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=10000)

# ---------------------------------------------------------
#                ЗАПУСК (ПАРАЛЛЕЛЬНО)
# ---------------------------------------------------------

if __name__ == "__main__":
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()
    run_flask()
