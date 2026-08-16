"""
services/migreat.py

دالة واحدة فقط: search_username(username) -> str
تبحث عبر مكتبة Maigret وترجع نتيجة منسّقة بصيغة HTML (parse_mode="HTML").

يستخدم قاعدة المواقع المحلية: services/maigret_data.json
(نفس مجلد هذا الملف — يتحدد المسار تلقائيًا عبر __file__، بدون أي مسار ثابت).
"""

from __future__ import annotations

import logging
from pathlib import Path

from maigret import search as maigret_search
from maigret.sites import MaigretDatabase

logger = logging.getLogger("maigret")

# مسار ملف قاعدة البيانات: نفس مجلد هذا الملف بالضبط، بغض النظر من وين يشتغل البوت
_SERVICES_DIR = Path(__file__).resolve().parent
_DATA_PATH = _SERVICES_DIR / "maigret_data.json"

# عدد المواقع المفحوصة (الأعلى ترتيبًا) — عدّلها حسب الحاجة
TOP_SITES = 300
SEARCH_TIMEOUT = 15

# يتحمّل مرة واحدة فقط عند استيراد الملف
_db = MaigretDatabase().load_from_path(str(_DATA_PATH))
SITES_DICT = _db.ranked_sites_dict(top=TOP_SITES)


async def search_username(username: str) -> str:
    """
    تبحث عن اسم مستخدم عبر Maigret وترجع نص جاهز بصيغة HTML.
    """
    username = username.strip().lstrip("@")
    if not username:
        return "❌ الرجاء إدخال اسم مستخدم صحيح."

    raw_results = await maigret_search(
        username=username,
        site_dict=SITES_DICT,
        logger=logger,
        timeout=SEARCH_TIMEOUT,
        is_parsing_enabled=False,
    )

    found = [
        (site, r) for site, r in raw_results.items() if r["status"].is_found()
    ]
    found.sort(key=lambda item: item[1].get("rank") or 999999)

    return _format_results_html(found, username)


def _format_results_html(found: list[tuple[str, dict]], username: str) -> str:
    if not found:
        return (
            "🔍 <b>نتيجة الاستعلام</b>\n\n"
            f"👤 <b>اسم المستخدم:</b> <code>{username}</code>\n\n"
            "❌ لم يتم العثور على أي حسابات."
        )

    lines = [
        "<b>🔍 نتيجة الاستعلام</b>",
        "",
        f"👤 <b>اسم المستخدم:</b> <code>{username}</code>",
        "",
        f"📊 <b>عدد الحسابات:</b> {len(found)}",
        "",
        "━━━━━━━━━━━━━━",
    ]

    for i, (site, r) in enumerate(found, 1):
        url = r.get("url_user") or ""
        lines.extend(
            [
                "",
                f"<b>{i}) {site}</b>",
                f'• 🔗 <a href="{url}">{username}</a>',
            ]
        )

    return "\n".join(lines)