# -*- coding: utf-8 -*-
"""
site_client.py
--------------
کلاینت سایت tdmmo.xyz (فیلمجو).

مسئولیت‌ها:
  • لاگین با اکانت کاربر + حل خودکار کپچا (با retry) و نگه‌داری سشن پایدار روی دیسک
  • تشخیص انقضای سشن و لاگین مجدد خودکار
  • جستجوی فیلم/سریال
  • خواندن اطلاعات صفحه‌ی فیلم (عنوان، ژانر، کشور، امتیاز، پوستر، خلاصه) و لیست قسمت‌ها
  • تولید لینک تازه‌ی پخش (vlc://) که امضا و انقضا دارد

نکته‌ی مهم معماری:
  لینک /play?a=p بدون سشنِ لاگین‌شده به صفحه‌ی ورود ریدایرکت می‌شود؛ پس کاربر
  نمی‌تواند خودش آن را باز کند. بنابراین ربات با سشن خودش لینک نهاییِ vlc:// (که
  حاوی expire+hash است) را تولید و به کاربر می‌دهد. این لینک تا زمان انقضا مستقیماً
  در VLC قابل پخش است.
"""
from __future__ import annotations

import html as _html
import logging
import os
import pickle
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

from captcha_solver import get_solver

log = logging.getLogger("site")

BASE = "https://tdmmo.xyz"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# اگر پاسخ صفحه‌ی لاگین‌شده باشد، حجمش خیلی بیشتر از صفحه‌ی «ورود» (~4KB) است.
_LOGGED_IN_MIN_LEN = 12000


@dataclass
class Episode:
    part: str          # مثلا «قسمت ۱»
    quality: str       # مثلا «480»
    size: str          # مثلا «533 مگابایت»
    play_url: str      # لینک /play?a=p&i=...&f=... (باید resolve شود)
    filename: str      # نام فایل

    @property
    def label(self) -> str:
        q = f" | {self.quality}p" if self.quality else ""
        s = f" | {self.size}" if self.size else ""
        return f"{self.part}{q}{s}".strip()


@dataclass
class Movie:
    movie_id: str
    title: str = ""
    original_title: str = ""   # نام اصلی (لاتین)
    year: str = ""
    imdb: str = ""
    genre: str = ""
    country: str = ""
    age: str = ""              # رده سنی
    director: str = ""
    stars: str = ""
    poster: str = ""
    plot: str = ""             # فقط خلاصه‌ی داستان
    episodes: List[Episode] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"{BASE}/movie?m={self.movie_id}"

    @property
    def is_series(self) -> bool:
        # اگر بیش از یک «قسمت» متمایز داشته باشد سریال است
        parts = {e.part for e in self.episodes}
        return len([p for p in parts if "قسمت" in p]) > 1


@dataclass
class SearchResult:
    movie_id: str
    title: str
    year: str = ""
    imdb: str = ""
    poster: str = ""


class LoginError(Exception):
    pass


