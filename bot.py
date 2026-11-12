import asyncio, hmac, logging, os, re, signal, subprocess, tempfile
from pathlib import Path
from aiohttp import web
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("insta-dl")
TOKEN = os.environ["BOT_TOKEN"]
TARGET_GROUP_ID = os.getenv("TARGET_GROUP_ID")
MAX_BYTES = int(os.getenv("MAX_FILE_MB", "49")) * 1024 * 1024
URL_RE = re.compile(r"https?://(?:www\\.)?(?:instagram\\.com|instagr\\.am)/[^\\s]+", re.I)
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".webm"}


def download_reel(url, folder):
    opts = {
        "outtmpl": str(Path(folder) / "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": False,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "max_filesize": MAX_BYTES,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        entries = info.get("entries") or [info]
        paths = []
        for entry in entries:
            if not entry:
                continue
            path = ydl.prepare_filename(entry)
            if not Path(path).exists():
                mp4 = str(Path(path).with_suffix(".mp4"))
                if Path(mp4).exists():
                    path = mp4
            if Path(path).exists() and Path(path).stat().st_size <= MAX_BYTES:
                paths.append(path)
        return paths


def natural_key(path):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\\d+)", path.name)]


def download_post(url, folder):
    # gallery-dl handles single-image and carousel posts, including mixed media.
    command = [
        "gallery-dl",
        "--no-input",
        "--quiet",
        "--directory", folder,
        "--filesize-max", str(MAX_BYTES),
        url,
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=240, check=False
    )
    paths = [
        path for path in Path(folder).rglob("*")
        if path.is_file()
        and path.stat().st_size <= MAX_BYTES
        and path.suffix.lower() in PHOTO_EXTS | VIDEO_EXTS
    ]
    paths.sort(key=natural_key)
    if result.returncode != 0 and not paths:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail[-1200:] or "gallery-dl could not extract this post")
    return [str(path) for path in paths]


async def send_media(context, chat_id, paths):
    for path in paths:
        suffix = Path(path).suffix.lower()
        with open(path, "rb") as media:
            if suffix in PHOTO_EXTS:
                await context.bot.send_photo(chat_id=chat_id, photo=media, read_timeout=120, write_timeout=120)
            elif suffix in VIDEO_EXTS:
                await context.bot.send_video(
                    chat_id=chat_id, video=media, supports_streaming=True,
                    read_timeout=120, write_timeout=120
                )


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    if update.effective_chat.type in ("group", "supergroup") and TARGET_GROUP_ID:
        if str(update.effective_chat.id) != TARGET_GROUP_ID:
            return
    match = URL_RE.search(msg.text)
    if not match:
        return

    url = match.group(0).rstrip(").,!?]}")
    status = await msg.reply_text("Downloading…")
    try:
        with tempfile.TemporaryDirectory(prefix="instadl_") as tmp:
            # Keep yt-dlp for Reels; use gallery-dl for regular posts/carousels.
            if re.search(r"/(?:reel|reels)/", url, re.I):
                paths = await asyncio.to_thread(download_reel, url, tmp)
            else:
                paths = await asyncio.to_thread(download_post, url, tmp)

            if not paths:
                await status.edit_text("No supported photo or video media found (or the file exceeds the upload limit).")
                return
            await status.delete()
            await send_media(context, update.effective_chat.id, paths)
    except Exception as exc:
        log.exception("Download failed")
        message = str(exc).strip()
        # Keep user-facing errors useful without exposing long tracebacks or credentials.
        if "There is no video in this post" in message:
            message = "No video found. If this is a photo post or carousel, try the gallery-dl extractor."
        elif not message:
            message = "The post could not be downloaded. It may be unavailable or restricted by Instagram."
        await status.edit_text(f"Download failed: {message[:700]}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text(
            "I'm online. Send an Instagram post or Reel link."
        )


async def run_webhook(application: Application, host: str, port: int):
    secret = os.getenv("WEBHOOK_SECRET")
    if secret and not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
        raise ValueError("WEBHOOK_SECRET must contain only A-Z, a-z, 0-9, underscore, or hyphen.")

    async def health_check(request):
        return web.json_response({"status": "ok", "service": "insta-dl"})

    async def telegram_webhook(request):
        if secret and not hmac.compare_digest(
            request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), secret
        ):
            return web.Response(status=403, text="Forbidden")
        try:
            payload = await request.json()
            update = Update.de_json(payload, application.bot)
        except Exception:
            return web.Response(status=400, text="Invalid update")
        await application.update_queue.put(update)
        return web.Response(text="OK")

    web_app = web.Application()
    web_app.router.add_get("/health", health_check)
    web_app.router.add_post(f"/{TOKEN}", telegram_webhook)

    await application.initialize()
    await application.start()
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)

    try:
        await site.start()
        webhook_url = f"https://{host}/{TOKEN}"
        await application.bot.set_webhook(
            url=webhook_url,
            secret_token=secret,
            allowed_updates=Update.ALL_TYPES,
        )
        log.info("Webhook server started; health endpoint: https://%s/health", host)

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass
        await stop_event.wait()
    finally:
        await runner.cleanup()
        await application.stop()
        await application.shutdown()


def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(
        MessageHandler(filters.COMMAND & filters.Regex(r"^/start"), start_command)
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    port = int(os.getenv("PORT", "10000"))
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if host:
        asyncio.run(run_webhook(application, host, port))
    else:
        application.run_polling()


if __name__ == "__main__":
    main()
