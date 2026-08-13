import asyncio
import re

from typing import List
from pydantic import BaseModel, field_validator
from fastapi import FastAPI, Depends, HTTPException, Header

from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    CommandHandler,
    CallbackQueryHandler,
)
from sqlalchemy.ext.asyncio import AsyncSession
from config import TOKEN, CONTACTS_API_KEY
from db.dbase import get_db
from handlers import (
    check_subscription,
    contact_action_callback,
    contact_handler,
    weather_handler,
    start_command_handel,
    text_msg_handlers,
)

from initdb import create_tables
from keyboards import CONTACT_ACTION_POINTS, CONTACT_ACTION_SEARCH
from services.users_contacts import record_contact

PHONE_RE = re.compile(r"^\+?[0-9]{6,15}$")
 
 
class Contacts(BaseModel):
    phone: str
    name: str
 
    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not PHONE_RE.match(v):
            raise ValueError("رقم هاتف غير صالح")
        return v
 
 
class AddContacts(BaseModel):
    contacts: List[Contacts]
 
 
class ContactResult(BaseModel):
    saved: int
    failed: int
    errors: List[str] = []
 
 
app = FastAPI()
 
 
def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != CONTACTS_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
 
 
@app.get("/health")
async def health():
    return {"status": "ok"}
 
 
@app.post("/contacts", response_model=ContactResult)
async def add_contact(
    contact_payload: AddContacts,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    if not contact_payload.contacts:
        raise HTTPException(status_code=400, detail="لا توجد جهات اتصال في الطلب")
 
    saved = 0
    errors: List[str] = []
 
    async def _save(cont: Contacts):
        nonlocal saved
        try:
            await record_contact(db, cont.phone, cont.name)
            saved += 1
        except Exception as e:
            errors.append(f"{cont.phone}: {e}")
 
    # تنفيذ متوازٍ بدل حلقة تسلسلية بطيئة
    await asyncio.gather(*(_save(c) for c in contact_payload.contacts))
 
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"فشل حفظ البيانات: {e}")
 
    return ContactResult(
        saved=saved,
        failed=len(errors),
        errors=errors,
    )


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

    telegram_app.add_handler(
        CallbackQueryHandler(check_subscription, pattern="^check_sub$")
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