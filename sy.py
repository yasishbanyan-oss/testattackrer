import time
import logging
import random
import asyncio
import json
import os
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- تنظیمات اولیه ---
BOT_TOKEN = "8772627350:AAEcZMYdHY6z3DlnkQv2Cm2eZStrR94IeUk"
OWNER_ID = 6749949992
DB_FILE = "database.json"

# --- دیتابیس پیش‌فرض ---
bot_data = {
    "messages": [],           
    "medias": [],            
    "interval": 10,           
    "is_running": False,      
    "attack_mode": "random",  
    "tag_text": "شخص پدر مرده", 
    "unauth_msg": "به توپم دست نزن", 
    "lock_msg": "کصمادرت اگر لف بدی مادرجنده",
    "saved_users": {},       
    "admins": {
        str(OWNER_ID): {
            "type": "permanent",
            "username": "OWNER",
            "permissions": ["admins", "messages", "commands"]
        }
    },
    "user_logs": {},          
    "history": [],            
    "joined_groups": {}       
}

# حالات FSM
(
    WAITING_FOR_MSG, 
    WAITING_FOR_CUSTOM_TIME, 
    WAITING_FOR_ADMIN_ID, 
    WAITING_FOR_ADMIN_TIME,
    WAITING_FOR_TAG_TEXT,
    WAITING_FOR_UNAUTH_MSG,
    WAITING_FOR_LOCK_MSG,
    WAITING_FOR_MEDIA
) = range(8)

