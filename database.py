# -*- coding: utf-8 -*-
"""
database.py
-----------
لایه‌ی دیتابیس ربات (SQLite). فایل دیتابیس در اولین اجرا خودکار ساخته می‌شود.

جدول‌ها:
  users            : کاربران ربات
  channels         : کانال‌های عضویت اجباری (ادمین اضافه/حذف می‌کند)
  favorites        : فیلم‌های نشان‌شده‌ی هر کاربر
  movie_cache      : کش اطلاعات فیلم برای کاهش درخواست به سایت
  admins           : ادمین‌های ربات
  settings         : تنظیمات کلید/مقدار
  error_log        : لاگ خطاها
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, List, Optional, Tuple

DEFAULT_DB = "data/bot.db"


class Database:
    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
        self._lock = threading.RLock()
        # check_same_thread=False چون PTB ممکن است از تردهای مختلف صدا بزند؛
        # خودمان با قفل هماهنگ می‌کنیم.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # ---------------- ساخت جدول‌ها ----------------
    def _init_schema(self) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id     INTEGER PRIMARY KEY,
                    username    TEXT,
                    first_name  TEXT,
                    joined_at   INTEGER,
                    last_seen   INTEGER,
                    is_blocked  INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS channels (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id     TEXT UNIQUE,      -- @username یا -100...
                    title       TEXT,
                    invite_link TEXT,
                    added_at    INTEGER
                );
                CREATE TABLE IF NOT EXISTS favorites (
                    user_id     INTEGER,
                    movie_id    TEXT,
                    title       TEXT,
                    added_at    INTEGER,
                    PRIMARY KEY (user_id, movie_id)
                );
                CREATE TABLE IF NOT EXISTS movie_cache (
                    movie_id    TEXT PRIMARY KEY,
                    payload     TEXT,            -- JSON فیلم
                    cached_at   INTEGER
                );
                CREATE TABLE IF NOT EXISTS admins (
                    user_id     INTEGER PRIMARY KEY,
                    added_at    INTEGER
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key         TEXT PRIMARY KEY,
                    value       TEXT
                );
                CREATE TABLE IF NOT EXISTS error_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          INTEGER,
                    context     TEXT,
                    message     TEXT
                );
                CREATE TABLE IF NOT EXISTS search_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER,
                    query       TEXT,
                    ts          INTEGER
                );
                CREATE TABLE IF NOT EXISTS watch_history (
                    user_id     INTEGER,
                    movie_id    TEXT,
                    title       TEXT,
                    episode     TEXT,
                    ts          INTEGER,
                    PRIMARY KEY (user_id, movie_id)
                );
                """
            )
            self.conn.commit()

    # ---------------- کاربران ----------------
    def upsert_user(self, user_id: int, username: str, first_name: str) -> None:
        now = int(time.time())
        with self._lock:
            self.conn.execute(
                """INSERT INTO users(user_id, username, first_name, joined_at, last_seen)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     username=excluded.username,
                     first_name=excluded.first_name,
                     last_seen=excluded.last_seen""",
                (user_id, username, first_name, now, now),
            )
            self.conn.commit()

    def count_users(self) -> int:
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]

    def all_user_ids(self) -> List[int]:
        with self._lock:
            return [r["user_id"] for r in
                    self.conn.execute("SELECT user_id FROM users WHERE is_blocked=0").fetchall()]

    def set_blocked(self, user_id: int, blocked: bool) -> None:
        with self._lock:
            self.conn.execute("UPDATE users SET is_blocked=? WHERE user_id=?",
                              (1 if blocked else 0, user_id))
            self.conn.commit()

    # ---------------- ادمین‌ها ----------------
    def add_admin(self, user_id: int) -> None:
        with self._lock:
            self.conn.execute("INSERT OR IGNORE INTO admins(user_id, added_at) VALUES(?,?)",
                              (user_id, int(time.time())))
            self.conn.commit()

    def remove_admin(self, user_id: int) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
            self.conn.commit()

    def is_admin(self, user_id: int) -> bool:
        with self._lock:
            return self.conn.execute("SELECT 1 FROM admins WHERE user_id=?",
                                     (user_id,)).fetchone() is not None

    def list_admins(self) -> List[int]:
        with self._lock:
            return [r["user_id"] for r in self.conn.execute("SELECT user_id FROM admins").fetchall()]

    # ---------------- کانال‌های عضویت اجباری ----------------
    def add_channel(self, chat_id: str, title: str = "", invite_link: str = "") -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO channels(chat_id, title, invite_link, added_at) VALUES(?,?,?,?)
                   ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,
                     invite_link=excluded.invite_link""",
                (chat_id, title, invite_link, int(time.time())),
            )
            self.conn.commit()

    def remove_channel(self, chat_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
            self.conn.commit()
            return cur.rowcount > 0

    def list_channels(self) -> List[sqlite3.Row]:
        with self._lock:
            return self.conn.execute("SELECT * FROM channels ORDER BY id").fetchall()

    # ---------------- علاقه‌مندی‌ها ----------------
    def add_favorite(self, user_id: int, movie_id: str, title: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO favorites(user_id, movie_id, title, added_at) VALUES(?,?,?,?)",
                (user_id, movie_id, title, int(time.time())),
            )
            self.conn.commit()

    def remove_favorite(self, user_id: int, movie_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM favorites WHERE user_id=? AND movie_id=?",
                              (user_id, movie_id))
            self.conn.commit()

    def is_favorite(self, user_id: int, movie_id: str) -> bool:
        with self._lock:
            return self.conn.execute(
                "SELECT 1 FROM favorites WHERE user_id=? AND movie_id=?",
                (user_id, movie_id)).fetchone() is not None

    def list_favorites(self, user_id: int) -> List[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM favorites WHERE user_id=? ORDER BY added_at DESC",
                (user_id,)).fetchall()

    # ---------------- کش فیلم ----------------
    def cache_get(self, movie_id: str, max_age: int) -> Optional[str]:
        with self._lock:
            row = self.conn.execute("SELECT payload, cached_at FROM movie_cache WHERE movie_id=?",
                                    (movie_id,)).fetchone()
            if row and (int(time.time()) - row["cached_at"] <= max_age):
                return row["payload"]
            return None

    def cache_put(self, movie_id: str, payload: str) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO movie_cache(movie_id, payload, cached_at) VALUES(?,?,?)
                   ON CONFLICT(movie_id) DO UPDATE SET payload=excluded.payload,
                     cached_at=excluded.cached_at""",
                (movie_id, payload, int(time.time())),
            )
            self.conn.commit()

    # ---------------- تنظیمات ----------------
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO settings(key, value) VALUES(?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, value))
            self.conn.commit()

    # ---------------- لاگ ----------------
    def log_error(self, context: str, message: str) -> None:
        with self._lock:
            self.conn.execute("INSERT INTO error_log(ts, context, message) VALUES(?,?,?)",
                              (int(time.time()), context, message[:2000]))
            self.conn.commit()

    def recent_errors(self, limit: int = 15) -> List[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM error_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def log_search(self, user_id: int, query: str) -> None:
        with self._lock:
            self.conn.execute("INSERT INTO search_log(user_id, query, ts) VALUES(?,?,?)",
                              (user_id, query, int(time.time())))
            self.conn.commit()

    def recent_searches(self, user_id: int, limit: int = 10) -> List[str]:
        """آخرین جستجوهای یکتای کاربر (جدیدترین اول)."""
        with self._lock:
            rows = self.conn.execute(
                """SELECT query, MAX(ts) mts FROM search_log
                   WHERE user_id=? AND query<>''
                   GROUP BY query ORDER BY mts DESC LIMIT ?""",
                (user_id, limit)).fetchall()
            return [r["query"] for r in rows]

    def clear_searches(self, user_id: int) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM search_log WHERE user_id=?", (user_id,))
            self.conn.commit()

    # ---------------- تاریخچه‌ی تماشا ----------------
    def add_watch(self, user_id: int, movie_id: str, title: str, episode: str = "") -> None:
        """ثبت/به‌روزرسانی آخرین تماشای کاربر از یک فیلم."""
        with self._lock:
            self.conn.execute(
                """INSERT INTO watch_history(user_id, movie_id, title, episode, ts)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(user_id, movie_id) DO UPDATE SET
                     title=excluded.title, episode=excluded.episode, ts=excluded.ts""",
                (user_id, movie_id, title, episode, int(time.time())))
            self.conn.commit()

    def list_watch(self, user_id: int, limit: int = 15):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM watch_history WHERE user_id=? ORDER BY ts DESC LIMIT ?",
                (user_id, limit)).fetchall()

    def clear_watch(self, user_id: int) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM watch_history WHERE user_id=?", (user_id,))
            self.conn.commit()

    def stats(self) -> dict:
        with self._lock:
            c = self.conn
            return {
                "users": c.execute("SELECT COUNT(*) x FROM users").fetchone()["x"],
                "blocked": c.execute("SELECT COUNT(*) x FROM users WHERE is_blocked=1").fetchone()["x"],
                "channels": c.execute("SELECT COUNT(*) x FROM channels").fetchone()["x"],
                "favorites": c.execute("SELECT COUNT(*) x FROM favorites").fetchone()["x"],
                "searches": c.execute("SELECT COUNT(*) x FROM search_log").fetchone()["x"],
                "cached": c.execute("SELECT COUNT(*) x FROM movie_cache").fetchone()["x"],
                "errors": c.execute("SELECT COUNT(*) x FROM error_log").fetchone()["x"],
            }

    def checkpoint(self) -> None:
        """WAL را در فایل اصلی ادغام می‌کند تا بکاپ کامل باشد."""
        with self._lock:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.commit()

    def swap_file(self, new_path: str) -> None:
        """
        دیتابیس فعلی را با فایل جدید (مثلاً بکاپ آپلودشده) جایگزین می‌کند.
        از فایل فعلی یک نسخه‌ی .bak می‌گیرد، اتصال را می‌بندد، فایل را جایگزین
        و دوباره باز می‌کند — بدون تغییر مرجع شیء Database.
        """
        import os
        import shutil
        with self._lock:
            self.checkpoint()
            self.conn.close()
            # پاک‌سازی فایل‌های جانبی WAL/SHM
            for suffix in ("-wal", "-shm"):
                p = self.path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            # بکاپ فایل فعلی
            if os.path.exists(self.path):
                shutil.copy2(self.path, self.path + ".bak")
            shutil.copy2(new_path, self.path)
            # بازگشایی
            self.conn = sqlite3.connect(self.path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()

    @staticmethod
    def is_sqlite_file(path: str) -> bool:
        """بررسی می‌کند فایل واقعاً یک دیتابیس SQLite است."""
        try:
            with open(path, "rb") as f:
                return f.read(16) == b"SQLite format 3\x00"
        except OSError:
            return False

    def close(self) -> None:
        with self._lock:
            self.conn.close()
