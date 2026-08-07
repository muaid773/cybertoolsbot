from datetime import datetime

import httpx

from config import VIRUSTOTAL_API_KEY
import re


def escape_md(text: str | None) -> str:
    if text is None:
        return "غير متوفر"

    text = str(text)

    return re.sub(
        r'([_*\[\]()~`>#+\-=|{}.!\\])',
        r'\\\1',
        text
    )
def ts(ts):
    if not ts:
        return "غير معروف"

    return datetime.utcfromtimestamp(
        ts
    ).strftime("%Y-%m-%d")


def build_domain_report(data: dict) -> str:

    stats = data["stats"]

    malicious = stats["malicious"]
    suspicious = stats["suspicious"]

    if malicious:
        level = "🔴 مرتفع"
        advice = "تم رصد الدومين بواسطة عدة محركات حماية، لذلك يُنصح بتجنب زيارته."
    elif suspicious:
        level = "🟠 متوسط"
        advice = "ظهرت مؤشرات مريبة لدى بعض المحركات، لذا يُفضل الحذر قبل استخدام الدومين."
    else:
        level = "🟢 منخفض"
        advice = "لم يتم اكتشاف مؤشرات ضارة حالياً."

    text = f"""
*🌐 تقرير تحليل الدومين*

━━━━━━━━━━━━━━

*الدومين*

`{escape_md(data['domain'])}`

*🚨 مستوى الخطورة*

{level}

*⭐ السمعة*

`{escape_md(data['reputation'])}`

━━━━━━━━━━━━━━

*📊 نتائج الفحص*

🔴 خبيث : *{stats['malicious']}*

🟠 مشبوه : *{stats['suspicious']}*

🟢 آمن : *{stats['harmless']}*

⚪ غير مكتشف : *{stats['undetected']}*

━━━━━━━━━━━━━━

*🏢 معلومات الدومين*

🌍 الدولة : {escape_md(data['country'])}

🏛 المسجل : {escape_md(data['registrar'])}

📅 تاريخ الإنشاء : {escape_md(ts(data['creation_date']))}

🔄 آخر تعديل : {escape_md(ts(data['last_modification_date']))}

━━━━━━━━━━━━━━

*🏷 التصنيفات*
"""

    if data["categories"]:
        for engine, category in data["categories"].items():
            text += f"\n• {escape_md(engine)} : {escape_md(category)}"
    else:
        text += "\nغير متوفر"

    text += "\n\n━━━━━━━━━━━━━━\n\n*🏷 الوسوم*\n"

    if data["tags"]:
        for tag in data["tags"]:
            text += f"\n• {escape_md(tag)}"
    else:
        text += "\nلا توجد"

    text += f"""

━━━━━━━━━━━━━━

*📝 التوصية الأمنية*

{escape_md(advice)}
"""

    return text.strip()

