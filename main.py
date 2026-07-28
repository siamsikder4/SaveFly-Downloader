import os
import time
import asyncio
import uuid
import aiohttp
from datetime import datetime

# Python Event Loop Fix for Pyrogram
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardMarkup,
    KeyboardButton
)
from aiohttp import web
import yt_dlp

# Environment Variables
API_ID = int(os.environ.get("API_ID", "0").strip())
API_HASH = os.environ.get("API_HASH", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

# 👑 Admin Telegram ID (এখানে ইউজারের ইনফো ও লিংক নোটিফিকেশন যাবে)
OWNER_ID = int(os.environ.get("OWNER_ID", "6142774415"))  

# Temporary cache for YouTube video links & selections
yt_cache = {}

# Pyrogram Bot Client
bot_app = Client("social_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Bottom Reply UI
reply_markup_ui = ReplyKeyboardMarkup(
    [
        [KeyboardButton("ℹ️ Supported Platforms"), KeyboardButton("📜 Credits")]
    ],
    resize_keyboard=True
)

# 🛠️ Safe Edit Text Helper Function
async def safe_edit_text(message, text, reply_markup=None, disable_web_page_preview=True):
    try:
        await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview)
    except MessageNotModified:
        pass
    except Exception as e:
        print(f"Edit Message Error: {e}")

# 📊 Telegram Upload Progress Bar
async def upload_progress(current, total, status_msg, start_time):
    now = time.time()
    if not hasattr(upload_progress, "last_update"):
        upload_progress.last_update = {}

    msg_id = status_msg.id
    if msg_id in upload_progress.last_update and (now - upload_progress.last_update[msg_id]) < 3 and current != total:
        return

    upload_progress.last_update[msg_id] = now
    percentage = (current * 100) / total
    completed = int(percentage // 10)
    bar = "🚀" * completed + "⬜" * (10 - completed)

    mb_cur = current / (1024 * 1024)
    mb_tot = total / (1024 * 1024)

    text = (
        f"<b>🚀 Uploading to Telegram...</b>\n\n"
        f"[{bar}] <b>{percentage:.1f}%</b>\n"
        f"📦 <b>Size:</b> <code>{mb_cur:.1f} MB</code> / <code>{mb_tot:.1f} MB</code>"
    )
    await safe_edit_text(status_msg, text)

# 📩 Notify Admin About User Request
async def notify_admin_user_link(user, url):
    try:
        user_id = user.id
        first_name = user.first_name or "User"
        username = f"@{user.username}" if user.username else "No Username"
        
        log_text = (
            f"📥 **নতুন ভিডিও ডাউনলোড রিকোয়েস্ট!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **ইউজার নাম:** {first_name}\n"
            f"🏷️ **ইউজারনেম:** {username}\n"
            f"🆔 **ইউজার আইডি:** <code>{user_id}</code>\n\n"
            f"🔗 **ভিডিও লিংক:**\n{url}"
        )
        await bot_app.send_message(OWNER_ID, log_text, disable_web_page_preview=True)
    except Exception as e:
        print(f"Admin Notify Error: {e}")

# Background Task for Auto Deleting Messages (600s = 10 mins)
async def auto_delete_messages(messages, delay=600):
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
        "✨ **Welcome to Downloader Bot!** ✨\n\n"
        "🔗 Send me any link from **YouTube, Facebook, Instagram, TikTok, Twitter, or Pinterest** to download directly!\n\n"
        "👨‍💻 **Developer:** @developerBYsiam"
    )
    await message.reply_text(welcome_text, reply_markup=reply_markup_ui)

# Main Handler for Text Buttons and Links
@bot_app.on_message(filters.text & filters.private & ~filters.command(["start"]))
async def main_text_handler(client, message):
    text = message.text.strip()

    if text == "ℹ️ Supported Platforms":
        platforms_text = (
            "<b>📱 SUPPORTED PLATFORMS:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "▶️ **YouTube** (Select Quality 360p-1080p, MP3)\n"
            "📘 **Facebook** (Videos & Reels)\n"
            "📸 **Instagram** (Reels & Posts)\n"
            "🎵 **TikTok** (No Watermark)\n"
            "🐦 **Twitter / X** & 📌 **Pinterest**\n\n"
            "<i>Just send any video link here!</i>"
        )
        await message.reply_text(platforms_text, reply_markup=reply_markup_ui)

    elif text == "📜 Credits":
        await message.reply_text("<b>🤖 Downloader Bot</b>\n<b>👨‍💻 Lead Developer:</b> @developerBYsiam", reply_markup=reply_markup_ui)

    elif text.startswith("http://") or text.startswith("https://"):
        asyncio.create_task(notify_admin_user_link(message.from_user, text))

        if "youtube.com" in text or "youtu.be" in text:
            await handle_youtube_link(client, message, text)
        else:
            await process_direct_social_link(client, message, text)

# 🎬 YouTube Link Quality Selection UI
async def handle_youtube_link(client, message, url):
    status_msg = await message.reply_text("🔎 **Fetching available YouTube qualities...**")
    
    cache_id = str(uuid.uuid4())[:8]
    yt_cache[cache_id] = {"url": url, "user_msg": message}

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 360p", callback_data=f"ytq|360|{cache_id}"),
            InlineKeyboardButton("🎬 480p", callback_data=f"ytq|480|{cache_id}")
        ],
        [
            InlineKeyboardButton("🎬 720p (HD)", callback_data=f"ytq|720|{cache_id}"),
            InlineKeyboardButton("🎬 1080p (FHD)", callback_data=f"ytq|1080|{cache_id}")
        ],
        [
            InlineKeyboardButton("🎵 Audio Only (MP3)", callback_data=f"ytq|mp3|{cache_id}")
        ]
    ])

    await safe_edit_text(
        status_msg,
        "<b>🎥 YOUTUBE DOWNLOAD QUALITY SELECT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 <i>Choose your preferred video or audio resolution:</i>",
        reply_markup=keyboard
    )

