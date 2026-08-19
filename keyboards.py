# -*- coding: utf-8 -*-
"""
keyboards.py
------------
سازنده‌ی کیبوردهای شیشه‌ای (inline) ربات.
"""
from __future__ import annotations

import math
from typing import List

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup,
                      KeyboardButton, ReplyKeyboardMarkup, WebAppInfo)

from site_client import Movie, SearchResult


# ---------------- منوی اصلی (دکمه‌های دائمی پایین صفحه) ----------------
BTN_SEARCH = "🔍 جستجوی فیلم"
BTN_FAVORITES = "❤️ علاقه‌مندی‌ها"
BTN_HISTORY = "🕒 تماشا شده‌ها"
BTN_RECENT = "📜 جستجوهای اخیر"
BTN_HELP = "📖 راهنما"
BTN_ADMIN = "🛠 پنل مدیریت"


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_SEARCH)],
        [KeyboardButton(BTN_HISTORY), KeyboardButton(BTN_FAVORITES)],
        [KeyboardButton(BTN_RECENT), KeyboardButton(BTN_HELP)],
    ]
    if is_admin:
        rows.append([KeyboardButton(BTN_ADMIN)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True,
                               input_field_placeholder="نام فیلم را بنویسید…")


def search_results_kb(results: List[SearchResult]) -> InlineKeyboardMarkup:
    """لیست نتایج جستجو در چت خصوصی — هر فیلم یک دکمه."""
    rows = []
    for r in results:
        year = f" ({r.year})" if r.year else ""
        imdb = f" ⭐{r.imdb}" if r.imdb else ""
        rows.append([InlineKeyboardButton(f"🎬 {r.title}{year}{imdb}",
                                          callback_data=f"mv:{r.movie_id}")])
    return InlineKeyboardMarkup(rows)


def movie_card_kb(movie: Movie, page: int, page_size: int,
                  is_fav: bool) -> InlineKeyboardMarkup:
    """کیبورد کارت فیلم: قسمت‌ها (صفحه‌بندی‌شده) + علاقه‌مندی + لینک صفحه."""
    rows: List[List[InlineKeyboardButton]] = []
    eps = movie.episodes
    total = len(eps)
    pages = max(1, math.ceil(total / page_size))
    page = max(0, min(page, pages - 1))
    start = page * page_size
    chunk = eps[start:start + page_size]

    for i, ep in enumerate(chunk, start=start):
        rows.append([InlineKeyboardButton(f"▶️ {ep.label}",
                                          callback_data=f"ep:{movie.movie_id}:{i}")])

    # ناوبری صفحه‌ها
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"epp:{movie.movie_id}:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(f"صفحه {page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"epp:{movie.movie_id}:{page+1}"))
    if nav:
        rows.append(nav)

    # علاقه‌مندی
    if is_fav:
        rows.append([InlineKeyboardButton("💔 حذف از علاقه‌مندی‌ها",
                                          callback_data=f"unfav:{movie.movie_id}")])
    else:
        rows.append([InlineKeyboardButton("❤️ افزودن به علاقه‌مندی‌ها",
                                          callback_data=f"fav:{movie.movie_id}")])

    return InlineKeyboardMarkup(rows)


def play_kb(https_link: str) -> InlineKeyboardMarkup:
    """کیبورد پیام پخش: لینک مستقیم به صورت دکمه‌ی URL (روش قدیمی — نگه‌داشته شده)."""
    rows = [[InlineKeyboardButton("🌐 لینک مستقیم (باز کردن/کپی)", url=https_link)]]
    return InlineKeyboardMarkup(rows)


def webapp_play_kb(player_url: str, download_url: str = "") -> InlineKeyboardMarkup:
    """کیبورد پخش با WebApp: دکمه‌ی تماشای آنلاین و دکمه‌ی دانلود.

    Args:
        player_url: آدرس صفحه‌ی Player (مثلا https://site.com/player/TOKEN)
        download_url: آدرس دانلود (مثلا https://site.com/download/TOKEN)
                       اگر خالی باشد فقط دکمه‌ی تماشا نمایش داده می‌شود.
    """
    rows = []
    rows.append([InlineKeyboardButton(
        "▶️ تماشای آنلاین",
        web_app=WebAppInfo(url=player_url),
    )])
    if download_url:
        rows.append([InlineKeyboardButton(
            "⬇️ دانلود فیلم",
            url=download_url,
        )])
    return InlineKeyboardMarkup(rows)


