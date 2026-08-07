import re

from telegram import Update
from telegram.ext import ContextTypes
from keyboards import (
    back_home_keyboard,
    main_mnue_keyboard,
    share_contacts_keyboard,
    contact_action_inline_keyboard,
    CONTACT_ACTION_POINTS,
    CONTACT_ACTION_SEARCH,
)
from services.link_servoces import analyze_url, analyze_domain
from services.scan_accs import search_username
from services.users_contacts import (
    get_or_create_user,
    handle_incoming_contact,
    handle_search_request,
)
from services.weather import ask_groq, get_weather
from config import SYSTEM_PROMT, WELCOME_MSG, DEV_INFO
from db.dbase import AsyncSessionLocal


# ==========================================================
# أدوات مساعدة لتنسيق Markdown
# ==========================================================

_MARKDOWN_RESERVED = re.compile(r"([_*`\[])")


def md_escape(text: str) -> str:
    """
    يهرّب الأحرف الخاصة بوضع Markdown (النسخة القديمة في تيليجرام)
    حتى لا تُكسر الرسالة عند احتواء اسم جهة اتصال على _ أو * أو ` أو [.
    """
    if not text:
        return text
    return _MARKDOWN_RESERVED.sub(r"\\\1", text)


def _format_search_result_text(result: dict) -> str:
    """يبني نص رد البحث (نتائج أو رسالة خطأ/تنبيه) بتنسيق Markdown."""
    if not result["ok"] or not result["results"]:
        return result["message"]

    lines = [
        result["message"],
        f"💰 *النقاط المتبقية:* {result['remaining_points']}",
        "",
    ]

    for item in result["results"]:
        if item["names"]:
            names = "، ".join(f"*{md_escape(n)}*" for n in item["names"])
        else:
            names = "_بدون اسم_"

        lines.extend([
            f"📱 `{item['phone']}`",
            f"👤 {names}",
            "────────────",
        ])

    return "\n".join(lines)


async def _reply_search_result(update: Update, result: dict) -> None:
    await update.message.reply_text(
        _format_search_result_text(result), parse_mode="Markdown"
    )


async def start_command_handel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        update.effective_chat.id,
        text=WELCOME_MSG,
        reply_markup=main_mnue_keyboard(),
        parse_mode="HTML"
    )

async def dev_info_handel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        update.effective_chat.id,
        text=DEV_INFO,
        reply_markup=main_mnue_keyboard(),
        parse_mode="HTML"
    )


async def weather_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.first_name or "عمنا"
    location = f"lat{update.message.location.latitude} - Long{update.message.location.longitude}"
    weather = await get_weather(update.message.location.latitude, update.message.location.longitude)
    reply = await ask_groq(
        f"اسم المستخدم هو {username}. موقعه هو {location} وبيانات الطقس: {weather}",
        system_prompt=SYSTEM_PROMT
    )
    await context.bot.send_message(update.effective_chat.id, text=reply, parse_mode="Markdown", reply_markup=main_mnue_keyboard())


# ==========================================================
# طلب البحث عن جهة اتصال (تفعيل وضع "كشف الأرقام")
# ==========================================================

async def search_contact_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    telegram_id = update.effective_user.id

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(
            db=db,
            telegram_id=telegram_id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )

        if user.points < 1:
            await update.message.reply_text(
                "⚠️ *ليس لديك نقاط كافية.*\n\n"
                "قم بمشاركة جهات اتصالك للحصول على نقاط.",
                reply_markup=share_contacts_keyboard(),
                parse_mode="Markdown",
            )
            # نبقيه في نفس وضع "كشف الأرقام" حتى بعد الرفع، ليكمل البحث تلقائيًا
            context.user_data["state"] = "awaiting_contact"
            context.user_data["needs_points_first"] = True
            return

    context.user_data["state"] = "awaiting_contact"

    await update.message.reply_text(
        "📇 أرسل رقم الهاتف (أو شارك جهة الاتصال) التي تريد البحث عنها.\n"
        "يمكنك الاستعلام عدة مرات متتالية، واضغط 🏠 عودة الى الرئيسية عند الانتهاء.",
        reply_markup=share_contacts_keyboard(),
        parse_mode="Markdown",
    )


# ==========================================================
# استقبال جهة اتصال
# ==========================================================

