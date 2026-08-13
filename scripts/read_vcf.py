import re
import base64
import quopri
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
import phonenumbers
from phonenumbers import PhoneNumberFormat
import asyncio
from db.dbase import AsyncSessionLocal
from db.models import Contact, ContactName
import httpx
def normalize_phone_info(phone: str):
    """
    تحلل رقم الهاتف وتعيد معلوماته.

    - normalize_phone_info(...).normalized: الرقم بصيغة E.164 إن كان صالحًا
    - is_yemeni: True فقط إذا كان الرقم صالحًا وينتمي لليمن
    - is_valid: True إذا كان الرقم صالحًا أصلًا
    """
    if not phone:
        return None
    phone = phone.strip()
    if not phone:
        return None

    try:
        parsed = phonenumbers.parse(phone, "YE")
    except phonenumbers.NumberParseException:
        return None
    
    region = phonenumbers.region_code_for_number(parsed)
    is_valid = phonenumbers.is_valid_number(parsed)
    normalized = (
        phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        if (is_valid and (region == "YE"))
        else None
    )
    return normalized

def decode_value(value, params):
    """يفك تشفير القيمة حسب الباراميترز حقها"""
    value = value.strip()

    # 1. فك السطور المتكسرة خلاص عملناها قبل

    # 2. BASE64
    if 'ENCODING=b' in params or 'ENCODING=BASE64' in params:
        try:
            return base64.b64decode(value).decode('utf-8', errors='ignore')
        except: pass

    # 3. QUOTED-PRINTABLE
    if 'ENCODING=QUOTED-PRINTABLE' in params or 'QUOTED-PRINTABLE' in params:
        try:
            # لازم نحول =D8=A7 لـ =D8=A7
            value = value.replace('=','=')
            return quopri.decodestring(value.encode('utf-8')).decode('utf-8', errors='ignore')
        except: pass

    # 4. CHARSET
    charset_match = re.search(r'CHARSET=([^;:]+)', params, re.I)
    if charset_match:
        charset = charset_match.group(1)
        try:
            return value.encode('latin1').decode(charset, errors='ignore')
        except: pass

    return value


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


async def record_contact(
    db: AsyncSession,
    phone: str,
    name: str,
) -> dict[str, Any]:

    full_name = name.strip() or "بدون اسم"

    result = await db.execute(select(Contact).where(Contact.phone == phone))
    contact = result.scalar_one_or_none()

    if contact is None:
        contact = Contact(phone=phone)
        db.add(contact)
        await db.flush()  # لضمان توليد contact.id قبل استخدامه بالأسفل
    else:
        print("ADDED:", contact.phone)
    

    existing_names = set(await _get_contact_names(db, contact.id))
    if full_name not in existing_names:
        db.add(ContactName(contact_id=contact.id, name=full_name))

    await db.commit()

async def extract_contacts_from_vcf(vcf_file):

    with open(vcf_file, 'r', encoding='utf-8', errors='ignore') as f:
        vcf_data = f.read()

    # نصلح التكسير الرسمي: سطر ينتهي بـ = وبعده سطر جديد + مسافة
    vcf_data = re.sub(r'=\r?\n[ \t]', '', vcf_data)

    vcards = re.split(r'BEGIN:VCARD', vcf_data, flags=re.I)
    async with AsyncSessionLocal() as db:
        contacts = {"contacts":[]}
        for vcard in vcards:
            if 'END:VCARD' not in vcard:
                continue

            name = "بدون اسم"
            phone = None

            # 1. استخراج الاسم: نجرب FN بعدين N
            fn_match = re.search(r'FN([^:]*):(.*)', vcard, re.I)
            if fn_match:
                params, raw_name = fn_match.groups()
                name = decode_value(raw_name, params)
            else: # لو مافي FN نجرب N
                n_match = re.search(r'N([^:]*):([^;]*);([^;]*)', vcard, re.I)
                if n_match:
                    params, last, first = n_match.groups()
                    name = decode_value(f"{first} {last}", params).strip()

            # 2. استخراج الرقم: ناخذ اول TEL فيه رقم
            tel_matches = re.findall(r'TEL([^:]*):([^\r\n]+)', vcard, re.I)
            for params, raw_phone in tel_matches:
                phone_clean = re.sub(r'[^\d+]', '', raw_phone) # نشيل كل شي الا رقم و +
                if len(phone_clean) > 6: # نتأكد انه رقم حقي
                    phone = phone_clean
                    break # اخذنا اول واحد
            phone = normalize_phone_info(phone)
            if type(phone) == str:
                contacts['contacts'].append(
                    {
                        "name":name,  "phone":phone
                    }
                )
        async with httpx.AsyncClient() as cli:
                    res = await cli.post("http://127.0.0.1:8000/contacts", json=contacts)
                    print(res)
    # print(f"\nتم استخراج {contacts} جهة اتصال")
    return contacts

if __name__ == "__main__":
    asyncio.run(extract_contacts_from_vcf("C:/Users/pc/Downloads/vcards.vcf"))