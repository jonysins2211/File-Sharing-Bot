print("✅ movie_post_style plugin loaded successfully!")

import re
import random
import string
import aiohttp
from datetime import datetime
import motor.motor_asyncio
from pyrogram import filters
from pyrogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)
from bot import Bot
from config import DB_URL, DB_NAME, ADMINS, TMDB_API_KEY, BASE_URL, POWERED_BY, CHANNEL_ID
from helper_func import encode  # used for generating vercel links

# -------------------- MongoDB Setup --------------------
mongo = motor.motor_asyncio.AsyncIOMotorClient(DB_URL)
db = mongo[DB_NAME]
files_coll = db.files
drafts_coll = db.movie_drafts
users_coll = db.users


# -------------------- Helper Functions --------------------
def gen_id(n=7):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def detect_quality_from_name(name: str):
    name = (name or "").lower()
    if re.search(r"2160|4k", name): return "2160p"
    if "1080" in name: return "1080p"
    if "720" in name: return "720p"
    if "480" in name: return "480p"
    if "360" in name: return "360p"
    if re.search(r"hd|hdrip|bluray|brrip", name): return "HD"
    return "Unknown"


def format_size(nbytes):
    try:
        n = int(nbytes)
    except:
        return ""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n} {unit}"
        n = n // 1024
    return f"{n} TB"


async def tmdb_search(query):
    url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            return await r.json()


async def tmdb_get(tmdb_id):
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={TMDB_API_KEY}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            return await r.json()


# -------------------- /movie Command --------------------
@Bot.on_message(filters.command("movie") & filters.user(ADMINS) & filters.private)
async def movie_search_cmd(client: Bot, m: Message):
    if len(m.command) < 2:
        return await m.reply_text("Usage: /movie <movie name>")

    query = " ".join(m.command[1:])
    msg = await m.reply_text(f"🔎 Searching TMDb for: {query} ...")

    js = await tmdb_search(query)
    results = js.get("results", [])
    if not results:
        return await msg.edit("❌ No results found on TMDb.")

    text = "🎬 Select the movie:\n\n"
    buttons = []
    for r in results[:6]:
        title = r.get("title") or r.get("name")
        year = (r.get("release_date") or "")[:4]
        buttons.append([
            InlineKeyboardButton(f"{title} ({year})", callback_data=f"tmdbsel:{r['id']}")
        ])
    await msg.edit(text, reply_markup=InlineKeyboardMarkup(buttons))


# -------------------- Callbacks --------------------
@Bot.on_callback_query(filters.regex(r"^tmdbsel:(\d+)$"))
async def tmdb_selected_cb(client: Bot, cq: CallbackQuery):
    tmdb_id = int(cq.data.split(":")[1])
    info = await tmdb_get(tmdb_id)
    title = info.get("title") or info.get("name")
    year = (info.get("release_date") or "")[:4]
    rating = info.get("vote_average", "N/A")
    genres = ", ".join([g["name"] for g in info.get("genres", [])]) or "N/A"
    lang = info.get("original_language", "N/A")
    poster_path = info.get("poster_path")
    poster = f"https://image.tmdb.org/t/p/w600{poster_path}" if poster_path else None

    caption = (
        f"🎬 {title} ({year})\n"
        f"⭐ TMDb: {rating}\n"
        f"🎥 Genres: {genres}\n"
        f"🗣️ Lang: {lang}\n\n"
        f"Press '🎞 Create Post' to start attaching files."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎞 Create Post", callback_data=f"createpost:{tmdb_id}")]
    ])

    if poster:
        await cq.message.reply_photo(poster, caption=caption, reply_markup=kb)
    else:
        await cq.message.reply_text(caption, reply_markup=kb)
    await cq.answer("✅ Movie selected.")


