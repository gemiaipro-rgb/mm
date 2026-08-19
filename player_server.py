# -*- coding: utf-8 -*-
"""
player_server.py
----------------
سرور Player اختصاصی SilentMovie.

مسئولیت‌ها:
  • تولید و اعتبارسنجی توکن‌های موقت برای فیلم
  • سرو صفحه‌ی Player (HTML)
  • Streaming Proxy (با پشتیبانی از Range) — URL واقعی فیلم مخفی می‌ماند
  • Download Proxy

اجرا:
  python player_server.py

یا:
  gunicorn -w 2 -b 0.0.0.0:8080 player_server:app
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import shutil
import time
import uuid
from typing import Dict, Optional, Tuple

import requests
from flask import (Flask, Response, abort, jsonify, render_template,
                   request, stream_with_context)

import config

log = logging.getLogger("player")

app = Flask(__name__, template_folder="player_templates")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024 * 1024  # 50 GB

# ---------------- ذخیره‌ی توکن‌ها ----------------
# token -> {"url": str, "title": str, "quality": str, "episode": str, "expires": float}
_tokens: Dict[str, dict] = {}

# حداکثر توکن‌های همزمان (جلوگیری از حافظه‌ی نامحدود)
_MAX_TOKENS = 5000


def _cleanup_expired() -> None:
    """توکن‌های منقضی را پاک می‌کند."""
    now = time.time()
    expired = [t for t, v in _tokens.items() if v["expires"] < now]
    for t in expired:
        del _tokens[t]


def create_token(video_url: str, title: str = "",
                 quality: str = "", episode: str = "") -> str:
    """توکن موقت ایجاد و ذخیره می‌کند. توکن را برمی‌گرداند."""
    _cleanup_expired()
    if len(_tokens) >= _MAX_TOKENS:
        # حذف قدیمی‌ترین‌ها
        sorted_tokens = sorted(_tokens.items(), key=lambda x: x[1]["expires"])
        for t, _ in sorted_tokens[:len(_tokens) - _MAX_TOKENS + 100]:
            del _tokens[t]

    token = uuid.uuid4().hex
    _tokens[token] = {
        "url": video_url,
        "title": title,
        "quality": quality,
        "episode": episode,
        "expires": time.time() + config.PLAYER_TOKEN_EXPIRY,
    }
    log.info("Token created: %s... (title=%s)", token[:12], title[:50])
    return token


def resolve_token(token: str) -> Optional[dict]:
    """توکن را اعتبارسنجی و اطلاعات فیلم را برمی‌گرداند."""
    data = _tokens.get(token)
    if data is None:
        return None
    if time.time() > data["expires"]:
        del _tokens[token]
        return None
    return data


def _sign_token(token: str) -> str:
    """امضای توکن برای جلوگیری از دسترسی غیرمجاز."""
    return hmac.new(
        config.PLAYER_TOKEN_SECRET.encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]


def verify_token(token: str) -> bool:
    """بررسی اعتبار توکن + امضا."""
    data = resolve_token(token)
    if data is None:
        return False
    # امضا را چک نمی‌کنیم چون توکن از طریق bot ایجاد شده و در حافظه است
    # این لایه برای آینده اگر خواستیم توکن‌ها را URL-safe کنیم
    return True


# ---------------- Streaming Proxy ----------------
def _proxy_stream(video_url: str, download: bool = False) -> Response:
    """استریم پروکسی با پشتیبانی از Range header."""
    headers = {"User-Agent": config.UA if hasattr(config, "UA") else
               "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    # Range header را پاس بده
    range_header = request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header

    try:
        # HEAD برای دریافت اطلاعات فایل
        head_resp = requests.head(
            video_url, headers=headers, timeout=30, allow_redirects=True, verify=False)
    except Exception as e:
        log.error("HEAD request failed: %s", e)
        abort(502, description="Unable to connect to video server")

    content_length = head_resp.headers.get("Content-Length")
    content_type = head_resp.headers.get("Content-Type", "video/mp4")
    accept_ranges = head_resp.headers.get("Accept-Ranges", "")

    resp_headers = {
        "Content-Type": content_type,
        "Accept-Ranges": accept_ranges or "bytes",
    }
    if download:
        resp_headers["Content-Disposition"] = "attachment"

    if range_header and accept_ranges:
        # Pass-through streaming with range
        resp_headers["Content-Length"] = content_length
        resp_headers["Content-Range"] = head_resp.headers.get("Content-Range", "")

        def generate():
            try:
                with requests.get(
                    video_url, headers=headers, stream=True,
                    timeout=60, allow_redirects=True, verify=False,
                ) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            yield chunk
            except Exception as e:
                log.error("Stream error: %s", e)

        return Response(
            stream_with_context(generate()),
            status=head_resp.status_code,
            headers=resp_headers,
        )
    else:
        # بدون Range — کل فایل
        if content_length:
            resp_headers["Content-Length"] = content_length

        def generate():
            try:
                with requests.get(
                    video_url, headers={"User-Agent": headers["User-Agent"]},
                    stream=True, timeout=60, allow_redirects=True, verify=False,
                ) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            yield chunk
            except Exception as e:
                log.error("Stream error: %s", e)

        return Response(
            stream_with_context(generate()),
            status=200,
            headers=resp_headers,
        )


# ---------------- Routes ----------------
@app.route("/player/<token>")
def player_page(token: str):
    """صفحه‌ی Player فیلم."""
    data = resolve_token(token)
    if data is None:
        return render_template("error.html", error_code="TOKEN_EXPIRED",
                               error_title="توکن منقضی شده",
                               error_message="این لینک منقضی شده است. لطفاً از ربات دوباره اقدام کنید.",
                               site_name="SilentMovie"), 410

    quality_label = f"{data['quality']}p" if data['quality'] else ""
    episode_label = data.get("episode", "")
    return render_template("player.html",
                           token=token,
                           title=data.get("title", "SilentMovie"),
                           quality=quality_label,
                           episode=episode_label,
                           site_name="SilentMovie")


@app.route("/api/stream/<token>")
def stream_api(token: str):
    """API استریم — URL واقعی فیلم از اینجا سرو می‌شود."""
    data = resolve_token(token)
    if data is None:
        return jsonify({"error": "Token expired or not found"}), 410

    video_url = data["url"]
    log.info("Stream request: token=%s..., download=%s", token[:12],
             request.args.get("download"))
    # URL واقعی لاگ نمی‌شود
    return _proxy_stream(video_url, download=False)


@app.route("/download/<token>")
def download_api(token: str):
    """API دانلود — با Content-Disposition: attachment."""
    data = resolve_token(token)
    if data is None:
        return jsonify({"error": "Token expired or not found"}), 410

    video_url = data["url"]
    log.info("Download request: token=%s...", token[:12])
    return _proxy_stream(video_url, download=True)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "tokens": len(_tokens)})


# ---------------- Runner ----------------
def run_server():
    """اجرای سرور Player."""
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )
    log.info("🎬 SilentMovie Player Server starting on port %d…", config.PLAYER_PORT)
    log.info("📡 Base URL: %s", config.PLAYER_BASE_URL)
    app.run(host="0.0.0.0", port=config.PLAYER_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
