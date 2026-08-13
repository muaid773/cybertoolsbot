from functools import wraps
from telegram import Update, ChatMember
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from config import REQUIRED_CHANNELS, ADMIN_CHAT_ID
from keyboards import channel_subscription_keyboard
def require_subscription(func):
    @wraps(func)
    async def wrapper(update:Update, context:ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        not_subscripted = []
        for channel in REQUIRED_CHANNELS:
            try:
                member:ChatMember = await context.bot.get_chat_member(channel["id"], update.effective_chat.id)
                if member.status in [ChatMember.LEFT, ChatMember.BANNED]:
                    not_subscripted.append(channel)
            except BadRequest as e:
                text = (
                    "⚠ حدث خطاء من التحقق الاجباري في القناة.\n\n"
                    f"{e}"
                )
                await context.bot.send_message(ADMIN_CHAT_ID, text=text)
        if not_subscripted:
            chname = "القناة" if len(not_subscripted) == 1 else "القنوات"
            await update.message.reply_text(
                text=f"اشترك في {chname} التالية اولا",
                reply_markup=channel_subscription_keyboard(not_subscripted)
            )
        await func(update, context, *args, **kwargs)
    return wrapper