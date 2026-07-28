import os
import time
import asyncio
import sqlite3
import uuid
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

# Owner ID
OWNER_ID = int(os.environ.get("OWNER_ID", "6142774415"))  

# Temporary cache for YouTube video links
yt_cache = {}

# Database Setup for Bot Settings (Multi F-Sub)
DB_NAME = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Multi-Channel Force Sub DB Helper Functions
def get_fsub_channels():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'fsub_channels'")
    row = cursor.fetchone()
    conn.close()
    if not row or not row[0]:
        return []
    return [x.strip() for x in row[0].split(",") if x.strip()]

def set_fsub_channels(channel_list):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    val = ",".join(channel_list) if channel_list else ""
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('fsub_channels', ?)", (val,))
    conn.commit()
    conn.close()

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

# Check Multi Force Sub Channels
async def check_force_sub(client, user_id):
    channels = get_fsub_channels()
    if not channels or user_id == OWNER_ID:
        return True, []

    unjoined = []
    for ch in channels:
        try:
            member = await client.get_chat_member(ch, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                unjoined.append(ch)
        except Exception:
            unjoined.append(ch)

    return (len(unjoined) == 0), unjoined

# Build Join Keyboard for Unjoined Channels
async def build_fsub_keyboard(client, unjoined_channels):
    buttons = []
    for idx, ch in enumerate(unjoined_channels, 1):
        try:
            chat = await client.get_chat(ch)
            invite_link = chat.invite_link or f"https://t.me/{chat.username}"
            title = chat.title or f"Channel {idx}"
        except Exception:
            invite_link = "https://t.me/"
            title = f"Channel {idx}"
        buttons.append([InlineKeyboardButton(f"📢 Join {title}", url=invite_link)])
    
    buttons.append([InlineKeyboardButton("🔄 Verify & Continue", callback_data="check_fsub_again")])
    return InlineKeyboardMarkup(buttons)

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
    user_id = message.from_user.id
    is_joined, unjoined = await check_force_sub(client, user_id)

    if not is_joined:
        keyboard = await build_fsub_keyboard(client, unjoined)
        await message.reply_text(
            "⚠️ **You must join all our official channels to use this bot!**",
            reply_markup=keyboard
        )
        return

    welcome_text = (
        "✨ **Welcome to Downloader Bot!** ✨\n\n"
        "🔗 Send me any video link from **YouTube, Facebook, Instagram, TikTok, Twitter, or Pinterest**!\n\n"
        "🎬 **YouTube Feature:** Select video quality before downloading!\n"
        "👨‍💻 **Developer:** @developerBYsiam"
    )
    await message.reply_text(welcome_text, reply_markup=reply_markup_ui)

# Callback Query Handler for Force Sub Re-check
@bot_app.on_callback_query(filters.regex("^check_fsub_again$"))
async def fsub_callback(client, callback_query):
    user_id = callback_query.from_user.id
    is_joined, unjoined = await check_force_sub(client, user_id)

    if is_joined:
        await callback_query.answer("✅ Thank you for joining! You can now use the bot.", show_alert=True)
        await callback_query.message.delete()
    else:
        await callback_query.answer("❌ You still haven't joined all required channels!", show_alert=True)

# Main Handler for Text Buttons and Links
@bot_app.on_message(filters.text & filters.private & ~filters.command(["start", "setfsub", "addfsub", "offsub", "showfsub"]))
async def main_text_handler(client, message):
    text = message.text.strip()
    user_id = message.from_user.id

    is_joined, unjoined = await check_force_sub(client, user_id)
    if not is_joined:
        keyboard = await build_fsub_keyboard(client, unjoined)
        await message.reply_text("⚠️ **Please join all our channels first to use the bot!**", reply_markup=keyboard)
        return

    if text == "ℹ️ Supported Platforms":
        platforms_text = (
            "<b>📱 SUPPORTED PLATFORMS:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "▶️ **YouTube** (Select 360p, 720p, 1080p, MP3)\n"
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
        if "youtube.com" in text or "youtu.be" in text:
            await handle_youtube_link(client, message, text)
        else:
            await process_direct_social_link(client, message, text)

# 🎬 YouTube Link Handler (Quality Buttons UI)
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

# YouTube Download Execution Callback
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

    if quality == "mp3":
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_file,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'max_filesize': 50 * 1024 * 1024,
        }
    else:
        ydl_opts = {
            'format': f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}][ext=mp4]/best',
            'outtmpl': out_file,
            'max_filesize': 50 * 1024 * 1024,
        }

    to_delete_messages = [user_msg]
    file_path = None

    try:
        loop = asyncio.get_event_loop()
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        file_path = await loop.run_in_executor(None, download)

        # Handle mp3 extension rename
        if quality == "mp3" and file_path:
            base, _ = os.path.splitext(file_path)
            if os.path.exists(base + ".mp3"):
                file_path = base + ".mp3"

        if not file_path or not os.path.exists(file_path):
            await safe_edit_text(status_msg, "❌ **Failed to download file.** Try another quality.")
            return

        await safe_edit_text(status_msg, "🚀 **Uploading to Telegram...**")

        caption = f"⚡ **YouTube ({quality.upper()}) Downloaded!**\n\n✨ **Bot by:** @developerBYsiam"
        
        if quality == "mp3":
            sent_msg = await bot_app.send_audio(callback_query.message.chat.id, audio=file_path, caption=caption)
        else:
            sent_msg = await bot_app.send_video(callback_query.message.chat.id, video=file_path, caption=caption)
            
        to_delete_messages.append(sent_msg)
        await status_msg.delete()

        # ⏱️ 10 Minutes Notice Message
        notice_text = (
            "⏳ **Auto Delete Notice**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Your link, downloaded media, and this notice will be automatically deleted in **10 minutes**!\n"
            "Please save or forward it now."
        )
        notice_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Developer Support", url="https://t.me/developerBYsiam")]
        ])
        
        notice_msg = await bot_app.send_message(
            callback_query.message.chat.id, 
            notice_text, 
            reply_markup=notice_keyboard
        )
        to_delete_messages.append(notice_msg)

        # Auto Delete Task (600s = 10 mins)
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

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': out_file,
        'noplaylist': True,
        'max_filesize': 50 * 1024 * 1024,
    }

    file_path = None
    try:
        await safe_edit_text(status_msg, "📥 **Downloading media...**")
        
        loop = asyncio.get_event_loop()
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        file_path = await loop.run_in_executor(None, download)

        if not file_path or not os.path.exists(file_path):
            await safe_edit_text(status_msg, "❌ **Failed to download media.** Check link or restrictions.")
            return

        await safe_edit_text(status_msg, "🚀 **Uploading media...**")
        
        caption = "⚡ **Downloaded Successfully!**\n\n✨ **Bot by:** @developerBYsiam"
        sent_video = await bot_app.send_video(message.chat.id, video=file_path, caption=caption)
        to_delete_messages.append(sent_video)

        await status_msg.delete()

        # ⏱️ 10 Minutes Auto Delete Notice
        notice_text = (
            "⏳ **Auto Delete Notice**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Your link, downloaded video, and this notice will be automatically deleted in **10 minutes**!\n"
            "Please save or forward it now."
        )
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

