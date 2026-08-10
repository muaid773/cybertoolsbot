from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


def main_mnue_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
       [KeyboardButton(text="🔍 اقتناص حساب"), KeyboardButton(text="🔗 فحص الروابط")],
       [KeyboardButton(text="📈 تحليل اسم النظاق"), KeyboardButton(text="📞 كشف الأرقام")],
       [KeyboardButton(text="⛅الطقس", request_location=True), KeyboardButton(text="⭐ نقاطي")],
       [KeyboardButton(text="👩‍💻معلومات المطور👨‍💻")]
    ]

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def share_contacts_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
      [[KeyboardButton(text="📲مشاركه جهات اتصال", request_contact=True)],
       [KeyboardButton(text="🏠 عودة الى الرئيسية")]
      ],
         resize_keyboard=True)

def back_home_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
    [
       [KeyboardButton(text="🏠 عودة الى الرئيسية")]
      ],
         resize_keyboard=True)


# ==========================================================
# أزرار شفافة (Inline) لاختيار الإجراء عند استقبال جهة اتصال
# ==========================================================

CONTACT_ACTION_POINTS = "contact_action_points"
CONTACT_ACTION_SEARCH = "contact_action_search"


def contact_action_inline_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="💰 احتساب نقاط لي", callback_data=CONTACT_ACTION_POINTS)],
        [InlineKeyboardButton(text="🔍 البحث عن هذا الرقم", callback_data=CONTACT_ACTION_SEARCH)],
    ]
    return InlineKeyboardMarkup(keyboard)

def channel_subscription_keyboard(channels:list) -> InlineKeyboardMarkup:
    keyboard = [  [InlineKeyboardButton(ch["label"], url=f"https://t.me/{ch["username"]}")] for ch in channels]
    keyboard.append(InlineKeyboardButton("✔ تحقق من الاشتراك", callback_data="check_sub"))

    return InlineKeyboardMarkup(keyboard)