from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Contact, ContactName, User, UserContact
import phonenumbers
from phonenumbers import PhoneNumberFormat


# ==========================================================
# إعدادات عامة
# ==========================================================

DEFAULT_WELCOME_POINTS = 3          # نقاط الترحيب عند أول استخدام
SEARCH_COST_POINTS = 1              # تكلفة كل عملية بحث
DEFAULT_UPLOAD_REWARD_EVERY = 3    # عدد جهات الاتصال المطلوبة للمكافأة
DEFAULT_UPLOAD_REWARD_POINTS = 3    # عدد النقاط الممنوحة عند بلوغ العدد المطلوب


# ==========================================================
# أدوات مساعدة
# ==========================================================

@dataclass(slots=True)
class PhoneInfo:
    """نتيجة تحليل رقم الهاتف."""

    raw: str
    normalized: str | None
    is_valid: bool
    is_yemeni: bool
    region: str | None = None
    

def normalize_phone_info(phone: str) -> PhoneInfo:
    """
    تحلل رقم الهاتف وتعيد معلوماته.

    - normalize_phone_info(...).normalized: الرقم بصيغة E.164 إن كان صالحًا
    - is_yemeni: True فقط إذا كان الرقم صالحًا وينتمي لليمن
    - is_valid: True إذا كان الرقم صالحًا أصلًا
    """
    if not phone:
        return PhoneInfo(raw="", normalized=None, is_valid=False, is_yemeni=False)

    phone = phone.strip()
    if not phone:
        return PhoneInfo(raw="", normalized=None, is_valid=False, is_yemeni=False)

    try:
        parsed = phonenumbers.parse(phone, "YE")
    except phonenumbers.NumberParseException:
        return PhoneInfo(raw=phone, normalized=None, is_valid=False, is_yemeni=False)

    region = phonenumbers.region_code_for_number(parsed)
    is_valid = phonenumbers.is_valid_number(parsed)
    normalized = (
        phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        if is_valid
        else None
    )
    return PhoneInfo(
        raw=phone,
        normalized=normalized,
        is_valid=is_valid,
        is_yemeni=is_valid and region == "YE",
        region=region,
    )


def normalize_phone(phone: str) -> str | None:
    """
    واجهة توافقية للملفات الأخرى:
    تعيد رقمًا يمنيًا موحدًا فقط، وإلا None.
    """
    info = normalize_phone_info(phone)
    if info.is_valid and info.is_yemeni:
        return info.normalized
    return None


def _extract_field(payload: Any, field: str) -> str:
    """يدعم كائن telegram.Contact وكذلك dict عادي."""
    value = getattr(payload, field, None)
    if value is None and isinstance(payload, dict):
        value = payload.get(field)
    return (value or "").strip()


async def _get_contact_names(db: AsyncSession, contact_id: int) -> list[str]:
    """
    يجلب كل الأسماء المرتبطة برقم معيّن باستعلام صريح ومباشر.
    مقصودة بديلاً عن contact.names (كعلاقة ORM) لأن الوصول للعلاقة
    كخاصية قد يُحدث lazy-load غير آمن في بيئة async ويسبب
    MissingGreenlet. هذا الاستعلام الصريح آمن دائمًا.
    """
    result = await db.execute(
        select(ContactName.name).where(ContactName.contact_id == contact_id)
    )
    return list(result.scalars().all())


# ==========================================================
# المستخدمون
# ==========================================================

