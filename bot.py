import os
import sqlite3
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==================== CONFIG (Environment Variables) ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
# ========================================================================

if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN environment variable is required.")
if not ADMIN_ID:
    raise SystemExit("❌ ADMIN_ID environment variable is required.")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DB_FILE = os.environ.get("DB_FILE", "store.db")


# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            content_type TEXT NOT NULL,
            content TEXT NOT NULL,
            caption TEXT
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE NOT NULL,
            title TEXT,
            invite_link TEXT NOT NULL
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS force_join (
            user_id INTEGER PRIMARY KEY,
            verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


# ---- Items ----
def add_item(name, content_type, content, caption=""):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO items (name, content_type, content, caption) VALUES (?, ?, ?, ?)",
            (name.lower(), content_type, content, caption),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def update_item(name, content_type, content, caption=""):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "UPDATE items SET content_type=?, content=?, caption=? WHERE name=?",
        (content_type, content, caption, name.lower()),
    )
    updated = c.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_item(name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT content_type, content, caption FROM items WHERE name = ?",
        (name.lower(),),
    )
    row = c.fetchone()
    conn.close()
    return row


def delete_item(name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM items WHERE name = ?", (name.lower(),))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def list_items():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, content_type FROM items ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return rows


def count_items():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM items")
    n = c.fetchone()[0]
    conn.close()
    return n


# ---- Channels ----
def add_channel(chat_id, title, invite_link):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO channels (chat_id, title, invite_link) VALUES (?, ?, ?)",
            (str(chat_id), title, invite_link),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_channel(chat_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM channels WHERE chat_id = ?", (str(chat_id),))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def list_channels():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT chat_id, title, invite_link FROM channels")
    rows = c.fetchall()
    conn.close()
    return rows


# ---- Users ----
def save_user(user):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
        (user.id, user.username or "", user.first_name or ""),
    )
    conn.commit()
    conn.close()


def count_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    n = c.fetchone()[0]
    conn.close()
    return n


def all_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


# ---- Settings ----
def set_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


# ==================== HELPERS ====================
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


async def check_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list:
    """Return list of channels user has NOT joined."""
    missing = []
    for chat_id, title, link in list_channels():
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status not in ("member", "administrator", "creator"):
                missing.append((chat_id, title, link))
        except Exception as e:
            logger.warning(f"Membership check failed for {chat_id}: {e}")
            missing.append((chat_id, title, link))
    return missing


def join_keyboard(missing):
    buttons = []
    for _, title, link in missing:
        buttons.append([InlineKeyboardButton(f"📢 Join {title}", url=link)])
    buttons.append([InlineKeyboardButton("✅ I Joined", callback_data="check_join")])
    return InlineKeyboardMarkup(buttons)


def admin_panel_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📦 Items", callback_data="admin_items"),
                InlineKeyboardButton("📢 Channels", callback_data="admin_channels"),
            ],
            [
                InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
                InlineKeyboardButton("📣 Broadcast", callback_data="admin_broadcast"),
            ],
            [
                InlineKeyboardButton("ℹ️ Help", callback_data="admin_help"),
            ],
        ]
    )


def channels_manage_keyboard():
    rows = [[InlineKeyboardButton("➕ Add Channel/Group", callback_data="add_channel")]]
    for chat_id, title, _ in list_channels():
        rows.append(
            [
                InlineKeyboardButton(
                    f"🗑 Remove {title}", callback_data=f"del_channel:{chat_id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_back")])
    return InlineKeyboardMarkup(rows)


