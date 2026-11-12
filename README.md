# Insta-DL Telegram Bot

A small Instagram link-to-Telegram bot for private chats and an optional configured group. It uses yt-dlp and sends the downloaded media **without adding a bot-generated caption, creator-name footer, or video overlay**.

> The bot cannot remove watermarks already embedded in the source video. The small icon shown beside a Telegram message is the Telegram bot's profile photo; change it with BotFather if you want different branding.

## Deploy to Render

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. In Render, create a **New Blueprint Instance** from this repository.
3. Set `BOT_TOKEN` in the Render environment settings. Set `TARGET_GROUP_ID` to your group ID to enable group downloads; leave it blank to allow any chat the bot can access.
4. Deploy. Render's generated `WEBHOOK_SECRET` is used by the app's webhook endpoint.

The service uses a webhook on Render and polling for local development. Render Free services may sleep when idle; the first request after sleep can be delayed.

## Local run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# set BOT_TOKEN in your shell
python bot.py
```

## Behavior

- Accepts Instagram Reel/post URLs in private chats.
- Accepts links in groups; optionally restrict group handling with `TARGET_GROUP_ID`.
- Sends media with no extra attribution footer or bot-added watermark.
- Temporary downloads are deleted automatically after sending.
- `MAX_FILE_MB` defaults to 49 MB to stay below the standard Telegram Bot API upload limit.

Private Instagram posts and some Reels may require authenticated cookies; this starter does not store cookies. Only download content you are authorized to access and share.