# 🎬 YouTube Quality Selection Download Callback
@bot_app.on_callback_query(filters.regex(r"^ytq\|"))
async def youtube_quality_callback(client, callback_query):
    parts = callback_query.data.split("|")
    quality = parts[1]
    cache_id = parts[2]

    if cache_id not in yt_cache:
        await callback_query.answer("❌ Request expired! Send link again.", show_alert=True)
        return

    url = yt_cache[cache_id]["url"]
    user_msg = yt_cache[cache_id]["user_msg"]
    status_msg = callback_query.message

    await callback_query.answer(f"Downloading {quality}...")
    await safe_edit_text(status_msg, f"📥 **Downloading YouTube media in {quality.upper()}...**")

    os.makedirs("downloads", exist_ok=True)
    out_file = f"downloads/{callback_query.from_user.id}_{cache_id}.%(ext)s"

    loop = asyncio.get_event_loop()

    # Progress Hook for Download
    last_update = [0]
    def yt_progress_hook(d):
        if d['status'] == 'downloading':
            now = time.time()
            if now - last_update[0] < 3:
                return
            last_update[0] = now
            
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            
            if total > 0:
                percentage = (downloaded / total) * 100
                completed = int(percentage // 10)
                bar = "🟩" * completed + "⬜" * (10 - completed)
                
                mb_down = downloaded / (1024 * 1024)
                mb_tot = total / (1024 * 1024)
                
                text = (
                    f"<b>📥 Downloading ({quality.upper()})...</b>\n\n"
                    f"[{bar}] <b>{percentage:.1f}%</b>\n"
                    f"📦 <b>Size:</b> <code>{mb_down:.1f} MB</code> / <code>{mb_tot:.1f} MB</code>"
                )
                asyncio.run_coroutine_threadsafe(safe_edit_text(status_msg, text), loop)

    ydl_opts = {
        'outtmpl': out_file,
        'max_filesize': 50 * 1024 * 1024,
        'progress_hooks': [yt_progress_hook],
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb'],
                'skip': ['hls', 'dash']
            }
        }
    }

    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'

    if quality == "mp3":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        # 💡 Flexible Format Selection + Automatic MP4 Merge
        ydl_opts['format'] = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best'
        ydl_opts['merge_output_format'] = 'mp4'

    to_delete_messages = [user_msg]
    file_path = None

    try:
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        file_path = await loop.run_in_executor(None, download)

        if quality == "mp3" and file_path:
            base, _ = os.path.splitext(file_path)
            if os.path.exists(base + ".mp3"):
                file_path = base + ".mp3"

        if not file_path or not os.path.exists(file_path):
            await safe_edit_text(status_msg, "❌ **Failed to download file.** Try another quality.")
            return

        start_time = time.time()
        caption = f"⚡ **YouTube ({quality.upper()}) Downloaded!**\n\n✨ **Bot by:** @developerBYsiam"
        
        if quality == "mp3":
            sent_msg = await bot_app.send_audio(
                callback_query.message.chat.id, 
                audio=file_path, 
                caption=caption,
                progress=upload_progress,
                progress_args=(status_msg, start_time)
            )
        else:
            sent_msg = await bot_app.send_video(
                callback_query.message.chat.id, 
                video=file_path, 
                caption=caption,
                progress=upload_progress,
                progress_args=(status_msg, start_time)
            )
            
        to_delete_messages.append(sent_msg)
        await status_msg.delete()

        # ⏱️ Short 10 Minutes Auto Delete Notice
        notice_text = "⏳ **Notice:** Media & link will automatically delete in **10 minutes**! Save now."
        notice_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Developer Support", url="https://t.me/developerBYsiam")]
        ])
        
        notice_msg = await bot_app.send_message(callback_query.message.chat.id, notice_text, reply_markup=notice_keyboard)
        to_delete_messages.append(notice_msg)

        asyncio.create_task(auto_delete_messages(to_delete_messages, delay=600))

    except Exception as e:
        await safe_edit_text(status_msg, f"⚠️ **Error:** `{str(e)}`")

    finally:
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
            except Exception: pass
        if cache_id in yt_cache:
            del yt_cache[cache_id]