async def contact_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    contact = update.message.contact
    if not contact:
        return

    telegram_id = update.effective_user.id
    state = context.user_data.get("state")

    # --- داخل وضع "كشف الأرقام": لا نفترض نيته، نسأله ---
    if state == "awaiting_contact":
        context.user_data["pending_contact"] = {
            "phone_number": contact.phone_number,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
        }
        await update.message.reply_text(
            "📇 ماذا تريد أن تفعل بجهة الاتصال هذه؟",
            reply_markup=contact_action_inline_keyboard(),
        )
        return

    # --- في أي وضع آخر: مشاركة جهة اتصال تُحسب دائمًا لكسب النقاط ---
    async with AsyncSessionLocal() as db:
        result = await handle_incoming_contact(
            db=db,
            telegram_id=telegram_id,
            payload=contact,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )

    await update.message.reply_text(result["message"], parse_mode="Markdown")

    # إن كان قد جاء من مسار "لا يملك نقاطًا كافية أثناء الاستعلام"، نعيده لوضع
    # الاستعلام تلقائيًا ليكمل البحث بمجرد أن تتوفر لديه نقاط.
    if context.user_data.pop("needs_points_first", False):
        context.user_data["state"] = "awaiting_contact"


# ==========================================================
# استقبال اختيار المستخدم من الأزرار الشفافة (Inline Buttons)
# ==========================================================

async def contact_action_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    pending = context.user_data.get("pending_contact")
    if not pending:
        await query.edit_message_text(
            "⚠️ انتهت صلاحية هذا الطلب، أرسل جهة الاتصال مرة أخرى."
        )
        return

    telegram_id = update.effective_user.id

    async with AsyncSessionLocal() as db:
        if query.data == CONTACT_ACTION_POINTS:
            result = await handle_incoming_contact(
                db=db,
                telegram_id=telegram_id,
                payload=pending,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
            )
            await query.edit_message_text(result["message"], parse_mode="Markdown")

        elif query.data == CONTACT_ACTION_SEARCH:
            result = await handle_search_request(
                db=db,
                telegram_id=telegram_id,
                query=pending["phone_number"],
                contact_payload=pending,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
            )
            await query.edit_message_text(
                _format_search_result_text(result), parse_mode="Markdown"
            )

    # نمسح الجهة المعلّقة فقط. حالة "awaiting_contact" تبقى كما هي
    # ليستمر المستخدم بإرسال أرقام أخرى دون الحاجة لإعادة فتح القائمة.
    context.user_data.pop("pending_contact", None)


# ==========================================================
# راوتر الرسائل النصية (القائمة الرئيسية)
# ==========================================================

async def text_msg_handlers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🏠 عودة الى الرئيسية":
        context.user_data.clear()
        await update.message.reply_text(
            "🏠 القائمة الرئيسية",
            reply_markup=main_mnue_keyboard(),
        )
        return

    if text == "👩‍💻معلومات المطور👨‍💻":
        await dev_info_handel(update, context)

    if text == "🔍 اقتناص حساب":
        context.user_data["state"] = "awaiting_username"
        await context.bot.send_message(
            update.effective_chat.id,
            "قم بكتابة اسم المستخدم الذي تريد اقتناصه.",
            reply_markup=back_home_keyboard()
        )
        return

    if text == "🔗 فحص الروابط":
        await context.bot.send_message(
            update.effective_chat.id,
            "الميزة غير مفعلة حاليًا.",
        )
        return

    if text == "📞 كشف الأرقام":
        await search_contact_handler(update, context)
        return

    if text == "📈 تحليل اسم النظاق":
        context.user_data["state"] = "awaiting_domain"
        await context.bot.send_message(update.effective_chat.id, "ارسل لنا اسم النطاق", reply_markup=back_home_keyboard())
        return

    status = context.user_data.get("state")

    if status == "awaiting_username":
        username = text.strip()
        context.user_data["state"] = None
        await context.bot.send_message(update.effective_chat.id, "جاري البحث عن الحسابات...")
        result = await search_username(username)
        await context.bot.send_message(update.effective_chat.id, text=result, parse_mode="HTML", reply_markup=main_mnue_keyboard())
        return

    if status == "awaiting_link":
        url = text.strip()
        context.user_data["state"] = None
        await context.bot.send_message(update.effective_chat.id, "جاري التحليل...")
        result = await analyze_url(url)
        await context.bot.send_message(update.effective_chat.id, text=result, parse_mode="Markdown", reply_markup=main_mnue_keyboard())
        return

    if status == "awaiting_domain":
        domain = text.strip()
        await context.bot.send_message(update.effective_chat.id, "جاري التحليل...")
        result = await analyze_domain(domain)
        await context.bot.send_message(update.effective_chat.id, text=result, parse_mode="Markdown", reply_markup=main_mnue_keyboard())
        return

    # --- البحث عن جهة اتصال عبر إرسال الرقم كنص، ويبقى الوضع مفعّلاً للاستعلام المتكرر ---
    if status == "awaiting_contact":
        query = text.strip()

        async with AsyncSessionLocal() as db:
            result = await handle_search_request(
                db=db,
                telegram_id=update.effective_user.id,
                query=query,
                contact_payload=None,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
            )

        await _reply_search_result(update, result)
        # لا نُصفّر الحالة هنا: يبقى بإمكانه الاستعلام مرة بعد مرة
        # حتى يضغط "🏠 عودة الى الرئيسية".