@Bot.on_callback_query(filters.regex(r"^createpost:(\d+)$"))
async def createpost_cb(client: Bot, cq: CallbackQuery):
    tmdb_id = int(cq.data.split(":")[1])
    draft = {
        "draft_id": gen_id(),
        "tmdb_id": tmdb_id,
        "creator": cq.from_user.id,
        "created_at": datetime.utcnow(),
        "slugs": []
    }
    await drafts_coll.insert_one(draft)
    await cq.message.reply_text(
        f"✅ Draft Created!\n\n"
        f"🆔 Draft ID: `{draft['draft_id']}`\n\n"
        f"Now attach Telegram file links using:\n"
        f"`/attach {draft['draft_id']} <t.me/c/.../1234> <t.me/c/.../1235:1080p>`",
        parse_mode="markdown"
    )
    await cq.answer("Draft created successfully.")


# -------------------- /attach Command (Auto Post) --------------------
@Bot.on_message(filters.command("attach") & filters.user(ADMINS) & filters.private)
async def attach_cmd(client: Bot, m: Message):
    if len(m.command) < 3:
        return await m.reply_text("Usage: /attach <draft_id> <file_link1> <file_link2:1080p> ...")

    draft_id = m.command[1]
    links = m.command[2:]
    draft = await drafts_coll.find_one({"draft_id": draft_id})
    if not draft:
        return await m.reply_text("❌ Draft not found. Make sure you created it using /movie.")

    attached = []
    for token in links:
        qual = None
        if ":" in token and not token.startswith("http"):
            link, qual = token.split(":", 1)
        else:
            link = token

        match = re.search(r"t\.me\/c\/(-?\d+)\/(\d+)", link)
        if not match:
            attached.append(f"❌ Invalid link format: {link}")
            continue

        chat_part, msg_id = match.groups()
        msg_id = int(msg_id)
        encoded = await encode(f"get-{msg_id * abs(int(chat_part))}")
        final_link = f"https://movieloverz-files.vercel.app/?file_id={encoded}"

        q = qual or detect_quality_from_name(link)
        entry = {"link": final_link, "quality": q, "slug": link, "size": 0, "filename": f"File {msg_id}"}
        await drafts_coll.update_one({"draft_id": draft_id}, {"$push": {"slugs": entry}})
        attached.append(f"✅ Added link ({q})")

    await m.reply_text("Attach results:\n" + "\n".join(attached))

    # ---- AUTO PREVIEW + POST TO CHANNEL ----
    try:
        tmdb = await tmdb_get(draft["tmdb_id"])
        title = tmdb.get("title") or tmdb.get("name")
        year = (tmdb.get("release_date") or "")[:4]
        lang = tmdb.get("original_language", "Unknown")
        poster_path = tmdb.get("poster_path")
        poster = f"https://image.tmdb.org/t/p/w600{poster_path}" if poster_path else None

        caption_lines = [
            f"🎬 {title} ({year})",
            f"🗣️ Language : {lang.upper()}",
            "",
            "🚀 Available Download Links ✨"
        ]
        byq = {}
        for s in draft.get("slugs", []):
            q = s.get("quality", "Unknown")
            byq.setdefault(q, []).append(s)

        order = ["2160p", "1080p", "720p", "480p", "360p", "HD", "Unknown"]
        for q in order:
            if q not in byq:
                continue
            caption_lines.append(f"📦 {q} : {len(byq[q])} files 🚀")
        caption_lines.append("")
        caption_lines.append(POWERED_BY)
        caption = "\n".join(caption_lines)

        buttons = []
        for q in order:
            if q not in byq:
                continue
            row = [InlineKeyboardButton(f"{q} 🚀", url=f["link"]) for f in byq[q]]
            buttons.append(row)
        buttons.append([InlineKeyboardButton("💫 Join Channel", url="https://t.me/MovieLoverz")])
        kb = InlineKeyboardMarkup(buttons)

        # ✅ Send post to your private channel
        sent = None
        if poster:
            sent = await client.send_photo(CHANNEL_ID, poster, caption=caption, reply_markup=kb)
        else:
            sent = await client.send_message(CHANNEL_ID, caption, reply_markup=kb)

        post_link = f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{sent.id}"
        await m.reply_text(f"✅ Movie post successfully sent!\n🔗 [View Post]({post_link})",
                           disable_web_page_preview=True)
    except Exception as e:
        print(f"⚠️ Auto post failed: {e}")
        await m.reply_text(f"⚠️ Error while posting: `{e}`")
