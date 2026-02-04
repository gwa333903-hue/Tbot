#!/usr/bin/env python
# pylint: disable=unused-argument

import logging
import os
import re
import glob
import yt_dlp

from telegram import (
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ---------------- BOT TOKEN (FROM ENV) ----------------
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise RuntimeError("❌ BOT TOKEN not found! Set TOKEN in Railway variables.")

# ---------------- PROGRESS HANDLER ----------------
class DownloadProgressHandler:
    def __init__(self, bot, chat_id, message_id):
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.last_percent = -1

    async def progress_hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes")

            if total and downloaded:
                percent = int(downloaded * 100 / total)
                if percent > self.last_percent and percent % 5 == 0:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self.message_id,
                        text=f"⬇️ Downloading... {percent}%",
                    )
                    self.last_percent = percent

        elif d["status"] == "finished":
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text="✅ Download complete! Processing...",
            )

# ---------------- COMMANDS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()} 👋\n\n"
        "Send me a YouTube link and I will download it 🎬",
        reply_markup=ForceReply(selective=True),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Send a YouTube link\n"
        "🎞 Choose quality\n"
        "⬇️ I will download & send it"
    )

# ---------------- RECEIVE VIDEO LINK ----------------
async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    video_url = update.message.text.strip()

    if not re.match(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+", video_url):
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Please send a valid YouTube link.",
        )
        return

    context.user_data["video_url"] = video_url

    keyboard = [
        [InlineKeyboardButton("🔥 Highest Quality", callback_data="best")],
        [InlineKeyboardButton("1080p", callback_data="1080p")],
        [InlineKeyboardButton("720p", callback_data="720p")],
        [InlineKeyboardButton("🎵 Audio Only", callback_data="audio_only")],
    ]

    await update.message.reply_text(
        "🎯 Choose download quality:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ---------------- BUTTON HANDLER ----------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_quality = query.data
    video_url = context.user_data.get("video_url")
    chat_id = query.message.chat_id

    if not video_url:
        await context.bot.send_message(chat_id, "⚠️ Please send the link again.")
        return

    progress_message = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🚀 Starting download ({selected_quality})...",
    )

    progress = DownloadProgressHandler(
        context.bot, chat_id, progress_message.message_id
    )

    try:
        download_dir = "downloads"
        os.makedirs(download_dir, exist_ok=True)

        ydl_opts = {
            "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "progress_hooks": [progress.progress_hook],
        }

        # -------- QUALITY OPTIONS --------
        if selected_quality == "audio_only":
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
            expected_ext = "mp3"

        elif selected_quality == "best":
            ydl_opts["format"] = "bestvideo+bestaudio/best"
            ydl_opts["merge_output_format"] = "mp4"
            expected_ext = "mp4"

        else:
            res = selected_quality.replace("p", "")
            ydl_opts["format"] = f"bestvideo[height<={res}]+bestaudio/best"
            ydl_opts["merge_output_format"] = "mp4"
            expected_ext = "mp4"

        # -------- DOWNLOAD --------
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            title = info.get("title", "video")

        files = glob.glob(os.path.join(download_dir, f"*.{expected_ext}"))
        final_file = max(files, key=os.path.getctime)

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_message.message_id,
            text="📤 Uploading to Telegram...",
        )

        if expected_ext == "mp3":
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=open(final_file, "rb"),
                caption=f"🎵 {title}",
            )
        else:
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(final_file, "rb"),
                caption=f"🎬 {title}",
            )

        os.remove(final_file)

    except Exception as e:
        logger.error(e)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_message.message_id,
            text="❌ Failed to download.",
        )

# ---------------- MAIN ----------------
def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, download_video)
    )
    application.add_handler(CallbackQueryHandler(button))

    application.run_polling()

if __name__ == "__main__":
    main()


