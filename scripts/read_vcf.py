import re
import base64
import quopri
import asyncio
from typing import Any

import httpx
import phonenumbers
from phonenumbers import PhoneNumberFormat


API_URL = "https://cybertoolsbot.onrender.com/contacts"

API_KEY = "123qwessasnid32dwq3-3e3e8u382-=12e93"

# يجب أن يطابق MAX_CONTACTS_PER_REQUEST في السيرفر
MAX_CONTACTS_PER_REQUEST = 200

# عدد الطلبات التي يمكن إرسالها في نفس الوقت
MAX_CONCURRENT_REQUESTS = 5


PHONE_RE = re.compile(r"^\+?[0-9]{6,15}$")


def normalize_phone_info(phone: str | None) -> str | None:
    """
    تحويل رقم الهاتف إلى E.164.

    مثال:
        777123456
        =>
        +967777123456

    ترجع None إذا كان الرقم غير صالح أو ليس رقمًا يمنيًا.
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

    if region != "YE":
        return None

    if not phonenumbers.is_valid_number(parsed):
        return None

    normalized = phonenumbers.format_number(
        parsed,
        PhoneNumberFormat.E164
    )

    # تأكيد أن الرقم مطابق لما يقبله FastAPI
    if not PHONE_RE.fullmatch(normalized):
        return None

    return normalized


def decode_value(value: str, params: str) -> str:
    """
    فك ترميز قيمة من VCF.
    يدعم:
    - BASE64
    - QUOTED-PRINTABLE
    - CHARSET
    """

    value = value.strip()
    params_upper = params.upper()

    # BASE64
    if "ENCODING=B" in params_upper or "ENCODING=BASE64" in params_upper:
        try:
            return base64.b64decode(value).decode(
                "utf-8",
                errors="ignore"
            )
        except Exception:
            pass

    # QUOTED-PRINTABLE
    if (
        "ENCODING=QUOTED-PRINTABLE" in params_upper
        or "QUOTED-PRINTABLE" in params_upper
    ):
        try:
            return quopri.decodestring(
                value.encode("utf-8")
            ).decode(
                "utf-8",
                errors="ignore"
            )
        except Exception:
            pass

    # CHARSET
    charset_match = re.search(
        r"CHARSET=([^;:]+)",
        params,
        re.I
    )

    if charset_match:
        charset = charset_match.group(1).strip()

        try:
            return value.encode("latin1").decode(
                charset,
                errors="ignore"
            )
        except Exception:
            pass

    return value


def extract_name(vcard: str) -> str:
    """
    استخراج اسم جهة الاتصال من VCARD.
    يحاول FN أولاً ثم N.
    """

    # FN
    fn_match = re.search(
        r"^FN([^:]*):(.*)$",
        vcard,
        re.I | re.M
    )

    if fn_match:
        params, raw_name = fn_match.groups()

        name = decode_value(
            raw_name,
            params
        ).strip()

        if name:
            return name

    # N
    n_match = re.search(
        r"^N([^:]*):([^;]*);([^;]*)",
        vcard,
        re.I | re.M
    )

    if n_match:
        params, last_name, first_name = n_match.groups()

        name = f"{first_name} {last_name}".strip()

        name = decode_value(
            name,
            params
        ).strip()

        if name:
            return name

    return "بدون اسم"


def extract_phone(vcard: str) -> str | None:
    """
    استخراج أول رقم هاتف صالح من VCARD.
    """

    tel_matches = re.findall(
        r"^TEL([^:]*):([^\r\n]+)",
        vcard,
        re.I | re.M
    )

    for params, raw_phone in tel_matches:

        # إزالة المسافات والأقواس والشرطات وغيرها
        phone_clean = re.sub(
            r"[^\d+]",
            "",
            raw_phone
        )

        if len(phone_clean) < 7:
            continue

        normalized = normalize_phone_info(
            phone_clean
        )

        if normalized:
            return normalized

    return None


def parse_vcf(vcf_file: str) -> list[dict[str, str]]:
    """
    قراءة ملف VCF وتحويله إلى القائمة التي يقبلها API.
    """

    with open(
        vcf_file,
        "r",
        encoding="utf-8",
        errors="ignore"
    ) as f:
        vcf_data = f.read()

    # إصلاح folded lines في VCF
    vcf_data = re.sub(
        r"=\r?\n[ \t]",
        "",
        vcf_data
    )

    # تقسيم البطاقات
    vcards = re.split(
        r"BEGIN:VCARD",
        vcf_data,
        flags=re.I
    )

    contacts: list[dict[str, str]] = []

    # لمنع تكرار نفس الرقم
    seen_phones: set[str] = set()

    for vcard in vcards:

        if "END:VCARD" not in vcard.upper():
            continue

        name = extract_name(vcard)
        phone = extract_phone(vcard)

        if not phone:
            continue

        # منع التكرار
        if phone in seen_phones:
            continue

        seen_phones.add(phone)

        contacts.append(
            {
                "phone": phone,
                "name": name or "بدون اسم"
            }
        )

    return contacts


def chunks(
    items: list[Any],
    size: int
):
    """
    تقسيم القائمة إلى دفعات.
    """

    for i in range(0, len(items), size):
        yield items[i:i + size]


async def send_batch(
    client: httpx.AsyncClient,
    batch: list[dict[str, str]],
    batch_number: int,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:

    async with semaphore:

        try:
            response = await client.post(
                API_URL,
                headers={
                    "x-api-key": API_KEY
                },
                json={
                    "contacts": batch
                }
            )

            print(
                f"Batch #{batch_number}: "
                f"HTTP {response.status_code}"
            )

            try:
                data = response.json()
            except Exception:
                data = {
                    "raw_response": response.text
                }

            if response.is_success:
                return {
                    "success": True,
                    "batch": batch_number,
                    "data": data
                }

            return {
                "success": False,
                "batch": batch_number,
                "data": data
            }

        except Exception as e:

            return {
                "success": False,
                "batch": batch_number,
                "data": {
                    "error": str(e)
                }
            }


async def upload_contacts(
    contacts: list[dict[str, str]]
):
    """
    إرسال جهات الاتصال إلى API على دفعات.
    """

    if not contacts:
        print("لا توجد جهات اتصال صالحة للإرسال.")
        return

    batches = list(
        chunks(
            contacts,
            MAX_CONTACTS_PER_REQUEST
        )
    )

    print(
        f"إجمالي جهات الاتصال: {len(contacts)}"
    )

    print(
        f"عدد الطلبات: {len(batches)}"
    )

    semaphore = asyncio.Semaphore(
        MAX_CONCURRENT_REQUESTS
    )

    timeout = httpx.Timeout(
        connect=10.0,
        read=60.0,
        write=60.0,
        pool=60.0
    )

    async with httpx.AsyncClient(
        timeout=timeout
    ) as client:

        tasks = [
            send_batch(
                client,
                batch,
                index + 1,
                semaphore
            )
            for index, batch in enumerate(batches)
        ]

        results = await asyncio.gather(
            *tasks
        )

    total_saved = 0
    total_failed = 0

    for result in results:

        data = result.get("data", {})

        if result["success"]:

            saved = data.get("saved", 0)
            failed = data.get("failed", 0)

            total_saved += saved
            total_failed += failed

            print(
                f"Batch #{result['batch']} "
                f"saved={saved}, "
                f"failed={failed}"
            )

            errors = data.get("errors", [])

            for error in errors:
                print(
                    f"  ERROR: {error}"
                )

        else:

            total_failed += len(
                batches[result["batch"] - 1]
            )

            print(
                f"Batch #{result['batch']} FAILED:"
            )

            print(data)

    print()
    print("========== النتيجة ==========")
    print(f"Saved : {total_saved}")
    print(f"Failed: {total_failed}")


async def extract_contacts_from_vcf(
    vcf_file: str
):
    """
    قراءة VCF ثم إرسال جميع جهات الاتصال إلى API.
    """

    contacts = parse_vcf(vcf_file)

    print(
        f"تم استخراج {len(contacts)} جهة اتصال صالحة."
    )

    await upload_contacts(
        contacts
    )

    return {
        "contacts": contacts
    }


if __name__ == "__main__":

    asyncio.run(
        extract_contacts_from_vcf(
            "C:/Users/pc/Downloads/vcards.vcf"
        )
    )