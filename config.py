# -*- coding: utf-8 -*-
"""
config.py
---------
خواندن تنظیمات از فایل .env (یا متغیرهای محیطی).
"""
from __future__ import annotations

import os
from typing import List


def _load_dotenv(path: str = ".env") -> None:
    """یک .env ساده را بدون وابستگی خارجی می‌خواند."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # فقط اگر از قبل در محیط نباشد
            os.environ.setdefault(key, val)


_load_dotenv()


def _int_list(raw: str) -> List[int]:
    out = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out


# ---- تلگرام ----
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "8346392606:AAEPQ2mMMHDxOXGMJGDN1u_A6TCbYDbtSnY")
# ادمین‌های اولیه (با کاما جدا شوند). اولین نفر «سوپر‌ادمین» است.
ADMIN_IDS: List[int] = _int_list(os.environ.get("ADMIN_IDS", "7232719340"))

# ---- اکانت سایت ----
SITE_MOBILE: str = os.environ.get("SITE_MOBILE", "09334897017")
SITE_PASSWORD: str = os.environ.get("SITE_PASSWORD", "Ehsan138813")

# ---- رفتار ----
# هر چند ساعت فایل دیتابیس برای ادمین‌ها ارسال شود
BACKUP_INTERVAL_HOURS: float = float(os.environ.get("BACKUP_INTERVAL_HOURS", "2"))
# مدت اعتبار کش فیلم (ثانیه) — پیش‌فرض ۶ ساعت
MOVIE_CACHE_TTL: int = int(os.environ.get("MOVIE_CACHE_TTL", str(6 * 3600)))
# تعداد نتایج در هر صفحه‌ی جستجوی درون‌خطی
SEARCH_PAGE_SIZE: int = int(os.environ.get("SEARCH_PAGE_SIZE", "8"))

# ---- مسیرها ----
DB_PATH: str = os.environ.get("DB_PATH", "data/bot.db")
SESSION_PATH: str = os.environ.get("SESSION_PATH", "data/site_session.pkl")

# ---- پروکسی (اختیاری) ----
# اگر روی سرور/کامپیوتری هستید که تلگرام مسدود است، آدرس پروکسی را اینجا بگذارید.
# نمونه‌ها:
#   socks5://127.0.0.1:1080
#   http://127.0.0.1:8080
# روی VPS خارج از ایران این را خالی بگذارید.
TELEGRAM_PROXY: str = os.environ.get("TELEGRAM_PROXY", "").strip()

# ---- Player Server ----
# آدرس پایه‌ی Player (بدون اسلش انتهایی). برای تست محلی: http://localhost:8080
# برای تولید: https://your-domain.com  (پشت Nginx/Cloudflare با HTTPS)
PLAYER_BASE_URL: str = os.environ.get("PLAYER_BASE_URL", "http://localhost:8080").rstrip("/")
# کلید امضای توکن (یک رشته‌ی تصادفی طولانی)
PLAYER_TOKEN_SECRET: str = os.environ.get("PLAYER_TOKEN_SECRET", "change-me-to-a-random-secret-key-32chars!")
# عمر توکن (ثانیه) — پیش‌فرض ۲ ساعت
PLAYER_TOKEN_EXPIRY: int = int(os.environ.get("PLAYER_TOKEN_EXPIRY", str(2 * 3600)))
# پورت Player Server
PLAYER_PORT: int = int(os.environ.get("PLAYER_PORT", "8080"))


def token_is_placeholder() -> bool:
    return (not BOT_TOKEN) or BOT_TOKEN.startswith("PUT-YOUR")