# --- مدیریت دیتابیس ---
def save_db():
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(bot_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Error saving DB: {e}")

def load_db():
    global bot_data
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                bot_data.update(loaded)
        except Exception as e:
            logging.error(f"Error loading DB: {e}")

load_db()

# --- لاگ ۲۴ ساعته ---
def log_event(event_text: str):
    now = time.time()
    bot_data["history"].append({"time": now, "event": event_text})
    bot_data["history"] = [h for h in bot_data["history"] if now - h["time"] <= 86400]
    save_db()

# --- بررسی دسترسی‌ها ---
def is_admin(user_id: int) -> bool:
    uid_str = str(user_id)
    now = time.time()
    to_delete = []
    
    for uid, info in bot_data["admins"].items():
        if info.get("type") == "hourly" and info.get("expires_at", 0) < now:
            to_delete.append(uid)
            
    for uid in to_delete:
        del bot_data["admins"][uid]
        log_event(f"⏰ انقضای دسترسی ادمین ساعتی: {uid}")
    if to_delete:
        save_db()

    return uid_str in bot_data["admins"] or user_id == OWNER_ID

def has_permission(user_id: int, perm: str) -> bool:
    if user_id == OWNER_ID: return True
    if not is_admin(user_id): return False
    return perm in bot_data["admins"][str(user_id)].get("permissions", [])

def estimate_creation_year(user_id: int) -> str:
    if user_id < 100000000: return "2013-2015"
    elif user_id < 250000000: return "2016"
    elif user_id < 500000000: return "2017"
    elif user_id < 800000000: return "2018-2019"
    elif user_id < 1300000000: return "2020-2021"
    elif user_id < 2000000000: return "2022-2023"
    elif user_id < 6000000000: return "2024"
    elif user_id < 7500000000: return "2025"
    else: return "2026"

# --- منوهای شیشه‌ای همراه با قفل پنل ---
def get_main_menu(owner_user_id: int):
    keyboard = [
        [InlineKeyboardButton("🟢 1️⃣ تنظیم پیام‌ها", callback_data=f"menu_set_msg:{owner_user_id}"), InlineKeyboardButton("🔵 🖼 تنظیم مدیا", callback_data=f"menu_set_media:{owner_user_id}")],
        [InlineKeyboardButton("🟡 2️⃣ زمان ارسال", callback_data=f"menu_time:{owner_user_id}"), InlineKeyboardButton("🟣 🏷 کلمه تگ", callback_data=f"menu_tag_text:{owner_user_id}")],
        [InlineKeyboardButton("🔴 💬 متن غیرادمین", callback_data=f"menu_unauth_msg:{owner_user_id}"), InlineKeyboardButton("🛑 🔒 تنظیم پیام قفل", callback_data=f"menu_lock_msg:{owner_user_id}")],
        [InlineKeyboardButton("👥 3️⃣ مدیریت ادمین‌ها", callback_data=f"menu_admins:{owner_user_id}"), InlineKeyboardButton("📖 4️⃣ راهنما", callback_data=f"menu_help:{owner_user_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_attack_mode_menu(owner_user_id: int):
    keyboard = [
        [InlineKeyboardButton("🔵 🎲 تصادفی (Random)", callback_data=f"mode_random:{owner_user_id}")],
        [InlineKeyboardButton("🟢 🔢 ترتیبی (Sequential)", callback_data=f"mode_sequential:{owner_user_id}")],
        [InlineKeyboardButton("🟡 💣 خشاب تک‌پیامی (Single Bomb)", callback_data=f"mode_bomb:{owner_user_id}")],
        [InlineKeyboardButton("🔴 🔒 اتک قفلی (Lock & Mute)", callback_data=f"mode_lock:{owner_user_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_time_menu(owner_user_id: int):
    keyboard = [
        [InlineKeyboardButton("2 ثانیه", callback_data=f"time_2:{owner_user_id}"), InlineKeyboardButton("5 ثانیه", callback_data=f"time_5:{owner_user_id}")],
        [InlineKeyboardButton("10 ثانیه", callback_data=f"time_10:{owner_user_id}"), InlineKeyboardButton("30 ثانیه", callback_data=f"time_30:{owner_user_id}")],
        [InlineKeyboardButton("⏱ دلخواه", callback_data=f"time_custom:{owner_user_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"menu_main:{owner_user_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_menu(owner_user_id: int):
    keyboard = [
        [InlineKeyboardButton("🟢 ➕ افزودن ادمین", callback_data=f"admin_add:{owner_user_id}"), InlineKeyboardButton("🔴 ➖ حذف ادمین", callback_data=f"admin_del:{owner_user_id}")],
        [InlineKeyboardButton("🔵 📋 لیست ادمین‌ها", callback_data=f"admin_list:{owner_user_id}"), InlineKeyboardButton("☣️ ⚠️ پاکسازی همه ادمین‌ها", callback_data=f"admin_delall_confirm:{owner_user_id}")],
        [InlineKeyboardButton("🟡 👑 مالک‌ها", callback_data=f"admin_owners:{owner_user_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"menu_main:{owner_user_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_backup_menu(owner_user_id: int):
    keyboard = [
        [InlineKeyboardButton("🟣 🎬 فقط گیف‌ها", callback_data=f"backup_animation:{owner_user_id}"), InlineKeyboardButton("🔴 🎭 فقط استیکرها", callback_data=f"backup_sticker:{owner_user_id}")],
        [InlineKeyboardButton("🟢 📷 فقط عکس‌ها", callback_data=f"backup_photo:{owner_user_id}"), InlineKeyboardButton("🟡 🎙 فقط ویس‌ها", callback_data=f"backup_voice:{owner_user_id}")],
        [InlineKeyboardButton("🔵 📦 کل دیتابیس (کاملاً یکجا)", callback_data=f"backup_full:{owner_user_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def check_panel_owner(query, owner_user_id: int) -> bool:
    if query.from_user.id != owner_user_id:
        await query.answer("کصخل این پنل برای تو نیست! ادم باش 🤥", show_alert=True)
        return False
    return True

# --- دستور /start ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username_str = f"@{user.username}" if user.username else str(user.id)
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    
    welcome_text = (
        f"سلام {username_str} عزیز! 👋\n"
        f"برای اینکه با ربات کار کنی باید ادمین باشی! اول به آیدی @Anotherger پیام بده ادمینت کنه بعد فعالیت کن!\n\n"
        f"⚙️ جهت فعالیت، دستور /panel را بفرستید."
    )
    await update.message.reply_text(welcome_text, message_thread_id=thread_id)

# --- دستور /panel ---
async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None

    if not is_admin(user_id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"), message_thread_id=thread_id)
        return

    await update.message.reply_text(
        f"👋 به پنل مدیریت ربات خوش آمدید.\n🏷 متن تگ فعلی: {bot_data['tag_text']}\n💬 متن غیرادمین فعلی: {bot_data.get('unauth_msg', 'به توپم دست نزن')}\n🔒 متن اتک قفلی: {bot_data.get('lock_msg', 'کصمادرت اگر لف بدی مادرجنده')}\nلطفاً یک بخش را انتخاب کنید:",
        reply_markup=get_main_menu(user_id),
        message_thread_id=thread_id
    )

# --- مدیریت دکمه‌های اینلاین ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data_parts = query.data.split(":")
    action = data_parts[0]
    owner_user_id = int(data_parts[1]) if len(data_parts) > 1 else query.from_user.id

    if not await check_panel_owner(query, owner_user_id): return

    await query.answer()
    user_id = query.from_user.id

    if action == "menu_main":
        await query.edit_message_text("👋 پنل اصلی مدیریت:", reply_markup=get_main_menu(owner_user_id))

    elif action == "menu_set_msg":
        if not has_permission(user_id, "messages"):
            await query.edit_message_text("❌ شما دسترسی به این بخش را ندارید.", reply_markup=get_main_menu(owner_user_id))
            return
        await query.edit_message_text("📝 پیام‌های متنی خود را ارسال کنید.\nدر پایان دستور /done را ارسال کنید.")
        return WAITING_FOR_MSG

    elif action == "menu_set_media":
        if not has_permission(user_id, "messages"):
            await query.edit_message_text("❌ شما دسترسی به این بخش را ندارید.", reply_markup=get_main_menu(owner_user_id))
            return
        await query.edit_message_text("🖼 عکس، ویس، گیف یا استیکر مورد نظر خود را بفرستید.\nدر پایان دستور /done را ارسال کنید.")
        return WAITING_FOR_MEDIA

    elif action == "menu_tag_text":
        await query.edit_message_text(f"🏷 کلمه تگ فعلی: {bot_data['tag_text']}\n\nلطفاً کلمه جدید برای تگ کردن را بفرستید:")
        return WAITING_FOR_TAG_TEXT

    elif action == "menu_unauth_msg":
        await query.edit_message_text(f"💬 متن فعلی پاسخ به افراد غیرادمین: {bot_data.get('unauth_msg', 'به توپم دست نزن')}\n\nلطفاً متن جدید را بفرستید:")
        return WAITING_FOR_UNAUTH_MSG

    elif action == "menu_lock_msg":
        await query.edit_message_text(f"🔒 متن فعلی اتک قفلی: {bot_data.get('lock_msg', 'کصمادرت اگر لف بدی مادرجنده')}\n\nلطفاً متن جدید را بفرستید:")
        return WAITING_FOR_LOCK_MSG

    elif action == "menu_time":
        await query.edit_message_text(f"⏱ تنظیم زمان ارسال پیام\nزمان فعلی: {bot_data['interval']} ثانیه\nیکی را انتخاب کنید:", reply_markup=get_time_menu(owner_user_id))

    elif action.startswith("time_"):
        val = action.split("_")[1]
        if val == "custom":
            await query.edit_message_text("لطفاً زمان مدنظر خود را بر حسب ثانیه (عدد) وارد کنید:")
            return WAITING_FOR_CUSTOM_TIME
        else:
            sec = int(val)
            bot_data["interval"] = sec
            save_db()
            await query.edit_message_text(f"✅ زمان ارسال روی {sec} ثانیه تنظیم شد.", reply_markup=get_main_menu(owner_user_id))

    elif action.startswith("mode_"):
        mode = action.split("_")[1]
        bot_data["attack_mode"] = mode
        bot_data["is_running"] = True
        save_db()
        
        chat_id = query.message.chat_id
        thread_id = query.message.message_thread_id if query.message.is_topic_message else None
        
        asyncio.create_task(start_auto_sending(chat_id, thread_id, context))
        
        log_event(f"🚀 شروع اتک با حالت {mode} توسط کاربر {user_id}")
        await query.edit_message_text(f"🚀 اتک با حالت **{mode}** و فاصله {bot_data['interval']} ثانیه استارت خورد!")

    elif action == "menu_admins":
        if user_id != OWNER_ID and not has_permission(user_id, "admins"):
            await query.edit_message_text("❌ فقط مالک یا ادمین‌های مجاز دسترسی دارند.", reply_markup=get_main_menu(owner_user_id))
            return
        await query.edit_message_text("👥 بخش مدیریت ادمین‌ها:", reply_markup=get_admin_menu(owner_user_id))

    elif action == "admin_list":
        admin_text = "📋 **لیست ادمین‌های فعلی ربات:**\n\n"
        for aid, ainfo in bot_data["admins"].items():
            uname = ainfo.get("username", "نامشخص")
            if uname != "OWNER" and uname != "نامشخص": uname = f"@{uname}"
            atype = "دائمی" if ainfo.get("type") == "permanent" else "ساعتی"
            admin_text += f"• `{aid}` ({uname}) ➔ {atype}\n"
        await query.edit_message_text(admin_text, parse_mode="Markdown", reply_markup=get_admin_menu(owner_user_id))

    elif action == "admin_delall_confirm":
        kb = [
            [InlineKeyboardButton("✅ بله، پاک کن", callback_data=f"admin_delall_yes:{owner_user_id}")],
            [InlineKeyboardButton("❌ انصراف", callback_data=f"admin_list:{owner_user_id}")]
        ]
        await query.edit_message_text("⚠️ **آیا مطمئن هستید که می‌خواهید تمام ادمین‌های ربات (به جز مالک) رو پاکسازی کنید؟**", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif action == "admin_delall_yes":
        bot_data["admins"] = {
            str(OWNER_ID): {
                "type": "permanent",
                "username": "OWNER",
                "permissions": ["admins", "messages", "commands"]
            }
        }
        save_db()
        log_event("☣️ پاکسازی کامل تمامی ادمین‌های ربات")
        await query.edit_message_text("✅ تمامی ادمین‌ها پاکسازی شدند و فقط مالک اصلی باقی ماند.", reply_markup=get_admin_menu(owner_user_id))

    elif action == "admin_add":
        await query.edit_message_text("لطفاً آیدی عددی ادمین جدید را وارد کنید:")
        return WAITING_FOR_ADMIN_ID

    elif action == "admin_owners":
        await query.edit_message_text(f"👑 مالک ربات:\nآیدی عددی: `{OWNER_ID}`", parse_mode="Markdown", reply_markup=get_admin_menu(owner_user_id))

    elif action.startswith("backup_"):
        b_type = action.split("_")[1]
        save_db()
        
        if b_type == "full":
            await context.bot.send_document(chat_id=query.message.chat_id, document=open(DB_FILE, "rb"), filename="database.json", caption="📦 بکاپ کامل دیتابیس.")
        else:
            filtered = [m for m in bot_data.get("medias", []) if m["type"] == b_type]
            out_file = f"backup_{b_type}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(filtered, f, ensure_ascii=False, indent=4)
            await context.bot.send_document(chat_id=query.message.chat_id, document=open(out_file, "rb"), filename=out_file, caption=f"📦 بکاپ تفکیک‌شده بخش {b_type}")
            if os.path.exists(out_file): os.remove(out_file)

        await query.edit_message_text("✅ بکاپ درخواستی ارسال گردید.")

    elif action.startswith("target_add_"):
        target_uid = action.split("_")[2]
        bot_data["saved_users"][target_uid] = {"username": "Unknown", "custom_tag": None}
        save_db()
        await query.edit_message_text(f"✅ کاربر {target_uid} به لیست سیو شده‌ها اضافه شد.")

    elif action == "menu_help":
        help_text = (
            "📖 **راهنمای جامع ربات اتکر:**\n\n"
            "/panel - باز کردن پنل مدیریت\n"
            "/set ID [Title] - افزودن کاربر با تگ اختصاصی\n"
            "/list - مشاهده افراد سیو شده\n"
            "/listmsg - مشاهده پیام‌ها و مدیاها\n"
            "/del ID - حذف یک فرد\n"
            "/delallsave - پاکسازی کامل افراد\n"
            "/deltext - پاکسازی متون\n"
            "/delmedia - پاکسازی مدیاها\n"
            "/deldata - پاکسازی کامل متون و مدیاها\n"
            "/go - شروع اتک\n"
            "/stop - توقف اتک\n"
            "/recent - گزارش اتفاقات ۲۴ ساعت اخیر\n"
            "/report - گزارش زنده ربات\n"
            "/info - مشخصات کامل کاربر (عمومی)\n"
            "/history_user ID - تاریخچه پیام‌های ثبت‌شده\n"
            "/backup - دریافت منوی بکاپ\n"
            "/restore - ریستور بکاپ متنی/دیتابیس\n"
            "/status - وضعیت فنی ربات\n"
        )
        await query.edit_message_text(help_text, parse_mode="Markdown", reply_markup=get_main_menu(owner_user_id))

# --- دریافت پیام‌های FSM ---
async def collect_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data["messages"].append(update.message.text)
    save_db()
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    await update.message.reply_text(f"✅ پیام ذخیره شد. (تعداد: {len(bot_data['messages'])})\nپیام بعدی را بفرستید یا /done را بزنید.", message_thread_id=thread_id)
    return WAITING_FOR_MSG

async def collect_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    media_item = None
    thread_id = msg.message_thread_id if msg.is_topic_message else None
    
    if msg.photo: media_item = {"type": "photo", "file_id": msg.photo[-1].file_id, "caption": msg.caption or ""}
    elif msg.voice: media_item = {"type": "voice", "file_id": msg.voice.file_id}
    elif msg.animation: media_item = {"type": "animation", "file_id": msg.animation.file_id, "caption": msg.caption or ""}
    elif msg.sticker: media_item = {"type": "sticker", "file_id": msg.sticker.file_id}

    if media_item:
        bot_data["medias"].append(media_item)
        save_db()
        await update.message.reply_text(f"✅ مدیا ذخیره شد! (تعداد: {len(bot_data['medias'])})\nمدیای بعدی را بفرستید یا /done را بزنید.", message_thread_id=thread_id)
    return WAITING_FOR_MEDIA

async def done_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    await update.message.reply_text("✅ ثبت با موفقیت تمام شد.", reply_markup=get_main_menu(update.effective_user.id), message_thread_id=thread_id)
    return ConversationHandler.END

async def receive_tag_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_tag = update.message.text.strip()
    bot_data["tag_text"] = new_tag
    save_db()
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    await update.message.reply_text(f"✅ کلمه تگ روی {new_tag} تنظیم شد.", reply_markup=get_main_menu(update.effective_user.id), message_thread_id=thread_id)
    return ConversationHandler.END

async def receive_unauth_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_unauth = update.message.text.strip()
    bot_data["unauth_msg"] = new_unauth
    save_db()
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    await update.message.reply_text(f"✅ متن پاسخ به غیرادمین‌ها روی {new_unauth} تنظیم شد.", reply_markup=get_main_menu(update.effective_user.id), message_thread_id=thread_id)
    return ConversationHandler.END

async def receive_lock_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_lock = update.message.text.strip()
    bot_data["lock_msg"] = new_lock
    save_db()
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    await update.message.reply_text(f"✅ متن اتک قفلی روی {new_lock} تنظیم شد.", reply_markup=get_main_menu(update.effective_user.id), message_thread_id=thread_id)
    return ConversationHandler.END

async def receive_custom_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if text.isdigit():
        sec = int(text)
        bot_data["interval"] = sec
        save_db()
        await update.message.reply_text(f"✅ زمان ارسال روی {sec} ثانیه تنظیم شد.", reply_markup=get_main_menu(update.effective_user.id), message_thread_id=thread_id)
        return ConversationHandler.END
    return WAITING_FOR_CUSTOM_TIME

async def receive_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if text.isdigit():
        new_admin_id = int(text)
        fetched_username = "نامشخص"
        try:
            chat_info = await context.bot.get_chat(new_admin_id)
            if chat_info.username: fetched_username = chat_info.username
            elif chat_info.first_name: fetched_username = chat_info.first_name
        except Exception: pass

        bot_data["admins"][str(new_admin_id)] = {
            "type": "permanent",
            "username": fetched_username,
            "permissions": ["admins", "messages", "commands"]
        }
        save_db()
        await update.message.reply_text(f"✅ ادمین جدید با آیدی `{new_admin_id}` و نام `{fetched_username}` ثبت شد.", parse_mode="Markdown", reply_markup=get_admin_menu(update.effective_user.id), message_thread_id=thread_id)
        return ConversationHandler.END
    return WAITING_FOR_ADMIN_ID

# --- دستورات اصلی ربات ---
async def set_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"), message_thread_id=thread_id)
        return

    added = []
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        uid = str(target_user.id)
        custom_tag = " ".join(context.args) if context.args else None
        bot_data["saved_users"][uid] = {"username": target_user.username or "NoUsername", "custom_tag": custom_tag}
        added.append(f"{uid} (تگ: {custom_tag or 'پیش‌فرض'})")
    elif context.args:
        uid = context.args[0]
        custom_tag = " ".join(context.args[1:]) if len(context.args) > 1 else None
        bot_data["saved_users"][uid] = {"username": "Unknown", "custom_tag": custom_tag}
        added.append(f"{uid} (تگ: {custom_tag or 'پیش‌فرض'})")

    if added:
        save_db()
        await update.message.reply_text(f"✅ کاربر(های) زیر ذخیره شدند:\n" + "\n".join(added), message_thread_id=thread_id)

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id): return

    users = bot_data["saved_users"]
    if not users:
        await update.message.reply_text("لیست سیو شده‌ها خالی است.", message_thread_id=thread_id)
    else:
        text = "📋 **لیست کاربران تنظیم‌شده:**\n\n"
        for uid, info in users.items():
            uname = f"@{info['username']}" if info.get('username') != "Unknown" else "بدون یوزرنیم"
            ctag = info.get('custom_tag') or 'پیش‌فرض'
            text += f"• `{uid}` ({uname}) ➔ 🏷 لقب: {ctag}\n"
        await update.message.reply_text(text, parse_mode="Markdown", message_thread_id=thread_id)

async def listmsg_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id): return

    messages = bot_data.get("messages", [])
    medias = bot_data.get("medias", [])
    text = f"📝 **خشاب جاری:**\n💬 متون: {len(messages)} عدد\n🖼 مدیاها: {len(medias)} عدد"
    await update.message.reply_text(text, parse_mode="Markdown", message_thread_id=thread_id)

async def del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id): return
    target_id = context.args[0] if context.args else None
    if target_id and target_id in bot_data["saved_users"]:
        del bot_data["saved_users"][target_id]
        save_db()
        await update.message.reply_text(f"❌ کاربر {target_id} حذف شد.", message_thread_id=thread_id)

async def delallsave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id): return
    bot_data["saved_users"].clear()
    save_db()
    await update.message.reply_text("🧹 تمامی افراد پاکسازی شدند.", message_thread_id=thread_id)

async def deltext_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id): return
    bot_data["messages"].clear()
    save_db()
    await update.message.reply_text("🗑 تمام پیام‌های متنی خشاب پاک شدند.", message_thread_id=thread_id)

async def delmedia_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id): return
    bot_data["medias"].clear()
    save_db()
    await update.message.reply_text("🗑 تمام مدیاهای خشاب پاک شدند.", message_thread_id=thread_id)

async def deldata_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id): return
    bot_data["messages"].clear()
    bot_data["medias"].clear()
    save_db()
    await update.message.reply_text("🗑 تمامی متون و مدیاها یکجا پاکسازی شدند.", message_thread_id=thread_id)

async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    target_user = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    
    creation_year = estimate_creation_year(target_user.id)
    username_str = f"@{target_user.username}" if target_user.username else "ندارد"
    
    info_text = (
        f"📊 **اطلاعات شناسنامه‌ای کاربر:**\n\n"
        f"👤 نام: {target_user.full_name}\n"
        f"🆔 یوزرنیم: {username_str}\n"
        f"🔢 آیدی عددی: `{target_user.id}`\n"
        f"📅 تخمین سال ساخت اکانت: {creation_year}\n"
    )

    kb = [
        [InlineKeyboardButton("➕ افزودن به لیست تارگت", callback_data=f"target_add_{target_user.id}:{update.effective_user.id}")],
        [InlineKeyboardButton("❌ انصراف", callback_data=f"menu_main:{update.effective_user.id}")]
    ]
    
    try:
        photos = await context.bot.get_user_profile_photos(target_user.id, limit=1)
        if photos.total_count > 0:
            await update.message.reply_photo(photo=photos.photos[0][-1].file_id, caption=info_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb), message_thread_id=thread_id)
            return
    except Exception: pass

    await update.message.reply_text(info_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb), message_thread_id=thread_id)

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if update.effective_user.id != OWNER_ID: return
    
    groups_list_text = "👥 **گروه‌های فعال ربات:**\n"
    for gid, gtitle in bot_data.get("joined_groups", {}).items():
        groups_list_text += f"• {gtitle} (`{gid}`)\n"

    rep = (
        f"📊 **گزارش زنده ربات اتکر:**\n\n"
        f"🚀 وضعیت اتک: {'فعال' if bot_data['is_running'] else 'متوقف'}\n"
        f"🎯 تعداد تارگت‌ها: {len(bot_data['saved_users'])}\n"
        f"💬 متون خشاب: {len(bot_data['messages'])}\n"
        f"🖼 مدیاهای خشاب: {len(bot_data['medias'])}\n"
        f"👥 ادمین‌ها: {len(bot_data['admins'])}\n\n"
        f"{groups_list_text}"
    )
    await update.message.reply_text(rep, parse_mode="Markdown", message_thread_id=thread_id)

# --- موتور اتک اتوماتیک ---
async def start_auto_sending(chat_id: int, thread_id: int, context: ContextTypes.DEFAULT_TYPE):
    seq_index = 0
    default_tag = bot_data.get("tag_text", "شخص پدر مرده")

    if bot_data.get("attack_mode") == "lock":
        for uid in bot_data["saved_users"].keys():
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=int(uid),
                    permissions=ChatPermissions(can_send_messages=False)
                )
            except Exception as e: logging.error(f"Error muting {uid}: {e}")

        lock_text = bot_data.get("lock_msg", "کصمادرت اگر لف بدی مادرجنده")
        tags_list = [f"[{uinfo.get('custom_tag') or default_tag}](tg://user?id={uid})" for uid, uinfo in bot_data["saved_users"].items()]
        if tags_list: lock_text += "\n\n" + " ".join(tags_list)
        await context.bot.send_message(chat_id=chat_id, text=lock_text, parse_mode="Markdown", message_thread_id=thread_id)

    while bot_data["is_running"]:
        messages = bot_data["messages"]
        medias = bot_data["medias"]
        mode = bot_data.get("attack_mode", "random")

        tags_list = [f"[{uinfo.get('custom_tag') or default_tag}](tg://user?id={uid})" for uid, uinfo in bot_data["saved_users"].items()]
        tags_text = " ".join(tags_list)

        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing", message_thread_id=thread_id)

            if mode == "bomb":
                if messages:
                    bomb_text = "\n\n".join(messages)
                    if tags_text: bomb_text += f"\n\n{tags_text}"
                    await context.bot.send_message(chat_id=chat_id, text=bomb_text, parse_mode="Markdown", message_thread_id=thread_id)
                photos = [m for m in medias if m["type"] == "photo"]
                if photos:
                    media_group = [InputMediaPhoto(media=p["file_id"]) for p in photos[:10]]
                    await context.bot.send_media_group(chat_id=chat_id, media=media_group, message_thread_id=thread_id)

            elif mode == "sequential":
                combined = messages + medias
                if combined:
                    item = combined[seq_index % len(combined)]
                    if isinstance(item, str):
                        msg_txt = item + (f"\n\n{tags_text}" if tags_text else "")
                        await context.bot.send_message(chat_id=chat_id, text=msg_txt, parse_mode="Markdown", message_thread_id=thread_id)
                    elif isinstance(item, dict):
                        m_type, f_id = item["type"], item["file_id"]
                        if m_type == "photo": await context.bot.send_photo(chat_id=chat_id, photo=f_id, caption=tags_text, parse_mode="Markdown", message_thread_id=thread_id)
                        elif m_type == "animation": await context.bot.send_animation(chat_id=chat_id, animation=f_id, caption=tags_text, parse_mode="Markdown", message_thread_id=thread_id)
                        elif m_type == "voice": await context.bot.send_voice(chat_id=chat_id, voice=f_id, message_thread_id=thread_id)
                        elif m_type == "sticker": await context.bot.send_sticker(chat_id=chat_id, sticker=f_id, message_thread_id=thread_id)
                    seq_index += 1

            else:
                if messages:
                    rand_msg = random.choice(messages)
                    if tags_text: rand_msg += f"\n\n{tags_text}"
                    await context.bot.send_message(chat_id=chat_id, text=rand_msg, parse_mode="Markdown", message_thread_id=thread_id)

        except Exception as e: logging.error(f"Error in auto send: {e}")
        await asyncio.sleep(bot_data["interval"])

async def go_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text("⚙️ حالت ارسال پیام را انتخاب کنید:", reply_markup=get_attack_mode_menu(update.effective_user.id), message_thread_id=thread_id)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id): return
    bot_data["is_running"] = False
    save_db()
    await update.message.reply_text("🛑 ارسال خودکار پیام‌ها متوقف شد.", message_thread_id=thread_id)

async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text("📦 نوع فایل بکاپ مورد نظر را انتخاب کنید:", reply_markup=get_backup_menu(update.effective_user.id), message_thread_id=thread_id)

async def recent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    now = time.time()
    recent_logs = [h for h in bot_data["history"] if now - h["time"] <= 86400]
    text = "📜 **گزارش اتفاقات ۲۴ ساعت اخیر:**\n\n"
    for log in reversed(recent_logs):
        time_str = time.strftime('%H:%M:%S', time.localtime(log['time']))
        text += f"⏱ [{time_str}] {log['event']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def restore_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if update.effective_user.id != OWNER_ID: return

    msg = update.message
    if msg.reply_to_message and msg.reply_to_message.document:
        doc = msg.reply_to_message.document
        file_name = doc.file_name.lower()
        file = await context.bot.get_file(doc.file_id)
        download_path = await file.download_to_drive()

        if file_name.endswith(".txt"):
            with open(download_path, "r", encoding="utf-8") as f: content = f.read()
            words = content.split()
            bot_data["messages"].extend(words)
            save_db()
            await update.message.reply_text(f"✅ تعداد {len(words)} کلمه/پیام به خشاب اضافه شدند!", message_thread_id=thread_id)
        elif file_name.endswith(".json"):
            await download_path.replace(DB_FILE)
            load_db()
            await update.message.reply_text("✅ دیتابیس کامل ریستور گردید!", message_thread_id=thread_id)

        if os.path.exists(download_path): os.remove(download_path)

async def history_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message.is_topic_message else None
    if not is_admin(update.effective_user.id) or not context.args: return
    uid = context.args[0]
    logs = bot_data.get("user_logs", {}).get(uid, [])
    text = f"📜 **تاریخچه پیام‌های تارگت {uid}:**\n\n"
    for l in logs[-15:]: text += f"⏱ [{l['time']}] {l['text']}\n"
    await update.message.reply_text(text, message_thread_id=thread_id)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    start_time = time.time()
    msg = await update.message.reply_text("در حال محاسبه پینگ...")
    ping = round((time.time() - start_time) * 1000, 2)

    status_text = (
        f"📊 **وضعیت ربات اتکر:**\n\n"
        f"⚡️ پینگ ربات: {ping}ms\n"
        f"👥 ادمین‌ها: {len(bot_data['admins'])}\n"
        f"🎯 تارگت‌ها: {len(bot_data['saved_users'])}\n"
        f"💬 پیام‌ها: {len(bot_data['messages'])}\n"
        f"🖼 مدیاها: {len(bot_data['medias'])}\n"
    )
    await msg.edit_text(status_text, parse_mode="Markdown")

# --- سنسور خروج اعضا و لاگ ---
async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg: return

    if msg.chat.type in ["group", "supergroup"]:
        bot_data.setdefault("joined_groups", {})[str(msg.chat.id)] = msg.chat.title
        save_db()

    if msg.left_chat_member:
        left_user = msg.left_chat_member
        uid_str = str(left_user.id)
        if uid_str in bot_data["saved_users"]:
            thread_id = msg.message_thread_id if msg.is_topic_message else None
            uname = f"@{left_user.username}" if left_user.username else left_user.full_name
            alert = f"📢 شخص {uname} با اینکه فحش گذاشته شد لف داد و بی‌غیرتی خودش رو ثابت کرد! 🤣"
            await context.bot.send_message(chat_id=msg.chat_id, text=alert, message_thread_id=thread_id)

    if msg.from_user and str(msg.from_user.id) in bot_data["saved_users"]:
        uid_str = str(msg.from_user.id)
        bot_data.setdefault("user_logs", {}).setdefault(uid_str, []).append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "text": msg.text or "[Media/Other]"
        })
        save_db()

# --- وب‌سرور aiohttp ---
async def handle_ping(request): return web.Response(text="Bot is Alive!")

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("panel", panel_cmd))

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback)],
        states={
            WAITING_FOR_MSG: [CommandHandler("done", done_messages), MessageHandler(filters.TEXT & ~filters.COMMAND, collect_messages)],
            WAITING_FOR_MEDIA: [CommandHandler("done", done_messages), MessageHandler((filters.PHOTO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL) & ~filters.COMMAND, collect_media)],
            WAITING_FOR_TAG_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tag_text)],
            WAITING_FOR_UNAUTH_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_unauth_msg)],
            WAITING_FOR_LOCK_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_lock_msg)],
            WAITING_FOR_CUSTOM_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_time)],
            WAITING_FOR_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_id)],
        },
        fallbacks=[CallbackQueryHandler(handle_callback)],
        allow_reentry=True,
        per_message=False
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("set", set_user_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("listmsg", listmsg_cmd))
    app.add_handler(CommandHandler("del", del_cmd))
    app.add_handler(CommandHandler("delallsave", delallsave_cmd))
    app.add_handler(CommandHandler("deltext", deltext_cmd))
    app.add_handler(CommandHandler("delmedia", delmedia_cmd))
    app.add_handler(CommandHandler("deldata", deldata_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("go", go_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("recent", recent_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("backup", backup_cmd))
    app.add_handler(CommandHandler("restore", restore_cmd))
    app.add_handler(CommandHandler("history_user", history_user_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    
    app.add_handler(MessageHandler(filters.ALL, track_chats))

    web_app = web.Application()
    web_app.router.add_get('/', handle_ping)
    runner = web.AppRunner(web_app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    print("ربات اتکر کاملاً آنلاین شد...")

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.sleep(1)
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
