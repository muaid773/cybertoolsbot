from functools import wraps
from telegram import Update, ChatMember
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from config import REQUIRED_CHANNELS, ADMIN_CHAT_ID
from keyboards import channel_subscription_keyboard


async def get_not_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    not_subscripted = []

    for channel in REQUIRED_CHANNELS:
        try:
            member: ChatMember = await context.bot.get_chat_member(
                channel["id"],
                update.effective_user.id
            )

            if member.status in [ChatMember.LEFT, ChatMember.BANNED]:
                not_subscripted.append(channel)

        except BadRequest as e:
            print(f"Error checking subscription for channel {channel['id']}: {e}")

    return not_subscripted


def require_subscription(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):

        if ADMIN_CHAT_ID and update.effective_user.id == ADMIN_CHAT_ID:
            return await func(update, context, *args, **kwargs)

        not_subscripted = await get_not_subscribed(update, context)

        if not_subscripted:
            chname = "القناة" if len(not_subscripted) == 1 else "القنوات"

            await update.effective_message.reply_text(
                text=f"اشترك في {chname} التالية أولا",
                reply_markup=channel_subscription_keyboard(not_subscripted)
            )

            return

        return await func(update, context, *args, **kwargs)

    return wrapper