import os
import time
import asyncio
from datetime import datetime

# Python Event Loop Fix for Pyrogram
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web
import yt_dlp

# Environment Variables
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Owner ID
OWNER_ID = int(os.environ.get("OWNER_ID", "6142774415"))  

# Pyrogram Bot Client
bot_app = Client("social_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Bottom Reply UI
reply_markup_ui = ReplyKeyboardMarkup(
    [
        [KeyboardButton("ℹ️ Supported Platforms"), KeyboardButton("📜 Credits")]
    ],
    resize_keyboard=True
)

# 🛠️ Safe Edit Text Helper
async def safe_edit_text(message, text, reply_markup=None, disable_web_page_preview=True):
    try:
        await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview)
    except MessageNotModified:
        pass
    except Exception as e:
        print(f"Edit Message Error: {e}")

# Background Task for Auto Deleting Messages (180s = 3 mins)
async def auto_delete_messages(messages, delay=180):
    await asyncio.sleep(delay)
    for msg in messages:
        try:
            await msg.delete()
        except Exception:
            pass

# /start Command
@bot_app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    welcome_text = (
        "✨ **Welcome to All-in-One Social Media Downloader Bot!** ✨\n\n"
        "🔗 Send me a link from **YouTube, Facebook, Instagram, TikTok, Twitter, or Pinterest**, and I will download and send it to you instantly!\n\n"
        "👨‍💻 **Developer:** @developerBYsiam"
    )
    await message.reply_text(welcome_text, reply_markup=reply_markup_ui)

# Main Handler for Text Buttons and Social Media Links
@bot_app.on_message(filters.text & filters.private & ~filters.command(["start"]))
async def main_text_handler(client, message):
    text = message.text.strip()

    if text == "ℹ️ Supported Platforms":
        platforms_text = (
            "<b>📱 SUPPORTED PLATFORMS:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "▶️ **YouTube** (Videos & Shorts)\n"
            "📘 **Facebook** (Videos & Reels)\n"
            "📸 **Instagram** (Reels, Posts, Stories)\n"
            "🎵 **TikTok** (Without Watermark)\n"
            "🐦 **Twitter / X** (Videos)\n"
            "📌 **Pinterest** (Videos & Images)\n\n"
            "<i>Just send any video link here!</i>"
        )
        await message.reply_text(platforms_text, reply_markup=reply_markup_ui)

    elif text == "📜 Credits":
        await message.reply_text("<b>🤖 Social Media Downloader Bot</b>\n<b>👨‍💻 Lead Developer:</b> @developerBYsiam", reply_markup=reply_markup_ui)

    # Social Media URL Processing (Detect http/https links)
    elif text.startswith("http://") or text.startswith("https://"):
        await process_social_media_link(client, message, text)

# Download & Send Logic using yt-dlp
async def process_social_media_link(client, message, url):
    status_msg = await message.reply_text("🔎 **Processing link... Please wait.**")
    to_delete_messages = [message]

    output_template = f"downloads/{message.from_user.id}_%(id)s.%(ext)s"
    os.makedirs("downloads", exist_ok=True)

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': output_template,
        'noplaylist': True,
        'max_filesize': 50 * 1024 * 1024,  # Bot API 50MB limit safeguard
    }

    file_path = None
    try:
        await safe_edit_text(status_msg, "📥 **Downloading media from social platform...**")
        
        # Run yt-dlp in a separate thread to keep bot responsive
        loop = asyncio.get_event_loop()
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        file_path = await loop.run_in_executor(None, download)

        if not file_path or not os.path.exists(file_path):
            await safe_edit_text(status_msg, "❌ **Failed to download media!** The link might be invalid or restricted.")
            return

        await safe_edit_text(status_msg, "🚀 **Uploading media to Telegram...**")
        
        caption = "⚡ **Downloaded Successfully!**\n\n✨ **Bot by:** @developerBYsiam"
        sent_video = await bot_app.send_video(
            message.chat.id, 
            video=file_path, 
            caption=caption
        )
        to_delete_messages.append(sent_video)

        # Clear status message
        await status_msg.delete()

        # Send Auto-Delete Notice
        notice_text = (
            "⏳ **Auto Delete Notice**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Your link, downloaded video, and this notice will be automatically deleted in **3 minutes**!\n"
            "Please save or forward it now."
        )
        notice_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Developer Support", url="https://t.me/developerBYsiam")]
        ])
        
        notice_msg = await bot_app.send_message(
            message.chat.id, 
            notice_text, 
            reply_markup=notice_keyboard
        )
        to_delete_messages.append(notice_msg)

        # 3 Minutes Auto Delete Task
        asyncio.create_task(auto_delete_messages(to_delete_messages, delay=180))

    except Exception as e:
        error_str = str(e)
        if "File is too large" in error_str or "max_filesize" in error_str:
            await safe_edit_text(status_msg, "❌ **Error:** The video file size exceeds Telegram Bot's 50MB upload limit.")
        else:
            await safe_edit_text(status_msg, f"⚠️ **Error:** `{error_str}`")

    finally:
        # Clean up local downloaded file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

# Health Check & Server Boot for Render
async def handle(request): return web.Response(text="Social Downloader Bot Active!")

async def main():
    await bot_app.start()
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print("🤖 Social Media Downloader Bot Active!")
    asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
