import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

WELCOME = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем драгоценные дары, которые Аллах уже вложил в твою Душу — "
    "силы, таланты, намерения, которые ждут, когда ты увидишь их Свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Чтобы начать, просто напиши мне любую фразу."
)

SYSTEM = (
    "Ты — AILVI, мягкий и точный наставник. Распаковываешь сильные стороны человека, его таланты и ценности. "
    "Говоришь простым русским языком, спокойно и по делу, без водянистости. "
    "Избегаешь спорных тем, бережно направляешь к ясности и конкретным шагам."
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)

def ask_gpt(user_text: str) -> str:
    # Короткий ответ GPT-5 (или другой выбранной модели)
    resp = client.chat.completions.create(
        model="gpt-5",  # можно заменить на более дешёвую, например gpt-4.1-mini
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_text}
        ],
        temperature=0.6,
        max_tokens=500
    )
    return resp.choices[0].message.content.strip()

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = (update.message.text or "").strip()
    if not user_text:
        return
    try:
        answer = ask_gpt(user_text)
    except Exception as e:
        answer = "Сейчас мне трудно ответить технически. Попробуй повторить запрос чуть позже."
    await update.message.reply_text(answer)

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