def build_vt_markdown(data: dict) -> str:
    stats = data.get("stats", {})

    malicious = stats.get("malicious", 0)
    suspicious = stats.get("suspicious", 0)
    harmless = stats.get("harmless", 0)
    undetected = stats.get("undetected", 0)

    # التقييم النهائي
    if malicious > 0:
        icon = "🔴"
        verdict = "خطر"
        summary = (
            f"تم اكتشاف الرابط بواسطة *{malicious}* محرك حماية "
            "كموقع ضار، لذلك يُنصح بعدم فتحه أو إدخال أي معلومات شخصية."
        )

    elif suspicious > 0:
        icon = "🟠"
        verdict = "مشبوه"
        summary = (
            "لم يتم تصنيفه كخبيث بشكل قاطع، "
            "لكن بعض محركات الحماية أبدت سلوكًا مريبًا."
        )

    else:
        icon = "🟢"
        verdict = "آمن غالبًا"
        summary = (
            "لم يتم اكتشاف أي نشاط ضار بواسطة محركات VirusTotal، "
            "ولكن هذا لا يضمن الأمان بنسبة 100٪."
        )

    categories = data.get("categories", {})

    if categories:
        cat_text = "\n".join(
            f"• {escape_md(engine)} : {escape_md(category)}"
            for engine, category in categories.items()
        )
    else:
        cat_text = "غير متوفر"

    tags = data.get("tags", [])

    tag_text = (
        "، ".join(escape_md(tag) for tag in tags)
        if tags else
        "لا توجد"
    )

    report = f"""
*🛡 تقرير تحليل الرابط*

━━━━━━━━━━━━━━

{icon} *التقييم النهائي:* *{escape_md(verdict)}*

_{escape_md(summary)}_

*🌐 الرابط*
`{escape_md(data.get("url"))}`

*↪️ الرابط النهائي*
`{escape_md(data.get("final_url") or data.get("url"))}`

*📄 عنوان الصفحة*
{escape_md(data.get("title"))}

*📂 التصنيف*
{escape_md(data.get("web_category"))}

*📡 كود الاستجابة*
`{escape_md(data.get("http_code"))}`

━━━━━━━━━━━━━━

*📊 نتائج محركات الحماية*

🔴 خبيث: *{malicious}*

🟠 مشبوه: *{suspicious}*

🟢 آمن: *{harmless}*

⚪ غير مكتشف: *{undetected}*

━━━━━━━━━━━━━━

*🏷 تصنيفات الموقع*

{cat_text}

━━━━━━━━━━━━━━

*🏷 الوسوم*

{tag_text}

━━━━━━━━━━━━━━

*📌 الخلاصة*

{icon} *{escape_md(summary)}*
"""

    return report.strip()
async def analyze_url(url: str) -> dict:
    headers = {"x-apikey": VIRUSTOTAL_API_KEY}

    async with httpx.AsyncClient(timeout=30) as client:

        # إرسال الرابط
        r = await client.post(
            "https://www.virustotal.com/api/v3/urls",
            headers=headers,
            data={"url": url},
        )
        r.raise_for_status()
        import pprint
        pprint.pprint(r.json())


        analysis_id = r.json()["data"]["id"]

        # انتظار انتهاء التحليل
        while True:
            r = await client.get(
                f"https://www.virustotal.com/api/v3/analyses/{analysis_id}",
                headers=headers,
            )
            r.raise_for_status()

            data = r.json()["data"]["attributes"]
            # import pprint
            # pprint.pprint(data["status"])

            if data["status"] == "completed":
                break

        stats = data.get("stats", {})

        return build_vt_markdown ({
            "url": data.get("url"),
            "final_url": data.get("final_url"),
            "status": data.get("status"),
            "title": data.get("title"),
            "http_code": data.get("response_code"),
            "categories": data.get("categories", {}),
            "web_category": data.get("web_category"),
            "tags": data.get("tags", []),
            "brand": data.get("targeted_brand", {}),
            "stats": {
                "malicious": stats.get("malicious", 0),
                "suspicious": stats.get("suspicious", 0),
                "harmless": stats.get("harmless", 0),
                "undetected": stats.get("undetected", 0),
            },
        })


async def analyze_domain(domain: str) -> dict:
    headers = {
        "x-apikey": VIRUSTOTAL_API_KEY
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"https://www.virustotal.com/api/v3/domains/{domain}",
            headers=headers
        )

        if response.status_code == 400:
            return {
                "ok": False,
                "message": "اسم النطاق غير صالح."
            }

        if response.status_code == 404:
            return {
                "ok": False,
                "message": "لم يتم العثور على معلومات لهذا النطاق."
            }

        response.raise_for_status()
        
        attr = response.json()["data"]["attributes"]

        stats = attr.get("last_analysis_stats", {})

        return build_domain_report({
            "domain": domain,
            "reputation": attr.get("reputation"),
            "categories": attr.get("categories", {}),
            "creation_date": attr.get("creation_date"),
            "last_modification_date": attr.get("last_modification_date"),
            "registrar": attr.get("registrar"),
            "country": attr.get("country"),
            "tags": attr.get("tags", []),
            "stats": {
                "malicious": stats.get("malicious", 0),
                "suspicious": stats.get("suspicious", 0),
                "harmless": stats.get("harmless", 0),
                "undetected": stats.get("undetected", 0),
            },
        })