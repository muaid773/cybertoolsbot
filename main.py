import asyncio
from typing import List
from pydantic import BaseModel
from fastapi import FastAPI, Depends
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    CommandHandler,
    CallbackQueryHandler,
)
from sqlalchemy.ext.asyncio import AsyncSession
from config import TOKEN
from db.dbase import get_db
from handlers import (
    contact_action_callback,
    contact_handler,
    weather_handler,
    start_command_handel,
    text_msg_handlers,
)

from initdb import create_tables
from keyboards import CONTACT_ACTION_POINTS, CONTACT_ACTION_SEARCH
from services.users_contacts import record_contact

class Contacts(BaseModel):
    phone:str
    name:str
class AddContacts(BaseModel):
    contacts:List[Contacts]

app = FastAPI()

telegram_app = None


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }
@app.post("/contacts")
async def add_contact(contact_payload:AddContacts, db: AsyncSession = Depends(get_db),):
    for cont in contact_payload.contacts:
        await record_contact(db, cont.phone, cont.name)
    return {"status": "ok"}

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