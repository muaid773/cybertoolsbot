import re
import base64
import quopri
import asyncio
from typing import Any

import httpx
import phonenumbers
from phonenumbers import PhoneNumberFormat


# ============================================================
# إعدادات API
# ============================================================

API_URL = "https://cybertoolsbot.onrender.com/contacts"

API_KEY = "123qwessasnid32dwq3-3e3e8u382-=12e93"

# يجب أن يطابق السيرفر
MAX_CONTACTS_PER_REQUEST = 200

# عدد الطلبات المتزامنة
MAX_CONCURRENT_REQUESTS = 5


# ============================================================
# Phone
# ============================================================

PHONE_RE = re.compile(
    r"^\+[0-9]{6,15}$"
)


def normalize_phone(phone: str | None) -> str | None:
    """
    تحويل الرقم إلى E.164 والتأكد أنه رقم يمني صالح.

    أمثلة:

        0771234567
        771234567
        +967771234567

    إذا كان صالحًا:
        +967771234567

    وإلا:
        None
    """

    if not phone:
        return None

    phone = phone.strip()

    if not phone:
        return None

    try:
        parsed = phonenumbers.parse(
            phone,
            "YE",
        )

    except phonenumbers.NumberParseException:
        return None

    # يجب أن يكون الرقم يمنيًا
    if phonenumbers.region_code_for_number(parsed) != "YE":
        return None

    # يجب أن يكون صالحًا
    if not phonenumbers.is_valid_number(parsed):
        return None

    normalized = phonenumbers.format_number(
        parsed,
        PhoneNumberFormat.E164,
    )

    if not PHONE_RE.fullmatch(normalized):
        return None

    return normalized


# ============================================================
# VCF decoding
# ============================================================

def decode_value(
    value: str,
    params: str,
) -> str:
    """
    فك قيمة من VCF.

    يدعم:
    - BASE64
    - QUOTED-PRINTABLE
    - CHARSET
    """

    value = value.strip()
    params_upper = params.upper()

    # --------------------------------------------------------
    # BASE64
    # --------------------------------------------------------

    if (
        "ENCODING=B" in params_upper
        or "ENCODING=BASE64" in params_upper
    ):
        try:
            decoded = base64.b64decode(
                value
            )

            charset_match = re.search(
                r"CHARSET=([^;:]+)",
                params,
                re.I,
            )

            charset = (
                charset_match.group(1).strip()
                if charset_match
                else "utf-8"
            )

            return decoded.decode(
                charset,
                errors="ignore",
            )

        except Exception:
            pass

    # --------------------------------------------------------
    # QUOTED PRINTABLE
    # --------------------------------------------------------

    if (
        "ENCODING=QUOTED-PRINTABLE" in params_upper
        or "QUOTED-PRINTABLE" in params_upper
    ):
        try:
            decoded = quopri.decodestring(
                value.encode("utf-8")
            )

            charset_match = re.search(
                r"CHARSET=([^;:]+)",
                params,
                re.I,
            )

            charset = (
                charset_match.group(1).strip()
                if charset_match
                else "utf-8"
            )

            return decoded.decode(
                charset,
                errors="ignore",
            )

        except Exception:
            pass

    # --------------------------------------------------------
    # CHARSET
    # --------------------------------------------------------

    charset_match = re.search(
        r"CHARSET=([^;:]+)",
        params,
        re.I,
    )

    if charset_match:
        charset = charset_match.group(1).strip()

        try:
            return value.encode(
                "latin1"
            ).decode(
                charset,
                errors="ignore",
            )

        except Exception:
            pass

    return value


# ============================================================
# Name
# ============================================================

def clean_name(name: str) -> str:
    """
    تنظيف الاسم.
    """

    name = " ".join(
        name.split()
    )

    if not name:
        return "بدون اسم"

    return name[:255]


def extract_name(
    vcard: str,
) -> str:
    """
    استخراج اسم جهة الاتصال.

    الأولوية:
        FN
        ثم N
    """

    # --------------------------------------------------------
    # FN
    # --------------------------------------------------------

    fn_match = re.search(
        r"^FN([^:]*):(.*)$",
        vcard,
        re.I | re.M,
    )

    if fn_match:

        params, raw_name = fn_match.groups()

        name = decode_value(
            raw_name,
            params,
        )

        name = clean_name(name)

        if name != "بدون اسم":
            return name

    # --------------------------------------------------------
    # N
    # --------------------------------------------------------

    n_match = re.search(
        r"^N([^:]*):([^;]*);([^;]*)",
        vcard,
        re.I | re.M,
    )

    if n_match:

        params, last_name, first_name = (
            n_match.groups()
        )

        first_name = decode_value(
            first_name,
            params,
        )

        last_name = decode_value(
            last_name,
            params,
        )

        name = clean_name(
            f"{first_name} {last_name}"
        )

        if name != "بدون اسم":
            return name

    return "بدون اسم"


# ============================================================
# Phone
# ============================================================

def extract_phone(
    vcard: str,
) -> str | None:
    """
    استخراج أول رقم يمني صالح من VCARD.
    """

    tel_matches = re.findall(
        r"^TEL([^:]*):([^\r\n]+)",
        vcard,
        re.I | re.M,
    )

    for params, raw_phone in tel_matches:

        # إزالة:
        # spaces
        # -
        # ()
        # .
        # إلخ
        phone_clean = re.sub(
            r"[^\d+]",
            "",
            raw_phone,
        )

        if len(phone_clean) < 7:
            continue

        normalized = normalize_phone(
            phone_clean
        )

        if normalized:
            return normalized

    return None


