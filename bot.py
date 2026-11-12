import logging, os, re, tempfile
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("insta-dl")
TOKEN=os.environ["BOT_TOKEN"]
TARGET_GROUP_ID=os.getenv("TARGET_GROUP_ID")
MAX_BYTES=int(os.getenv("MAX_FILE_MB","49"))*1024*1024
URL_RE=re.compile(r"https?://(?:www\.)?(?:instagram\.com|instagr\.am)/[^\s]+",re.I)

def download(url, folder):
    opts={"outtmpl":str(Path(folder)/"%(id)s.%(ext)s"),"format":"best[ext=mp4]/best",
          "merge_output_format":"mp4","noplaylist":False,"quiet":True,"no_warnings":True,
          "restrictfilenames":True,"max_filesize":MAX_BYTES}
    with YoutubeDL(opts) as ydl:
        info=ydl.extract_info(url,download=True)
        entries=info.get("entries") or [info]
        paths=[]
        for entry in entries:
            if not entry: continue
            path=ydl.prepare_filename(entry)
            if not Path(path).exists():
                mp4=str(Path(path).with_suffix(".mp4"))
                if Path(mp4).exists(): path=mp4
            if Path(path).exists() and Path(path).stat().st_size<=MAX_BYTES: paths.append(path)
        return paths

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message
    if not msg or not msg.text: return
    if update.effective_chat.type in ("group","supergroup") and TARGET_GROUP_ID:
        if str(update.effective_chat.id)!=TARGET_GROUP_ID: return
    match=URL_RE.search(msg.text)
    if not match: return
    status=await msg.reply_text("Downloading…")
    try:
        with tempfile.TemporaryDirectory(prefix="instadl_") as tmp:
            paths=download(match.group(0),tmp)
            if not paths:
                await status.edit_text("No downloadable media found (or the file exceeds the upload limit).")
                return
            await status.delete()
            for p in paths:
                with open(p,"rb") as f:
                    await context.bot.send_video(chat_id=update.effective_chat.id,video=f,
                                                 supports_streaming=True,read_timeout=120,write_timeout=120)
    except Exception as exc:
        log.exception("Download failed")
        try: await status.edit_text("Download failed. The post may be private, unavailable, or require Instagram cookies.")
        except Exception: pass

async def health(update, context):
    await update.message.reply_text("I'm online. Send an Instagram post or Reel link.")

def main():
    app=Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/start"),health))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle))
    port=int(os.getenv("PORT","10000"))
    host=os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if host:
        app.run_webhook(listen="0.0.0.0",port=port,url_path=TOKEN,
                        webhook_url=f"https://{host}/{TOKEN}",secret_token=os.getenv("WEBHOOK_SECRET"))
    else:
        app.run_polling()

if __name__=="__main__": main()