# ==================== COMMANDS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    if is_admin(user.id):
        text = (
            f"👋 Welcome Admin {user.first_name}!\n\n"
            "Use the panel below to manage your bot:"
        )
        await update.message.reply_text(
            text, reply_markup=admin_panel_keyboard()
        )
        return

    missing = await check_membership(context, user.id)
    if missing:
        await update.message.reply_text(
            "🔒 To use this bot, please join our channel(s) first:",
            reply_markup=join_keyboard(missing),
        )
        return

    await update.message.reply_text(
        "👋 Hello! Send me the *name* of the item you want to get.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        text = (
            "*👑 Admin Commands*\n\n"
            "• `/panel` — Open admin panel\n"
            "• `/add <name> <text>` — Store text/link\n"
            "• Reply to a file with `/add <name>` — Store file\n"
            "• `/update <name>` — Replace existing item\n"
            "• `/remove <name>` — Delete item\n"
            "• `/list` — List all items\n"
            "• `/addchannel <link>` — Add force-join channel\n"
            "• `/removechannel <chat_id>` — Remove channel\n"
            "• `/channels` — List force-join channels\n"
            "• `/stats` — Bot statistics\n"
            "• `/broadcast <msg>` — Broadcast to all users\n"
            "• `/cancel` — Cancel current operation"
        )
    else:
        text = (
            "Send the *name* of the item you want to get.\n"
            "Example: `/get myfile` or just type `myfile`"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "👑 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_panel_keyboard(),
    )


