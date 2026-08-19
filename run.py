# -*- coding: utf-8 -*-
"""
run.py
-------
نقطه‌ی ورود اصلی برای Railway.

هم‌زمان:
  ۱. Player Server (Flask) را روی PORT ریلوی ران می‌کند
  ۲. ربات تلگرام را در یک ترد جداگانه اجرا می‌کند

روی Railway فقط کافی است:
  - Start Command = python run.py
  - Port = 8080  (یا هر پورتی Railway بدهد)
"""
from __future__ import annotations

import logging
import threading
import time

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("main")

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


def start_player_server():
    """Flask Player Server را در ترد جداگانه استارت می‌کند."""
    from player_server import app
    import config

    port = config.PLAYER_PORT
    log.info("🎬 Player Server روی پورت %d…", port)
    log.info("📡 PLAYER_BASE_URL=%s", config.PLAYER_BASE_URL)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


def start_bot():
    """ربات تلگرام را اجرا می‌کند."""
    import config
    from bot import build_application, site  # site سراسری است

    if config.token_is_placeholder():
        log.error("❌ BOT_TOKEN تنظیم نشده است.")
        return

    app = build_application()
    try:
        ok = site.ensure_login()
        log.info("وضعیت لاگین اولیه به سایت: %s", "موفق" if ok else "ناموفق")
    except Exception as e:
        log.warning("لاگین اولیه ناموفق: %s", e)

    log.info("🤖 ربات در حال اجراست…")
    app.run_polling(
        allowed_updates=["message", "callback_query", "inline_query"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    import config
    log.info("═══════════════════════════════════════")
    log.info("🚀 SilentMovie — Bot + Player Server")
    log.info("═══════════════════════════════════════")
    log.info("PORT=%d  BASE_URL=%s", config.PLAYER_PORT, config.PLAYER_BASE_URL)

    # Player Server در ترد جداگانه
    player_thread = threading.Thread(target=start_player_server, daemon=True)
    player_thread.start()

    # صبر تا Flask بالا بیاید
    time.sleep(2)

    # Bot در ترد اصلی
    start_bot()
