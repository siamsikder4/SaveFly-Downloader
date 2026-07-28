import os
import time
import asyncio
import sqlite3
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

# 👑 Owner / Admin ID Verification
OWNER_ID = int(os.environ.get("OWNER_ID", "6142774415"))  

# Database Setup for Bot Settings (Single F-Sub)
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

# Force Sub DB Helper Functions (Only 1 Channel Allowed)
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

# 🔒 Fixed & Robust Check Force Sub Channel
async def check_force_sub(client, user_id):
    channels = get_fsub_channels()
    if not channels or user_id == OWNER_ID:
        return True, []

    unjoined = []
    for ch in channels:
        try:
            ch_id = int(ch) if (ch.startswith("-") or ch.isdigit()) else ch
            member = await client.get_chat_member(ch_id, user_id)
            
            # Convert status to lower string for both Enum & String support
            st = str(member.status).lower()
            if not ("member" in st or "administrator" in st or "creator" in st or "owner" in st):
                unjoined.append(ch)
        except Exception as e:
            print(f"FSub Check Error ({ch}): {e}")
            unjoined.append(ch)

    return (len(unjoined) == 0), unjoined

# Build Join Keyboard for Unjoined Channels
async def build_fsub_keyboard(client, unjoined_channels):
    buttons = []
    for idx, ch in enumerate(unjoined_channels, 1):
        try:
            ch_id = int(ch) if (ch.startswith("-") or ch.isdigit()) else ch
            chat = await client.get_chat(ch_id)
            invite_link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else "https://t.me/")
            title = chat.title or f"Channel"
        except Exception:
            invite_link = "https://t.me/"
            title = f"Channel"
        buttons.append([InlineKeyboardButton(f"📢 Join {title}", url=invite_link)])
    
    buttons.append([InlineKeyboardButton("🔄 Verify & Continue", callback_data="check_fsub_again")])
    return InlineKeyboardMarkup(buttons)