def join_kb(channels, check_cb: str = "checkjoin") -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        link = ch["invite_link"] or (f"https://t.me/{ch['chat_id'].lstrip('@')}"
                                     if str(ch["chat_id"]).startswith("@") else None)
        title = ch["title"] or ch["chat_id"]
        if link:
            rows.append([InlineKeyboardButton(f"📢 {title}", url=link)])
    rows.append([InlineKeyboardButton("✅ عضو شدم", callback_data=check_cb)])
    return InlineKeyboardMarkup(rows)


def favorites_kb(favs) -> InlineKeyboardMarkup:
    rows = []
    for f in favs:
        rows.append([InlineKeyboardButton(f"🎬 {f['title']}", callback_data=f"mv:{f['movie_id']}")])
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([])


def history_kb(items) -> InlineKeyboardMarkup:
    """تاریخچه‌ی تماشا: هر مورد دکمه‌ای برای باز کردن دوباره‌ی فیلم."""
    rows = []
    for it in items:
        ep = f" — {it['episode']}" if it["episode"] else ""
        rows.append([InlineKeyboardButton(f"🎬 {it['title']}{ep}",
                                          callback_data=f"mv:{it['movie_id']}")])
    if rows:
        rows.append([InlineKeyboardButton("🗑 پاک کردن تاریخچه", callback_data="clearwatch")])
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([])


def recent_searches_kb(queries) -> InlineKeyboardMarkup:
    """جستجوهای اخیر: هر مورد دکمه‌ای برای جستجوی دوباره."""
    rows = []
    for i, q in enumerate(queries):
        rows.append([InlineKeyboardButton(f"🔍 {q}", callback_data=f"rs:{i}")])
    if rows:
        rows.append([InlineKeyboardButton("🗑 پاک کردن تاریخچه جستجو", callback_data="clearsearch")])
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([])


# ---------------- پنل مدیریت ----------------
def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار ربات", callback_data="adm:stats")],
        [InlineKeyboardButton("📢 کانال‌های عضویت اجباری", callback_data="adm:channels")],
        [InlineKeyboardButton("📣 پیام همگانی", callback_data="adm:broadcast")],
        [InlineKeyboardButton("📤 ارسال فایل دیتابیس", callback_data="adm:senddb"),
         InlineKeyboardButton("♻️ بازیابی دیتابیس", callback_data="adm:restoredb")],
        [InlineKeyboardButton("👤 مدیریت ادمین‌ها", callback_data="adm:admins")],
        [InlineKeyboardButton("🐞 لاگ خطاها", callback_data="adm:errors")],
        [InlineKeyboardButton("❌ بستن", callback_data="adm:close")],
    ])


def channels_kb(channels) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        title = ch["title"] or ch["chat_id"]
        rows.append([
            InlineKeyboardButton(f"📢 {title}", callback_data="noop"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"adm:delch:{ch['chat_id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ افزودن کانال", callback_data="adm:addch")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm:home")])
    return InlineKeyboardMarkup(rows)


def admins_kb(admin_ids, super_admin: int) -> InlineKeyboardMarkup:
    rows = []
    for aid in admin_ids:
        label = f"👑 {aid}" + (" (سوپر‌ادمین)" if aid == super_admin else "")
        btns = [InlineKeyboardButton(label, callback_data="noop")]
        if aid != super_admin:
            btns.append(InlineKeyboardButton("🗑", callback_data=f"adm:deladmin:{aid}"))
        rows.append(btns)
    rows.append([InlineKeyboardButton("➕ افزودن ادمین", callback_data="adm:addadmin")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm:home")])
    return InlineKeyboardMarkup(rows)


def back_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="adm:home")]])