class SiteClient:
    def __init__(self, mobile: str, password: str,
                 session_path: str = "data/site_session.pkl"):
        self.mobile = mobile
        self.password = password
        self.session_path = session_path
        self._lock = threading.RLock()       # هم‌زمانی امن بین هندلرهای ربات
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})
        self._solver = get_solver()
        self._load_session()

    # ---------------- مدیریت سشن ----------------
    def _load_session(self) -> None:
        try:
            if os.path.exists(self.session_path):
                with open(self.session_path, "rb") as f:
                    self.s.cookies = pickle.load(f)
                log.info("سشن قبلی سایت بارگذاری شد")
        except Exception as e:
            log.warning("بارگذاری سشن ناموفق بود: %s", e)

    def _save_session(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.session_path) or ".", exist_ok=True)
            with open(self.session_path, "wb") as f:
                pickle.dump(self.s.cookies, f)
        except Exception as e:
            log.warning("ذخیره‌ی سشن ناموفق بود: %s", e)

    def _get(self, path: str, **kw) -> requests.Response:
        kw.setdefault("timeout", 45)
        kw.setdefault("headers", {}).setdefault("Referer", BASE + "/")
        return self.s.get(BASE + path if path.startswith("/") else path, **kw)

    # ---------------- لاگین ----------------
    def is_logged_in(self) -> bool:
        """با گرفتن صفحه‌ی اصلی بررسی می‌کند که سشن معتبر است یا نه."""
        try:
            r = self._get("/", allow_redirects=True)
            # صفحه‌ی «ورود» کوچک است؛ صفحه‌ی داشبورد بزرگ.
            if len(r.text) >= _LOGGED_IN_MIN_LEN and "form-login" not in r.text:
                return True
            return False
        except requests.RequestException as e:
            log.warning("بررسی وضعیت لاگین ناموفق: %s", e)
            return False

    def login(self, max_attempts: int = 6) -> bool:
        """لاگین با حل خودکار کپچا و چند بار تلاش (کپچای تازه در هر تلاش)."""
        with self._lock:
            for attempt in range(1, max_attempts + 1):
                try:
                    # سشن تازه برای گرفتن PHPSESSID و کپچای گره‌خورده به آن
                    self.s.get(BASE + "/", timeout=45)
                    self.s.get(BASE + "/form-login", headers={"Referer": BASE + "/"}, timeout=45)
                    rc = self.s.get(BASE + "/captcha", headers={"Referer": BASE + "/"}, timeout=45)
                    expr, answer = self._solver.solve(rc.content)
                    if answer is None:
                        log.warning("تلاش %d: کپچا خوانده نشد، تلاش مجدد", attempt)
                        time.sleep(1.0)
                        continue
                    log.info("تلاش %d: کپچا = %s = %s", attempt, expr, answer)
                    r = self.s.post(
                        BASE + "/login",
                        data={"mobile": self.mobile, "password": self.password,
                              "captcha": str(answer), "submit": ""},
                        headers={"Referer": BASE + "/"}, timeout=45,
                    )
                    if len(r.text) >= _LOGGED_IN_MIN_LEN and "form-login" not in r.text:
                        self._save_session()
                        log.info("✅ لاگین موفق بود")
                        return True
                    # اگر کوتاه بود یعنی رمز/موبایل غلط یا کپچا رد شد
                    if "کپچا" in r.text or "امنیتی" in r.text or "اشتباه" in r.text:
                        log.warning("تلاش %d: کپچا/اطلاعات رد شد", attempt)
                    else:
                        log.warning("تلاش %d: پاسخ نامعتبر (len=%d)", attempt, len(r.text))
                    time.sleep(1.2)
                except requests.RequestException as e:
                    log.warning("تلاش %d خطای شبکه: %s", attempt, e)
                    time.sleep(2.0 * attempt)
            return False

    def ensure_login(self) -> bool:
        """اگر لاگین نیست، لاگین می‌کند. قبل از هر عملیات نیازمند احراز هویت صدا زده می‌شود."""
        with self._lock:
            if self.is_logged_in():
                return True
            log.info("سشن منقضی شده؛ در حال لاگین مجدد…")
            return self.login()

    # ---------------- جستجو ----------------
    def search(self, query: str, page: int = 1) -> List[SearchResult]:
        if not self.ensure_login():
            raise LoginError("لاگین به سایت ممکن نشد")
        q = urllib.parse.quote(query.strip())
        r = self._get(f"/search?q={q}&p={page}")
        return self._parse_search(r.text)

    @staticmethod
    def _parse_search(text: str) -> List[SearchResult]:
        results: List[SearchResult] = []
        # هر آیتم: <div class="movie_item"><a href="movie?m=ID"> ... spans ...
        for block in re.findall(r'<div class="movie_item">(.*?)</a>\s*</div>', text, re.S):
            mid = re.search(r'movie\?m=(\d+)', block)
            if not mid:
                continue
            title = re.search(r'movie_item_title">([^<]*)<', block)
            year = re.search(r'movie_item_year">([^<]*)<', block)
            imdb = re.search(r'movie_item_imdb">([^<]*)<', block)
            poster = re.search(r'<img src="([^"]+)"', block)
            results.append(SearchResult(
                movie_id=mid.group(1),
                title=_clean(title.group(1)) if title else "",
                year=_clean(year.group(1)) if year else "",
                imdb=_clean(imdb.group(1)) if imdb else "",
                poster=poster.group(1) if poster else "",
            ))
        # حذف تکراری‌ها با حفظ ترتیب
        seen = set()
        uniq = []
        for r in results:
            if r.movie_id in seen:
                continue
            seen.add(r.movie_id)
            uniq.append(r)
        return uniq

    def search_total_pages(self, text: str) -> int:
        m = re.search(r'کل صفحات جستجوی[^:]*:\s*(\d+)', text)
        return int(m.group(1)) if m else 1

    # ---------------- صفحه‌ی فیلم ----------------
    def movie(self, movie_id: str) -> Movie:
        if not self.ensure_login():
            raise LoginError("لاگین به سایت ممکن نشد")
        r = self._get(f"/movie?m={movie_id}")
        return self._parse_movie(movie_id, r.text)

    @staticmethod
    def _parse_movie(movie_id: str, text: str) -> Movie:
        m = Movie(movie_id=movie_id)
        # عنوان و متادیتا داخل DetitlesTitleBox
        box = re.search(r'DetitlesTitleBox">(.*?)</div>\s*</div>', text, re.S)
        block = box.group(1) if box else text
        t = re.search(r'DetilesTitlesLarg">([^<]+)<', block)
        if t:
            m.title = _clean(t.group(1))
        for line in re.findall(r'DetilesTitlesSmall">([^<]+)<', block):
            line = _clean(line)
            if "imdb" in line.lower():
                m.imdb = line.replace(":", "").replace("imdb", "").strip()
            elif line.startswith("ژانر"):
                m.genre = line.split(":", 1)[-1].strip()
            elif line.startswith("کشور"):
                m.country = line.split(":", 1)[-1].strip()
            elif line.startswith("سال"):
                m.year = line.split(":", 1)[-1].strip()
        # پوستر
        pm = re.search(r'(https?://[^\s"\'<>]+/pic-list/[^\s"\'<>]+\.jpg)', text)
        if pm:
            m.poster = pm.group(1)
        # بلاک توضیحات (DetitlesDes): شامل نام اصلی/محصول/کارگردان/ستارگان/خلاصه
        des = re.search(r'DetitlesDes[^"]*"[^>]*>(.*?)</div>', text, re.S)
        if des:
            # هر تگ را به خط تبدیل کن تا فیلدها جدا شوند
            raw = re.sub(r'<[^>]+>', "\n", des.group(1))
            lines = [_clean(x) for x in raw.split("\n")]
            lines = [x for x in lines if x]
            plot_lines: List[str] = []
            capture_plot = False
            for ln in lines:
                low = ln.replace(" ", "")
                if ln.startswith("نام اصلی"):
                    m.original_title = ln.split(":", 1)[-1].strip()
                elif ln.startswith("ژانر") and not m.genre:
                    m.genre = ln.split(":", 1)[-1].strip()
                elif ln.startswith("محصول"):
                    val = ln.split(":", 1)[-1].strip()
                    ym = re.search(r'(\d{4})', val)
                    if ym and not m.year:
                        m.year = ym.group(1)
                    # کشور بعد از سال
                    country = re.sub(r'\d{4}', '', val).strip()
                    if country and not m.country:
                        m.country = country
                elif "ردهسنی" in low or ln.startswith("رده سنی"):
                    m.age = ln.split(":", 1)[-1].strip()
                elif ln.startswith("کارگردان"):
                    m.director = ln.split(":", 1)[-1].strip()
                elif ln.startswith("ستارگان"):
                    m.stars = ln.split(":", 1)[-1].strip()
                elif "خلاصه" in ln and ":" in ln and len(ln) < 25:
                    capture_plot = True  # خطوط بعدی خلاصه‌اند
                elif capture_plot:
                    # خلاصه تا رسیدن به نام لاتین انتهایی
                    if re.match(r'^[A-Za-z0-9 /,\.\-]+$', ln):
                        continue
                    plot_lines.append(ln)
            m.plot = " ".join(plot_lines).strip()
        # قسمت‌ها: لینک‌های play?a=p با اطلاعات حجم/قسمت/کیفیت
        m.episodes = SiteClient._parse_episodes(text)
        return m

    @staticmethod
    def _parse_episodes(text: str) -> List[Episode]:
        eps: List[Episode] = []
        # بخش پخش آنلاین (a=p). هر <a href="...play?a=p..."> ... spans
        pattern = re.compile(
            r'href="(https://tdmmo\.xyz/play\?a=p[^"]+)"\s*>(.*?)</a>', re.S)
        for href, inner in pattern.findall(text):
            href = href.replace("&amp;", "&")
            fn = re.search(r'[?&]f=([^&"]+)', href)
            filename = urllib.parse.unquote(fn.group(1)) if fn else ""
            # داخل span ها: حجم و «قسمت X - کیفیت : YYY»
            spans = re.findall(r'>([^<]+)<', inner)
            spans = [_clean(s) for s in spans if _clean(s)]
            size = ""
            part = ""
            quality = ""
            for s in spans:
                if "مگابایت" in s or "گیگابایت" in s:
                    size = s
                elif "قسمت" in s or "کیفیت" in s:
                    pm = re.search(r'(قسمت\s*\d+)', s)
                    qm = re.search(r'کیفیت\s*:\s*(\d+)', s)
                    if pm:
                        part = pm.group(1)
                    if qm:
                        quality = qm.group(1)
            if not part:
                # فیلم تک‌قسمتی
                part = "پخش"
            eps.append(Episode(part=part, quality=quality, size=size,
                               play_url=href, filename=filename))
        return eps

    # ---------------- تولید لینک پخش ----------------
    def resolve_play(self, play_url: str, movie_id: str = "") -> Optional[str]:
        """لینک /play?a=p را به لینک تازه‌ی vlc:// (امضاشده) تبدیل می‌کند."""
        if not self.ensure_login():
            raise LoginError("لاگین به سایت ممکن نشد")
        with self._lock:
            ref = f"{BASE}/movie?m={movie_id}" if movie_id else BASE + "/"
            r = self.s.get(play_url, headers={"Referer": ref}, timeout=45,
                           allow_redirects=False)
            loc = r.headers.get("Location", "")
            if loc.startswith("vlc://"):
                return loc
            # اگر به login ریدایرکت شد یعنی سشن پرید → یک بار دیگر
            if "login" in loc:
                if self.login():
                    r = self.s.get(play_url, headers={"Referer": ref}, timeout=45,
                                   allow_redirects=False)
                    loc = r.headers.get("Location", "")
                    if loc.startswith("vlc://"):
                        return loc
            return None

    @staticmethod
    def vlc_to_http(vlc_url: str) -> str:
        """لینک vlc:// را به لینک مستقیم http:// تبدیل می‌کند.
        روی موبایل فقط http کار می‌کند (سرور CDN گواهی https معتبر ندارد و
        دکمه‌ی تلگرام هم اسکیم vlc:// را نمی‌پذیرد)."""
        if not vlc_url:
            return vlc_url
        # حذف پیشوند اسکیم (vlc:// یا vlc-x-callback و ...)
        u = vlc_url
        if u.startswith("vlc://"):
            u = u[len("vlc://"):]
        # هر لینک https را هم به http تنزل بده
        if u.startswith("https://"):
            u = "http://" + u[len("https://"):]
        elif not u.startswith("http://"):
            u = "http://" + u
        return u

    # سازگاری با کدهای قدیمی که هنوز نام قبلی را صدا می‌زنند
    @staticmethod
    def vlc_to_https(vlc_url: str) -> str:
        return SiteClient.vlc_to_http(vlc_url)


def _clean(s: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", s or "")).strip()
