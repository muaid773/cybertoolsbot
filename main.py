import asyncio

from fastapi import FastAPI
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    CommandHandler,
    CallbackQueryHandler,
)

from config import TOKEN
from handlers import (
    contact_action_callback,
    contact_handler,
    weather_handler,
    start_command_handel,
    text_msg_handlers,
)

from initdb import create_tables
from keyboards import CONTACT_ACTION_POINTS, CONTACT_ACTION_SEARCH


app = FastAPI()

telegram_app = None


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }


async def start_bot():

    global telegram_app

    if not TOKEN:
        raise RuntimeError("NOT Found token")

    telegram_app = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    telegram_app.add_handler(
        CommandHandler(
            "start",
            start_command_handel
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT,
            text_msg_handlers
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.CONTACT,
            contact_handler
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.LOCATION,
            weather_handler
        )
    )

    telegram_app.add_handler(
        CallbackQueryHandler(
            contact_action_callback,
            pattern=f"^({CONTACT_ACTION_POINTS}|{CONTACT_ACTION_SEARCH})$"
        )
    )

    await telegram_app.initialize()
    await telegram_app.start()

    await telegram_app.updater.start_polling()


async def stop_bot():

    if telegram_app:

        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


@app.on_event("startup")
async def startup():

    print("init database tables")

    await create_tables()

    print("start telegram bot")

    asyncio.create_task(
        start_bot()
    )


@app.on_event("shutdown")
async def shutdown():

    await stop_bot()