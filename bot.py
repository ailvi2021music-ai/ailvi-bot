import os
import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    filters, Defaults
)

# ===== Логирование =====
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
log = logging.getLogger("ailvi-bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

WELCOME = (
    "<b>Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻</b>\n\n"
    "Добро пожаловать в пространство, где <i>Сердце</i> узнаёт себя заново.\n\n"
    "Чтобы начать глубокую распаковку — напиши: <b>Начинаем</b>"
)

STARTED = (
    "С радостью. Начнём с самого важного для тебя сейчас. ✨\n\n"
    "<b>Расскажи коротко</b>: что прямо сейчас больше всего волнует — "
    "про смысл, призвание, отношения с работой или ощущение себя?"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.info("Start from %s", update.effective_user.id if update.effective_user else "?")
    await update.message.reply_html(WELCOME, disable_web_page_preview=True)

async def any_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip().lower()
    log.info("Text from %s: %s", update.effective_user.id if update.effective_user else "?", text)

    if text == "начинаем":
        await update.message.reply_html(STARTED)
        return

    await update.message.reply_html(
        f"Я с тобой. Ты написал(а): <i>{update.message.text}</i>\n\n"
        "Если готов(а) к распаковке — напиши: <b>Начинаем</b>"
    )

def main() -> None:
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    # Включаем HTML глобально
    defaults = Defaults(parse_mode=ParseMode.HTML)

    app = Application.builder().token(TOKEN).defaults(defaults).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_text))

    log.info("Application started (polling)")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