# ============================================================
# VCF parser
# ============================================================

def parse_vcf(
    vcf_file: str,
) -> list[dict[str, str]]:
    """
    قراءة ملف VCF وتحويله إلى:

    [
        {
            "phone": "+967771234567",
            "name": "محمد"
        }
    ]
    """

    with open(
        vcf_file,
        "r",
        encoding="utf-8",
        errors="ignore",
    ) as file:

        vcf_data = file.read()

    # --------------------------------------------------------
    # إصلاح folded lines
    # --------------------------------------------------------

    vcf_data = re.sub(
        r"\r?\n[ \t]",
        "",
        vcf_data,
    )

    # --------------------------------------------------------
    # تقسيم VCARD
    # --------------------------------------------------------

    vcards = re.split(
        r"BEGIN:VCARD",
        vcf_data,
        flags=re.I,
    )

    contacts: list[dict[str, str]] = []

    # منع تكرار الرقم
    seen_phones: set[str] = set()

    for vcard in vcards:

        if "END:VCARD" not in vcard.upper():
            continue

        phone = extract_phone(vcard)

        if not phone:
            continue

        # نفس الرقم موجود في أكثر من بطاقة
        if phone in seen_phones:
            continue

        name = extract_name(vcard)

        seen_phones.add(phone)

        contacts.append(
            {
                "phone": phone,
                "name": name,
            }
        )

    return contacts


# ============================================================
# Chunks
# ============================================================

def chunks(
    items: list[Any],
    size: int,
):
    """
    تقسيم القائمة إلى دفعات.
    """

    for index in range(
        0,
        len(items),
        size,
    ):
        yield items[
            index:index + size
        ]


# ============================================================
# Send batch
# ============================================================

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
                    "x-api-key": API_KEY,
                },
                json={
                    "contacts": batch,
                },
            )

            print(
                f"Batch #{batch_number} "
                f"HTTP {response.status_code}"
            )

            try:
                data = response.json()

            except ValueError:

                data = {
                    "error": response.text,
                }

            if response.is_success:

                return {
                    "success": True,
                    "batch": batch_number,
                    "data": data,
                }

            return {
                "success": False,
                "batch": batch_number,
                "data": data,
            }

        except httpx.RequestError as exc:

            return {
                "success": False,
                "batch": batch_number,
                "data": {
                    "error": (
                        f"فشل الاتصال بالخادم: {exc}"
                    )
                },
            }

        except Exception as exc:

            return {
                "success": False,
                "batch": batch_number,
                "data": {
                    "error": str(exc),
                },
            }


# ============================================================
# Upload
# ============================================================

async def upload_contacts(
    contacts: list[dict[str, str]],
):
    """
    إرسال جهات الاتصال إلى API على دفعات.
    """

    if not contacts:

        print(
            "لا توجد جهات اتصال صالحة للإرسال."
        )

        return

    batches = list(
        chunks(
            contacts,
            MAX_CONTACTS_PER_REQUEST,
        )
    )

    print(
        f"إجمالي جهات الاتصال: "
        f"{len(contacts)}"
    )

    print(
        f"عدد الطلبات: "
        f"{len(batches)}"
    )

    semaphore = asyncio.Semaphore(
        MAX_CONCURRENT_REQUESTS
    )

    timeout = httpx.Timeout(
        connect=10.0,
        read=60.0,
        write=60.0,
        pool=60.0,
    )

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(
            max_connections=10,
            max_keepalive_connections=5,
        ),
    ) as client:

        tasks = [
            send_batch(
                client=client,
                batch=batch,
                batch_number=index + 1,
                semaphore=semaphore,
            )
            for index, batch in enumerate(
                batches
            )
        ]

        results = await asyncio.gather(
            *tasks
        )

    total_saved = 0
    total_failed = 0

    # --------------------------------------------------------
    # النتائج
    # --------------------------------------------------------

    for result in results:

        batch_number = result["batch"]
        data = result.get("data", {})

        if result["success"]:

            saved = int(
                data.get("saved", 0)
            )

            failed = int(
                data.get("failed", 0)
            )

            total_saved += saved
            total_failed += failed

            print(
                f"Batch #{batch_number}: "
                f"saved={saved}, "
                f"failed={failed}"
            )

            for error in data.get(
                "errors",
                [],
            ):

                print(
                    f"  ERROR: {error}"
                )

        else:

            failed = len(
                batches[
                    batch_number - 1
                ]
            )

            total_failed += failed

            print(
                f"Batch #{batch_number} FAILED"
            )

            print(
                data
            )

    print()
    print(
        "========== النتيجة =========="
    )
    print(
        f"Saved : {total_saved}"
    )
    print(
        f"Failed: {total_failed}"
    )

    return {
        "saved": total_saved,
        "failed": total_failed,
    }


# ============================================================
# Main
# ============================================================

async def extract_contacts_from_vcf(
    vcf_file: str,
):
    """
    قراءة VCF ثم رفع جهات الاتصال.
    """

    contacts = parse_vcf(
        vcf_file
    )

    print(
        f"تم استخراج "
        f"{len(contacts)} "
        f"جهة اتصال صالحة."
    )

    result = await upload_contacts(
        contacts
    )

    return {
        "contacts": contacts,
        "result": result,
    }


if __name__ == "__main__":

    asyncio.run(
        extract_contacts_from_vcf(
            "C:/Users/pc/Downloads/vcards.vcf"
        )
    )