# Direct Downloader for Other Social Media Links
async def process_direct_social_link(client, message, url):
    status_msg = await message.reply_text("🔎 **Processing link... Please wait.**")
    to_delete_messages = [message]

    os.makedirs("downloads", exist_ok=True)
    out_file = f"downloads/{message.from_user.id}_{int(time.time())}.%(ext)s"

    loop = asyncio.get_event_loop()

    # Progress Hook for Download
    last_update = [0]
    def yt_progress_hook(d):
        if d['status'] == 'downloading':
            now = time.time()
            if now - last_update[0] < 3:
                return
            last_update[0] = now
            
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            
            if total > 0:
                percentage = (downloaded / total) * 100
                completed = int(percentage // 10)
                bar = "🟩" * completed + "⬜" * (10 - completed)
                
                mb_down = downloaded / (1024 * 1024)
                mb_tot = total / (1024 * 1024)
                
                text = (
                    f"<b>📥 Downloading Media...</b>\n\n"
                    f"[{bar}] <b>{percentage:.1f}%</b>\n"
                    f"📦 <b>Size:</b> <code>{mb_down:.1f} MB</code> / <code>{mb_tot:.1f} MB</code>"
                )
                asyncio.run_coroutine_threadsafe(safe_edit_text(status_msg, text), loop)

    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': out_file,
        'noplaylist': True,
        'max_filesize': 50 * 1024 * 1024,
        'progress_hooks': [yt_progress_hook],
        'quiet': True,
        'no_warnings': True,
    }

    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'

    file_path = None
    try:
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        file_path = await loop.run_in_executor(None, download)

        if not file_path or not os.path.exists(file_path):
            await safe_edit_text(status_msg, "❌ **Failed to download media.** Check link or restrictions.")
            return

        start_time = time.time()
        caption = "⚡ **Downloaded Successfully!**\n\n✨ **Bot by:** @developerBYsiam"
        
        sent_video = await bot_app.send_video(
            message.chat.id, 
            video=file_path, 
            caption=caption,
            progress=upload_progress,
            progress_args=(status_msg, start_time)
        )
        to_delete_messages.append(sent_video)

        await status_msg.delete()

        # ⏱️ Short 10 Minutes Auto Delete Notice
        notice_text = "⏳ **Notice:** Media & link will automatically delete in **10 minutes**! Save now."
        notice_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Developer Support", url="https://t.me/developerBYsiam")]
        ])
        
        notice_msg = await bot_app.send_message(message.chat.id, notice_text, reply_markup=notice_keyboard)
        to_delete_messages.append(notice_msg)

        asyncio.create_task(auto_delete_messages(to_delete_messages, delay=600))

    except Exception as e:
        await safe_edit_text(status_msg, f"⚠️ **Error:** `{str(e)}`")

    finally:
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
            except Exception: pass

# Health Check & Server Boot
async def handle(request): return web.Response(text="Bot Active!")

async def main():
    await bot_app.start()
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    await site.start()
    print("🤖 Social Downloader Bot Live!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