# ==================== ADMIN: ADD ITEM ====================
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "Usage:\n"
            "• `/add <name> <text/link>` for text or link\n"
            "• Reply to a file with `/add <name>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    name = context.args[0]
    replied = update.message.reply_to_message

    if replied:
        file_id, content_type = extract_file(replied)
        if not file_id:
            await update.message.reply_text("❌ Unsupported file type.")
            return
        caption = replied.caption or ""
        ok = add_item(name, content_type, file_id, caption)
        if ok:
            await update.message.reply_text(
                f"✅ Stored file as `{name}`", parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"❌ Name `{name}` already exists. Use `/update {name}` to replace.",
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Provide text or link after the name.")
        return

    content = " ".join(context.args[1:])
    ok = add_item(name, "text", content)
    if ok:
        await update.message.reply_text(
            f"✅ Stored text/link as `{name}`", parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"❌ Name `{name}` already exists. Use `/update {name}` to replace.",
            parse_mode=ParseMode.MARKDOWN,
        )


def extract_file(message):
    """Return (file_id, content_type) for supported media."""
    if message.document:
        return message.document.file_id, "document"
    if message.video:
        return message.video.file_id, "video"
    if message.audio:
        return message.audio.file_id, "audio"
    if message.photo:
        return message.photo[-1].file_id, "photo"
    if message.voice:
        return message.voice.file_id, "voice"
    if message.video_note:
        return message.video_note.file_id, "video_note"
    if message.animation:
        return message.animation.file_id, "animation"
    if message.sticker:
        return message.sticker.file_id, "sticker"
    return None, None


async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/update <name>` (reply to a file) or `/update <name> <new text>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    name = context.args[0]
    if not get_item(name):
        await update.message.reply_text(
            f"❌ No item named `{name}`", parse_mode=ParseMode.MARKDOWN
        )
        return

    replied = update.message.reply_to_message
    if replied:
        file_id, content_type = extract_file(replied)
        if not file_id:
            await update.message.reply_text("❌ Unsupported file type.")
            return
        caption = replied.caption or ""
        update_item(name, content_type, file_id, caption)
        await update.message.reply_text(
            f"♻️ Updated file `{name}`", parse_mode=ParseMode.MARKDOWN
        )
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Provide new text or reply to a file.")
        return

    content = " ".join(context.args[1:])
    update_item(name, "text", content)
    await update.message.reply_text(
        f"♻️ Updated text `{name}`", parse_mode=ParseMode.MARKDOWN
    )


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/remove <name>`", parse_mode=ParseMode.MARKDOWN
        )
        return
    name = context.args[0]
    if delete_item(name):
        await update.message.reply_text(
            f"🗑 Deleted `{name}`", parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"❌ No item named `{name}`", parse_mode=ParseMode.MARKDOWN
        )


async def listall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    items = list_items()
    if not items:
        await update.message.reply_text("📭 No items stored yet.")
        return
    lines = [f"• `{n}` — {t}" for n, t in items]
    await update.message.reply_text(
        "*📦 Stored items:*\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN
    )


# ==================== ADMIN: CHANNELS ====================
async def addchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    # If replying to a message that is forwarded from a channel
    replied = update.message.reply_to_message
    if replied and replied.forward_from_chat and replied.forward_from_chat.type in ("channel", "supergroup"):
        chat = replied.forward_from_chat
        try:
            chat_full = await context.bot.get_chat(chat.id)
            invite = chat_full.invite_link or (
                f"https://t.me/{chat.username}" if chat.username else None
            )
            if not invite:
                invite = await context.bot.export_chat_invite_link(chat.id)
            ok = add_channel(chat.id, chat.title, invite)
            if ok:
                await update.message.reply_text(f"✅ Added channel: {chat.title}")
            else:
                await update.message.reply_text("⚠️ Channel already added.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
        return

    if not context.args:
        await update.message.reply_text(
            "*Add channel/group:*\n"
            "1) `/addchannel https://t.me/yourchannel`\n"
            "2) Or forward any message from the channel and reply `/addchannel`\n\n"
            "⚠️ Bot must be admin in that channel/group.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    link = context.args[0]
    username = link.rstrip("/").split("/")[-1]
    if username.startswith("+"):
        # Private invite link — cannot resolve; use forwarded method
        await update.message.reply_text(
            "⚠️ Private invite link detected. Please forward a message from that channel "
            "and reply `/addchannel` so bot can detect the chat ID.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    chat_identifier = f"@{username}" if not username.startswith("@") else username
    try:
        chat = await context.bot.get_chat(chat_identifier)
        try:
            invite = chat.invite_link
            if not invite and chat.username:
                invite = f"https://t.me/{chat.username}"
            if not invite:
                invite = await context.bot.export_chat_invite_link(chat.id)
        except Exception:
            invite = link

        ok = add_channel(chat.id, chat.title, invite)
        if ok:
            await update.message.reply_text(
                f"✅ Added: *{chat.title}*\nID: `{chat.id}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text("⚠️ This channel is already in the list.")
    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed: {e}\n\nMake sure bot is admin in that channel."
        )


async def removechannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/removechannel <chat_id>`\nUse `/channels` to view IDs.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    chat_id = context.args[0]
    if remove_channel(chat_id):
        await update.message.reply_text("🗑 Channel removed.")
    else:
        await update.message.reply_text("❌ Channel not found.")


async def channels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    chans = list_channels()
    if not chans:
        await update.message.reply_text("📭 No channels added yet.")
        return
    lines = [f"• *{t}*\n   ID: `{cid}`\n   Link: {lnk}" for cid, t, lnk in chans]
    await update.message.reply_text(
        "*📢 Force-Join Channels:*\n\n" + "\n\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


# ==================== ADMIN: STATS & BROADCAST ====================
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"👥 Users: `{count_users()}`\n"
        f"📦 Items: `{count_items()}`\n"
        f"📢 Channels: `{len(list_channels())}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    text = None
    replied = update.message.reply_to_message

    if context.args:
        text = " ".join(context.args)
    elif replied:
        text = replied.text or replied.caption

    if not text and not replied:
        await update.message.reply_text(
            "Usage: `/broadcast <message>` or reply to a message with `/broadcast`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    users = all_users()
    sent, failed = 0, 0
    await update.message.reply_text(f"📣 Broadcasting to {len(users)} users...")

    for uid in users:
        try:
            if replied:
                await replied.copy(chat_id=uid)
            else:
                await context.bot.send_message(chat_id=uid, text=text)
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ Done.\nSent: {sent}\nFailed: {failed}")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled.")


# ==================== DELIVER ====================
async def deliver(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    user_id = update.effective_user.id
    save_user(update.effective_user)

    missing = await check_membership(context, user_id)
    if missing:
        await update.message.reply_text(
            "🔒 You must join our channel(s) to get this item:",
            reply_markup=join_keyboard(missing),
        )
        return

    row = get_item(name)
    if not row:
        await update.message.reply_text(
            f"❌ No item named `{name}`", parse_mode=ParseMode.MARKDOWN
        )
        return

    content_type, content, caption = row
    try:
        if content_type == "text":
            await update.message.reply_text(content, disable_web_page_preview=False)
        elif content_type == "photo":
            await update.message.reply_photo(content, caption=caption)
        elif content_type == "video":
            await update.message.reply_video(content, caption=caption)
        elif content_type == "audio":
            await update.message.reply_audio(content, caption=caption)
        elif content_type == "voice":
            await update.message.reply_voice(content, caption=caption)
        elif content_type == "video_note":
            await update.message.reply_video_note(content)
        elif content_type == "animation":
            await update.message.reply_animation(content, caption=caption)
        elif content_type == "sticker":
            await update.message.reply_sticker(content)
        else:
            await update.message.reply_document(content, caption=caption)
    except Exception as e:
        try:
            await context.bot.send_document(
                chat_id=user_id, document=content, caption=caption
            )
        except Exception as e2:
            await update.message.reply_text(f"⚠️ Could not send file: {e2}")


async def get_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/get <name>`", parse_mode=ParseMode.MARKDOWN
        )
        return
    await deliver(update, context, context.args[0])


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if name.startswith("/"):
        return
    await deliver(update, context, name)


# ==================== CALLBACKS ====================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # --- User: check join ---
    if data == "check_join":
        missing = await check_membership(context, user_id)
        if missing:
            await query.edit_message_text(
                "❌ You haven't joined all channels yet.\nPlease join and press '✅ I Joined' again.",
                reply_markup=join_keyboard(missing),
            )
        else:
            await query.edit_message_text(
                "✅ Verified! Now send me the name of the item you want."
            )
        return

    # --- Admin-only callbacks ---
    if not is_admin(user_id):
        return

    if data == "admin_back":
        await query.edit_message_text(
            "👑 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_panel_keyboard(),
        )
        return

    if data == "admin_items":
        items = list_items()
        if not items:
            text = "📭 No items stored yet.\n\nUse `/add <name> <text>` or reply to a file with `/add <name>`."
        else:
            lines = [f"• `{n}` — {t}" for n, t in items]
            text = "*📦 Stored Items:*\n\n" + "\n".join(lines)
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]]
            ),
        )
        return

    if data == "admin_channels":
        await query.edit_message_text(
            "📢 *Force-Join Channels*\nManage your channels/groups below:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=channels_manage_keyboard(),
        )
        return

    if data == "admin_stats":
        await query.edit_message_text(
            f"📊 *Bot Statistics*\n\n"
            f"👥 Users: `{count_users()}`\n"
            f"📦 Items: `{count_items()}`\n"
            f"📢 Channels: `{len(list_channels())}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]]
            ),
        )
        return

    if data == "admin_broadcast":
        await query.edit_message_text(
            "📣 *Broadcast*\n\nSend: `/broadcast <message>`\nOr reply to any message with `/broadcast`.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]]
            ),
        )
        return

    if data == "admin_help":
        await query.edit_message_text(
            "*👑 Admin Commands*\n\n"
            "`/panel` — Panel\n"
            "`/add <name> <text>` — Add text\n"
            "Reply to file + `/add <name>` — Add file\n"
            "`/update <name>` — Replace item\n"
            "`/remove <name>` — Delete item\n"
            "`/list` — List items\n"
            "`/addchannel <link>` — Add force-join\n"
            "`/channels` — List channels\n"
            "`/stats` — Stats\n"
            "`/broadcast <msg>` — Broadcast",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]]
            ),
        )
        return

    if data == "add_channel":
        await query.edit_message_text(
            "➕ *Add Channel/Group*\n\n"
            "Send: `/addchannel https://t.me/yourchannel`\n\n"
            "Or *forward any message* from the channel/group and reply with `/addchannel`.\n\n"
            "⚠️ Bot must be admin in that chat.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="admin_channels")]]
            ),
        )
        return

    if data.startswith("del_channel:"):
        chat_id = data.split(":", 1)[1]
        if remove_channel(chat_id):
            await query.edit_message_text(
                "🗑 Channel removed.",
                reply_markup=channels_manage_keyboard(),
            )
        else:
            await query.edit_message_text(
                "❌ Channel not found.",
                reply_markup=channels_manage_keyboard(),
            )
        return


# ==================== SETUP ====================
async def post_init(app: Application):
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help"),
            BotCommand("panel", "Admin panel"),
            BotCommand("get", "Get an item by name"),
        ]
    )


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Public
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("get", get_cmd))

    # Admin
    app.add_handler(CommandHandler("panel", panel_cmd))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("update", update_cmd))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("delete", remove))
    app.add_handler(CommandHandler("list", listall))
    app.add_handler(CommandHandler("addchannel", addchannel_cmd))
    app.add_handler(CommandHandler("removechannel", removechannel_cmd))
    app.add_handler(CommandHandler("channels", channels_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))

    # Callbacks + text
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
