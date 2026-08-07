from tracemalloc import start

import httpx
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler, CallbackQueryHandler
from config import TOKEN
from handlers import contact_action_callback, contact_handler, weather_handler, start_command_handel, text_msg_handlers
from initdb import create_tables
from keyboards import CONTACT_ACTION_POINTS, CONTACT_ACTION_SEARCH
def main():
    if not TOKEN:
        raise RuntimeError("NOT Found token")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command_handel))
    app.add_handler(MessageHandler(filters.TEXT, text_msg_handlers))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(MessageHandler(filters.LOCATION, weather_handler))
    app.add_handler(
    CallbackQueryHandler(
        contact_action_callback,
        pattern=f"^({CONTACT_ACTION_POINTS}|{CONTACT_ACTION_SEARCH})$"
    )
)

    app.run_polling()

if __name__ == "__main__":
    print("init database tables")
    asyncio.run(create_tables())
    print("start bot run")
    main()