# 📩 Notify Admin About User Request
async def notify_admin_user_link(user, url):
    try:
        user_id = user.id
        first_name = user.first_name or "User"
        username = f"@{user.username}" if user.username else "No Username"
        
        log_text = (
            f"📥 **New Download Request!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Name:** {first_name}\n"
            f"🆔 **User ID:** `<code>{user_id}</code>`\n"
            f"🏷️ **Username:** {username}\n"
            f"🔗 **Link:** {url}"
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
    user_id = message.from_user.id
    is_joined, unjoined = await check_force_sub(client, user_id)

    if not is_joined:
        keyboard = await build_fsub_keyboard(client, unjoined)
        await message.reply_text(
            "⚠️ **বট ব্যবহার করতে আপনাকে আমাদের চ্যানেলে জয়েন করতে হবে!**\n\n"
            "জয়েন করার পর **'🔄 Verify & Continue'** বাটনে ক্লিক করুন।",
            reply_markup=keyboard
        )
        return

    welcome_text = (
        "✨ **Welcome to Downloader Bot!** ✨\n\n"
        "🔗 Send me any link from **YouTube, Facebook, Instagram, TikTok, Twitter, or Pinterest** to download directly!\n\n"
        "👨‍💻 **Developer:** @developerBYsiam"
    )
    await message.reply_text(welcome_text, reply_markup=reply_markup_ui)

# 🔄 Strictly Verification Callback Query Handler
@bot_app.on_callback_query(filters.regex("^check_fsub_again$"))
async def fsub_callback(client, callback_query):
    user_id = callback_query.from_user.id
    is_joined, unjoined = await check_force_sub(client, user_id)

    if is_joined:
        await callback_query.answer("✅ ভেরিফিকেশন সফল হয়েছে!", show_alert=True)
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        await callback_query.message.reply_text(
            "🎉 **ভেরিফিকেশন সম্পন্ন হয়েছে!**\n\n"
            "এখন যেকোনো ভিডিওর লিংক পাঠান।",
            reply_markup=reply_markup_ui
        )
    else:
        await callback_query.answer("❌ আপনি এখনো চ্যানলে জয়েন করেননি! জয়েন করে চেষ্টা করুন।", show_alert=True)
        keyboard = await build_fsub_keyboard(client, unjoined)
        await safe_edit_text(
            callback_query.message,
            "⚠️ **ভেরিফিকেশন ব্যর্থ হয়েছে!**\n\n"
            "বট ব্যবহার করতে চ্যানেলে জয়েন আবশ্যক। জয়েন করে '🔄 Verify & Continue' বাটনে ক্লিক করুন।",
            reply_markup=keyboard
        )

# 📢 1. EASY F-SUB VIA FORWARDED MESSAGE (REPLACES OLD CHANNEL)
@bot_app.on_message(filters.private & filters.forwarded)
async def handle_forward_fsub(client, message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        return

    ch_id = None
    ch_title = None

    if message.forward_from_chat:
        ch_id = str(message.forward_from_chat.id)
        ch_title = message.forward_from_chat.title or "Channel"
    elif message.forward_from:
        ch_id = str(message.forward_from.id)
        ch_title = message.forward_from.first_name or "Channel"

    if ch_id:
        # 🔄 আগের চ্যানেল মুছে নতুন ১টি চ্যানেল সেট করা হচ্ছে
        set_fsub_channels([ch_id])
        await message.reply_text(
            f"✅ **নতুন F-Sub চ্যানেল সেট করা হয়েছে! (আগেরটি রিমুভড)**\n\n"
            f"📌 **নাম:** `{ch_title}`\n"
            f"🆔 **আইডি:** `{ch_id}`"
        )
    else:
        await message.reply_text("❌ চ্যানেল আইডি নেওয়া যায়নি! কমান্ড দিয়ে চেষ্টা করুন: `/addfsub @channelusername`")

# Main Handler for Text Buttons and Links
@bot_app.on_message(filters.text & filters.private & ~filters.command(["start", "setfsub", "addfsub", "delfsub", "clearfsub", "offsub", "showfsub"]))
async def main_text_handler(client, message):
    text = message.text.strip()
    user_id = message.from_user.id

    is_joined, unjoined = await check_force_sub(client, user_id)
    if not is_joined:
        keyboard = await build_fsub_keyboard(client, unjoined)
        await message.reply_text("⚠️ **বট ব্যবহার করতে আপনাকে আগে আমাদের চ্যানেলে জয়েন করতে হবে!**", reply_markup=keyboard)
        return

    if text == "ℹ️ Supported Platforms":
        platforms_text = (
            "<b>📱 SUPPORTED PLATFORMS:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "▶️ **YouTube** (Direct Fast Download)\n"
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
        # 📩 Admin (Saved Messages)-এ ইউজারের আইডি সহ লিংক সেন্ড করা
        asyncio.create_task(notify_admin_user_link(message.from_user, text))
        
        await process_direct_social_link(client, message, text)

# Direct Downloader for YouTube and All Social Media Links
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
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
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

# 📢 EASY ADMIN CHANNEL MANAGEMENT COMMANDS
@bot_app.on_message(filters.command("addfsub") & filters.private)
async def add_fsub_command(client, message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        return

    try:
        input_data = message.text.split()[1].strip()
        chat = await client.get_chat(input_data)
        ch_id = str(chat.id)
        
        # 🔄 আগের চ্যানেল রিমুভ করে নতুন ১টি সেট করা হচ্ছে
        set_fsub_channels([ch_id])
        await message.reply_text(f"✅ **`{chat.title}`** (`{ch_id}`) নতুন F-Sub চ্যানেল হিসেবে সেট করা হয়েছে! (আগেরটি রিমুভড)")
    except Exception as e:
        await message.reply_text(f"⚠️ **ফরমেট:** `/addfsub @channelusername` বা `/addfsub -100xxxxxxx`\nError: `{e}`")

@bot_app.on_message(filters.command("showfsub") & filters.private)
async def show_fsub_command(client, message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        return

    channels = get_fsub_channels()
    if channels:
        text = f"<b>📢 বর্তমান F-Sub চ্যানেল:</b>\n\n"
        for idx, ch in enumerate(channels, 1):
            try:
                ch_id = int(ch) if (ch.startswith("-") or ch.isdigit()) else ch
                chat = await client.get_chat(ch_id)
                text += f"📌 **{chat.title}** (<code>{ch}</code>)\n"
            except Exception:
                text += f"📌 অজানা চ্যানেল (<code>{ch}</code>)\n"
        await message.reply_text(text)
    else:
        await message.reply_text("ℹ️ বর্তমানে কোনো F-Sub চ্যানেল সেট করা নেই।")

@bot_app.on_message(filters.command(["clearfsub", "offsub"]) & filters.private)
async def off_fsub_command(client, message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        return

    set_fsub_channels([])
    await message.reply_text("🧹 **F-Sub চ্যানেল বন্ধ/রিমুভ করা হয়েছে!**")

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
    loop.run_until_complete(main())