async def get_or_create_user(
    db: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    user = await db.get(User, telegram_id)

    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            points=DEFAULT_WELCOME_POINTS,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    changed = False
    if username and user.username != username:
        user.username = username
        changed = True
    if first_name and user.first_name != first_name:
        user.first_name = first_name
        changed = True

    if changed:
        await db.commit()
        await db.refresh(user)

    return user


# ==========================================================
# رفع جهة اتصال
# ==========================================================

async def handle_incoming_contact(
    db: AsyncSession,
    telegram_id: int,
    payload: Any,
    username: str | None = None,
    first_name: str | None = None,
) -> dict[str, Any]:
    """
    يحفظ رقم جهة اتصال يرسلها المستخدم.
    - إذا كان قد رفع هذا الرقم من قبل -> لا يُحتسب (مكرر).
    - إذا رفع الرقم لأول مرة -> يُحتسب ضمن عداده، وعند كل 10 جهات يُمنح مكافأة نقاط.
    - إذا كان الرقم موجوداً مسبقاً برفع مستخدم آخر -> يُسمح للمستخدم الحالي
      بربطه أيضاً (يفيد في بناء قاعدة بيانات الأسماء/كاشف الأرقام) ويُحتسب له.
    """
    user = await get_or_create_user(db, telegram_id, username, first_name)


    raw_phone = _extract_field(payload, "phone_number")
    phone_info = normalize_phone_info(raw_phone)

    if not phone_info.is_valid:
        return {
            "ok": False,
            "duplicate": False,
            "message": "❌ رقم الهاتف غير صالح، حاول مرة أخرى.",
        }

    if not phone_info.is_yemeni:
        return {
            "ok": False,
            "duplicate": False,
            "message": ("❌ عذرًا، نحن ندعم الارقام اليمنية فقط"),
        }

    phone = phone_info.normalized

    given_name = _extract_field(payload, "first_name")
    last_name = _extract_field(payload, "last_name")
    full_name = f"{given_name} {last_name}".strip() or "بدون اسم"

    result = await db.execute(select(Contact).where(Contact.phone == phone))
    contact = result.scalar_one_or_none()

    if contact is None:
        contact = Contact(phone=phone)
        db.add(contact)
        await db.flush()  # لضمان توليد contact.id قبل استخدامه بالأسفل

    existing_link = await db.execute(
        select(UserContact).where(
            UserContact.user_id == telegram_id,
            UserContact.contact_id == contact.id,
        )
    )
    if existing_link.scalar_one_or_none() is not None:
        await db.rollback()
        return {
            "ok": False,
            "duplicate": True,
            "message": (
                "⚠️ *عفوًا، لم تُحتسب هذه الجهة*\n"
                "هي مكررة وسبق لك أن رفعتها من قبل."
            ),
        }

    db.add(UserContact(user_id=telegram_id, contact_id=contact.id))

    existing_names = set(await _get_contact_names(db, contact.id))
    if full_name not in existing_names:
        db.add(ContactName(contact_id=contact.id, name=full_name))

    user.uploaded_contacts += 1
    rewarded = user.uploaded_contacts % DEFAULT_UPLOAD_REWARD_EVERY == 0

    if rewarded:
        user.points += DEFAULT_UPLOAD_REWARD_POINTS

    await db.commit()
    await db.refresh(user)

    if rewarded:
        message = (
            "✅ *تم حفظ جهة الاتصال بنجاح*\n\n"
            f"🎉 لقد رفعت *{DEFAULT_UPLOAD_REWARD_EVERY}* جهات اتصال، "
            f"كسبت معنا *{DEFAULT_UPLOAD_REWARD_POINTS}* نقاط!\n"
            f"💰 رصيدك الآن: *{user.points}* نقطة."
        )
    else:
        remaining = DEFAULT_UPLOAD_REWARD_EVERY - (
            user.uploaded_contacts % DEFAULT_UPLOAD_REWARD_EVERY
        )
        message = (
            "✅ *تم حفظ جهة الاتصال بنجاح*\n\n"
            f"📊 ارفع *{remaining}* جهة اتصال أخرى لتكسب "
            f"*{DEFAULT_UPLOAD_REWARD_POINTS}* نقاط."
        )

    return {
        "ok": True,
        "duplicate": False,
        "rewarded": rewarded,
        "points": user.points,
        "uploaded_contacts": user.uploaded_contacts,
        "message": message,
    }


# ==========================================================
# حصاد صامت أثناء البحث
# ==========================================================

async def _harvest_contact_silently(
    db: AsyncSession,
    telegram_id: int,
    phone: str,
    full_name: str,
) -> None:
    """
    عندما يشارك المستخدم جهة اتصال للبحث عنها (كشف رقم)، تكون بطاقة
    جهة الاتصال غالبًا تحمل اسمًا محفوظًا لديه مسبقًا في هاتفه.
    هذه بيانات مفيدة لقاعدتنا، فنقوم بتخزينها بصمت:
    - لا نزيد uploaded_contacts.
    - لا نمنح أي مكافأة/نقاط.
    - لا نُعلم المستخدم بأي شيء عن هذا الحفظ.
    لأن نيّته كانت الاستعلام فقط، وليس الرفع.
    """
    if not phone:
        return

    result = await db.execute(select(Contact).where(Contact.phone == phone))
    contact = result.scalar_one_or_none()

    if contact is None:
        contact = Contact(phone=phone)
        db.add(contact)
        await db.flush()

    existing_link = await db.execute(
        select(UserContact).where(
            UserContact.user_id == telegram_id,
            UserContact.contact_id == contact.id,
        )
    )
    if existing_link.scalar_one_or_none() is None:
        db.add(UserContact(user_id=telegram_id, contact_id=contact.id))

    if full_name:
        existing_names = set(await _get_contact_names(db, contact.id))
        if full_name not in existing_names:
            db.add(ContactName(contact_id=contact.id, name=full_name))

    await db.commit()


# ==========================================================
# البحث عن جهة اتصال
# ==========================================================

async def handle_search_request(
    db: AsyncSession,
    telegram_id: int,
    query: str,
    contact_payload: Any = None,
    username: str | None = None,
    first_name: str | None = None,
) -> dict[str, Any]:
    """
    يبحث عن رقم (أو اسم) ويخصم نقطة عند نجاح البحث فقط.
    يقبل رقم هاتف أو اسمًا نصيًا للبحث به.

    إذا مرّرت contact_payload (بطاقة جهة اتصال تليجرام) يتم حصاد
    رقمها/اسمها بصمت وتخزينها في القاعدة دون احتساب أي نقاط للمستخدم،
    بغض النظر عن نتيجة البحث نفسها.
    """

    if contact_payload is not None:
        harvested_info = normalize_phone_info(_extract_field(contact_payload, "phone_number"))
        harvested_given = _extract_field(contact_payload, "first_name")
        harvested_last = _extract_field(contact_payload, "last_name")
        harvested_name = f"{harvested_given} {harvested_last}".strip()

        # نحصد فقط الأرقام اليمنية الصحيحة، أما غير اليمني أو غير الصالح
        # فلا نمنع البحث بسببه، فقط نتجاهل التخزين الصامت.
        if harvested_info.is_valid and harvested_info.is_yemeni and harvested_info.normalized:
            await _harvest_contact_silently(
                db=db,
                telegram_id=telegram_id,
                phone=harvested_info.normalized,
                full_name=harvested_name,
            )

    user = await get_or_create_user(db, telegram_id, username, first_name)

    if user.points < SEARCH_COST_POINTS:
        return {
            "ok": False,
            "need_points": True,
            "results": [],
            "remaining_points": user.points,
            "message": (
                "⚠️ *ليس لديك نقاط كافية للاستعلام*\n\n"
                "قم بمشاركة جهات اتصالك للحصول على نقاط."
            ),
        }

    query = (query or "").strip()
    if not query:
        return {
            "ok": False,
            "results": [],
            "remaining_points": user.points,
            "message": "❌ الرجاء إرسال رقم هاتف أو اسم صحيح للبحث.",
        }

    digits = re.sub(r"\D", "", query)

    if digits:
        stmt = select(Contact).where(Contact.phone.like(f"%{digits}%"))
    else:
        stmt = (
            select(Contact)
            .join(Contact.names)
            .where(ContactName.name.ilike(f"%{query}%"))
            .distinct()
        )

    result = await db.execute(stmt.limit(10))
    contacts = result.scalars().unique().all()

    if not contacts:
        return {
            "ok": True,
            "results": [],
            "remaining_points": user.points,
            "message": "🔍 لم يتم العثور على أي نتائج مطابقة.",
        }

    user.points -= SEARCH_COST_POINTS
    await db.commit()
    await db.refresh(user)

    results = []
    for c in contacts:
        names = await _get_contact_names(db, c.id)
        results.append({"phone": c.phone, "names": names})

    return {
        "ok": True,
        "results": results,
        "remaining_points": user.points,
        "message": "✅ *تم العثور على النتائج التالية:*",
    }



async def record_contact(
    db: AsyncSession,
    phone: str,
    name: str,
) -> bool:

    full_name = name.strip() or "بدون اسم"

    result = await db.execute(
        select(Contact).where(
            Contact.phone == phone
        )
    )

    contact = result.scalar_one_or_none()

    if contact is None:
        contact = Contact(phone=phone)
        db.add(contact)

        await db.flush()

    existing_names = set(
        await _get_contact_names(
            db,
            contact.id
        )
    )

    if full_name not in existing_names:
        db.add(
            ContactName(
                contact_id=contact.id,
                name=full_name
            )
        )

    return True