print("✅ movie_post_style plugin loaded successfully!")
import re
import random
import string
import aiohttp
from datetime import datetime
import motor.motor_asyncio
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)
from config import DB_URL, DB_NAME, ADMINS, TMDB_API_KEY, BASE_URL, POWERED_BY

# MongoDB setup
mongo = motor.motor_asyncio.AsyncIOMotorClient(DB_URL)
db = mongo[DB_NAME]
files_coll = db.files
drafts_coll = db.movie_drafts
users_coll = db.users

# Helper Functions
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


# ---------------- Commands ---------------- #

@Client.on_message(filters.command("movie") & filters.user(ADMINS) & filters.private)
async def movie_search_cmd(client: Client, m: Message):
    if len(m.command) < 2:
        return await m.reply_text("Usage: /movie <movie name>")
    query = " ".join(m.command[1:])
    msg = await m.reply_text(f"🔎 Searching TMDb for: {query} ...")
    js = await tmdb_search(query)
    results = js.get("results", [])
    if not results:
        return await msg.edit("No results found.")
    text = "Select the movie:\n\n"
    buttons = []
    for r in results[:6]:
        title = r.get("title") or r.get("name")
        year = (r.get("release_date") or "")[:4]
        buttons.append([InlineKeyboardButton(f"{title} ({year})", callback_data=f"tmdbsel:{r['id']}")])
    await msg.edit(text, reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex(r"^tmdbsel:(\d+)$"))
async def tmdb_selected_cb(client: Client, cq: CallbackQuery):
    tmdb_id = int(cq.data.split(":")[1])
    info = await tmdb_get(tmdb_id)
    title = info.get("title") or info.get("name")
    year = (info.get("release_date") or "")[:4]
    rating = info.get("vote_average", "N/A")
    genres = ", ".join([g["name"] for g in info.get("genres", [])]) or "N/A"
    lang = info.get("original_language", "N/A")
    poster_path = info.get("poster_path")
    poster = f"https://image.tmdb.org/t/p/w600{poster_path}" if poster_path else None

    caption = f"🎬 {title} ({year})\n⭐ TMDb: {rating}\n🎥 {genres}\n🗣️ Lang: {lang}\n\nPress 'Create Post' to start attaching files."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎞 Create Post", callback_data=f"createpost:{tmdb_id}")]])
    if poster:
        await cq.message.reply_photo(poster, caption=caption, reply_markup=kb)
    else:
        await cq.message.reply_text(caption, reply_markup=kb)
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^createpost:(\d+)$"))
async def createpost_cb(client: Client, cq: CallbackQuery):
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
        f"✅ Draft Created!\n\n🆔 Draft ID: `{draft['draft_id']}`\n\nNow attach file slugs using:\n`/attach <draft_id> <slug1> <slug2:1080p>`\n\nThen preview with:\n`/preview <draft_id>`",
        parse_mode="markdown"
    )
    await cq.answer("Draft created successfully.")


@Client.on_message(filters.command("attach") & filters.user(ADMINS) & filters.private)
async def attach_cmd(client: Client, m: Message):
    if len(m.command) < 3:
        return await m.reply_text("Usage: /attach <draft_id> <slug1> <slug2:1080p> ...")
    draft_id = m.command[1]
    raw = m.command[2:]
    draft = await drafts_coll.find_one({"draft_id": draft_id})
    if not draft:
        return await m.reply_text("❌ Draft not found.")
    attached = []
    for token in raw:
        if ":" in token:
            slug, qual = token.split(":", 1)
            slug, qual = slug.strip(), qual.strip()
        else:
            slug, qual = token.strip(), None
        doc = await files_coll.find_one({"slug": slug})
        if not doc:
            attached.append(f"❌ `{slug}` - Not Found")
            continue
        q = qual or detect_quality_from_name(doc.get("file_name", doc.get("filename", "")))
        size = doc.get("file_size", doc.get("size", 0))
        link = f"{BASE_URL}/f/{slug}"
        entry = {"slug": slug, "quality": q, "size": size, "link": link, "filename": doc.get("file_name", doc.get("filename", ""))}
        await drafts_coll.update_one({"draft_id": draft_id}, {"$push": {"slugs": entry}})
        attached.append(f"✅ {slug} → {q} ({format_size(size)})")
    await m.reply_text("Attach results:\n" + "\n".join(attached))


@Client.on_message(filters.command("preview") & filters.user(ADMINS) & filters.private)
async def preview_cmd(client: Client, m: Message):
    if len(m.command) < 2:
        return await m.reply_text("Usage: /preview <draft_id>")
    draft_id = m.command[1]
    draft = await drafts_coll.find_one({"draft_id": draft_id})
    if not draft:
        return await m.reply_text("❌ Draft not found.")
    tmdb = await tmdb_get(draft["tmdb_id"])
    title = tmdb.get("title") or tmdb.get("name")
    year = (tmdb.get("release_date") or "")[:4]
    lang = tmdb.get("original_language", "Unknown")
    poster_path = tmdb.get("poster_path")
    poster = f"https://image.tmdb.org/t/p/w600{poster_path}" if poster_path else None

    # Caption
    caption_lines = [
        f"🎬 Title : {title} ({year})",
        f"🗣️ Lang : {lang}",
        "",
        "🚀 Download Links ✨"
    ]

    byq = {}
    for s in draft.get("slugs", []):
        q = s.get("quality", "Unknown")
        byq.setdefault(q, []).append(s)

    order = ["2160p", "1080p", "720p", "480p", "360p", "HD", "Unknown"]
    for q in order:
        if q not in byq:
            continue
        parts = [f"{format_size(f['size'])}" for f in byq[q]]
        caption_lines.append(f"📦 {q} : {' | '.join(parts)} 🚀")

    caption_lines.append("")
    caption_lines.append(POWERED_BY)
    caption = "\n".join(caption_lines)

    # Inline buttons grouped by quality
    buttons = []
    for q in order:
        if q not in byq:
            continue
        row = []
        for f in byq[q]:
            size_txt = format_size(f["size"]) or "Link"
            row.append(InlineKeyboardButton(f"{q} ({size_txt}) 🚀", url=f["link"]))
        buttons.append(row)

    # Add footer row
    buttons.append([InlineKeyboardButton("💫 Join Channel", url="https://t.me/MovieLoverz")])

    kb = InlineKeyboardMarkup(buttons)

    # Send preview
    if poster:
        await m.reply_photo(poster, caption=caption, reply_markup=kb)
    else:
        await m.reply_text(caption, reply_markup=kb)