# 🛠️ Multi-Channel Admin Force Sub Commands
@bot_app.on_message(filters.command("setfsub") & filters.private)
async def set_fsub_command(client, message):
    if message.from_user.id != OWNER_ID: return
    try:
        channels = message.text.split()[1:]
        if not channels:
            await message.reply_text("⚠️ **Format:** `/setfsub -100xxxx -100yyyy`")
            return
        set_fsub_channels(channels)
        await message.reply_text(f"✅ **Set {len(channels)} F-Sub channels successfully!**\n`{', '.join(channels)}`")
    except Exception as e:
        await message.reply_text(f"❌ Error: `{e}`")

@bot_app.on_message(filters.command("addfsub") & filters.private)
async def add_fsub_command(client, message):
    if message.from_user.id != OWNER_ID: return
    try:
        new_ch = message.text.split()[1]
        current = get_fsub_channels()
        if new_ch not in current:
            current.append(new_ch)
            set_fsub_channels(current)
            await message.reply_text(f"✅ Added `{new_ch}` to F-Sub list!")
        else:
            await message.reply_text("⚠️ Channel already in list!")
    except Exception:
        await message.reply_text("⚠️ **Format:** `/addfsub -100xxxxxxx`")

@bot_app.on_message(filters.command("showfsub") & filters.private)
async def show_fsub_command(client, message):
    if message.from_user.id != OWNER_ID: return
    channels = get_fsub_channels()
    if channels:
        await message.reply_text(f"<b>📢 Active F-Sub Channels ({len(channels)}):</b>\n`" + "\n".join(channels) + "`")
    else:
        await message.reply_text("ℹ️ No F-Sub channels currently set.")

@bot_app.on_message(filters.command("offsub") & filters.private)
async def off_fsub_command(client, message):
    if message.from_user.id != OWNER_ID: return
    set_fsub_channels([])
    await message.reply_text("✅ All Force Subscribe channels turned OFF!")

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
