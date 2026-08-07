# username_service.py
from __future__ import annotations
from html import escape
import asyncio
import re
from dataclasses import dataclass
from typing import Optional, Dict, List, Any

import httpx
from bs4 import BeautifulSoup


DEFAULT_SITES: Dict[str, Dict[str, Any]] = {
    "github": {
        "url": "https://github.com/{username}",
        "not_found": ["not found", "page not found"],
    },
    "youtube": {
        "url": "https://youtube.com/@{username}",
        "not_found": ["this page isn't available", "page isn't available"],
    },
    "instagram": {
        "url": "https://instagram.com/{username}",
        "not_found": ["sorry, this page isn't available", "page isn't available"],
    },
    "x": {
        "url": "https://x.com/{username}",
        "not_found": ["this account doesn't exist", "account doesn’t exist"],
    },
    "tiktok": {
        "url": "https://tiktok.com/@{username}",
        "not_found": ["couldn't find this account", "could not find this account"],
    }
}


@dataclass
class AccountInfo:
    platform: str
    username: str
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    text: Optional[str] = None
    status_code: Optional[int] = None
    final_url: Optional[str] = None


def normalize_username(username: str) -> str:
    username = username.strip()
    if username.startswith("@"):
        username = username[1:]
    return username.strip()


def format_accounts_html(accounts: List[AccountInfo], username: str) -> str:
    username = escape(username)

    if not accounts:
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
        f"📊 <b>عدد الحسابات:</b> {len(accounts)}",
        "",
        "━━━━━━━━━━━━━━",
    ]

    for i, account in enumerate(accounts, 1):
        platform = escape(account.platform)
        title = escape(account.title or "غير متوفر")

        lines.extend([
            "",
            f"<b>{i}) {platform.upper()}</b>",
            f'• 🔗 <a href="{account.url}">{username}</a>'
            f"• 📝 <b>العنوان:</b> {title}",
        ])

        description = escape(account.description[:180])
        if account.description:
            lines.append(
                f"• 📄 <b>الوصف:</b> {description}"
            )
        lines.append("━━━━━━━━━━━━━━")

    return "\n".join(lines)

def extract_page_data(html: str) -> tuple[Optional[str], Optional[str], str]:
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else None

    description = None
    meta = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if meta and meta.get("content"):
        description = str(meta.get("content")).strip()

    visible_text = soup.get_text(" ", strip=True)
    visible_text = re.sub(r"\s+", " ", visible_text).strip()

    return title, description, visible_text


def looks_like_not_found(
    *,
    status_code: int,
    html_lower: str,
    title: Optional[str],
    description: Optional[str],
    config: Dict[str, Any],
    final_url: str,
) -> bool:
    # أكواد واضحة لعدم وجود الصفحة
    if status_code in {404, 410}:
        return True

    # بعض المواقع ترجع 200 مع رسالة عدم وجود الحساب
    not_found_phrases = [p.lower() for p in config.get("not_found", [])]
    for phrase in not_found_phrases:
        if phrase and phrase in html_lower:
            return True

    # أحيانًا تظهر الصفحة الرئيسية أو صفحة عامة بدل ملف المستخدم
    suspicious_paths = ["/home", "/explore", "/signin", "/login", "/accounts", "/"]
    if any(p in final_url.lower() for p in suspicious_paths):
        # لا نعتبرها غير موجودة مباشرة، فقط إذا كانت الصفحة أيضًا تبدو عامة جدًا
        generic_clues = ["log in", "sign up", "create account", "join now"]
        if any(clue in html_lower for clue in generic_clues):
            return True

    # عنوان الصفحة إذا كان عامًا جدًا
    if title:
        low_title = title.lower()
        generic_titles = [
            "page not found",
            "error",
            "not found",
            "account suspended",
            "content unavailable",
        ]
        if any(t in low_title for t in generic_titles):
            return True

    # وصف الصفحة أحيانًا يكشف عدم وجود الحساب
    if description:
        low_desc = description.lower()
        if any(p in low_desc for p in not_found_phrases):
            return True

    return False


async def fetch_profile(
    client: httpx.AsyncClient,
    platform: str,
    config: Dict[str, Any],
    username: str,
) -> Optional[AccountInfo]:
    url = config["url"].format(username=username)

    try:
        response = await client.get(url)
        html = response.text
        html_lower = html.lower()

        title, description, visible_text = extract_page_data(html)

        if looks_like_not_found(
            status_code=response.status_code,
            html_lower=html_lower,
            title=title,
            description=description,
            config=config,
            final_url=str(response.url),
        ):
            return None

        # فلتر إضافي: لو الصفحة قصيرة جدًا ومشابهة لصفحة خطأ، استبعدها
        if response.status_code != 200 and len(visible_text) < 80:
            return None

        return AccountInfo(
            platform=platform,
            username=username,
            url=url,
            title=title,
            description=description,
            text=visible_text[:500] if visible_text else None,
            status_code=response.status_code,
            final_url=str(response.url),
        )

    except (httpx.TimeoutException, httpx.RequestError):
        return None
    except Exception:
        return None


async def search_username(
    username: str,
    sites: Dict[str, Dict[str, Any]] = DEFAULT_SITES,
    *,
    timeout: float = 10.0,
    concurrency: int = 5,
) -> str:
    """
    يبحث عن اسم المستخدم في عدة منصات ويرجع فقط النتائج التي تبدو موجودة فعلاً.

    الاستخدام:
        results = await search_username("@Thinking")
    """
    username = normalize_username(username)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    }

    limits = httpx.Limits(
        max_keepalive_connections=concurrency,
        max_connections=max(concurrency * 2, 10),
    )

    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        limits=limits,
    ) as client:

        async def guarded_fetch(platform: str, config: Dict[str, Any]) -> Optional[AccountInfo]:
            async with sem:
                return await fetch_profile(client, platform, config, username)

        tasks = [
            guarded_fetch(platform, config)
            for platform, config in sites.items()
        ]

        results = await asyncio.gather(*tasks)

    results = [item for item in results if item is not None]

    return format_accounts_html(results, username)
