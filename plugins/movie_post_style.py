print("✅ movie_post_style plugin loaded successfully!")

import re
import random
import string
import aiohttp
from datetime import datetime
from pyrogram import filters
from pyrogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)
from bot import Bot
from config import ADMINS, TMDB_API_KEY, BASE_URL, POWERED_BY, CHANNEL_ID
from helper_func import encode, get_messages


# ---- Temporary in-memory storage for movie drafts ----
movie_drafts = {}


# ---- Helpers ----
def gen_id(n=6):
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


# -------------- /movie Command --------------
@Bot.on_message(filters.command("movie") & filters.user(ADMINS) & filters.private)
async def movie_search(client: Bot, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /movie <movie name>")

    query = " ".join(message.command[1:])
    msg = await message.reply_text(f"🔎 Searching for **{query}** ...")
    js = await tmdb_search(query)
    results = js.get("results", [])

    if not results:
        return await msg.edit("❌ No results found on TMDb.")

    buttons = []
    for r in results[:6]:
        title = r.get("title") or r.get("name")
        year = (r.get("release_date") or "")[:4]
        buttons.append([
            InlineKeyboardButton(f"{title} ({year})", callback_data=f"tmdbsel:{r['id']}")
        ])

    await msg.edit("🎬 Select the movie:", reply_markup=InlineKeyboardMarkup(buttons))


# -------------- TMDb Selection Callback --------------
@Bot.on_callback_query(filters.regex(r"^tmdbsel:(\d+)$"))
async def tmdb_selected(client: Bot, cq: CallbackQuery):
    tmdb_id = int(cq.data.split(":")[1])
    info = await tmdb_get(tmdb_id)
    title = info.get("title") or info.get("name")
    year = (info.get("release_date") or "")[:4]
    rating = info.get("vote_average", "N/A")
    genres = ", ".join([g["name"] for g in info.get("genres", [])]) or "N/A"
    lang = info.get("original_language", "Unknown").upper()
    poster_path = info.get("poster_path")
    poster = f"https://image.tmdb.org/t/p/w600{poster_path}" if poster_path else None

    caption = (
        f"🎬 {title} ({year})\n"
        f"⭐ TMDb: {rating}\n"
        f"🎥 {genres}\n"
        f"🗣️ Language: {lang}\n\n"
        f"Tap below to create post."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎞 Create Post", callback_data=f"createpost:{tmdb_id}")]
    ])

    if poster:
        await cq.message.reply_photo(poster, caption=caption, reply_markup=kb)
    else:
        await cq.message.reply_text(caption, reply_markup=kb)

    await cq.answer("Movie selected!")


# -------------- Create Post Callback --------------
@Bot.on_callback_query(filters.regex(r"^createpost:(\d+)$"))
async def create_post(client: Bot, cq: CallbackQuery):
    tmdb_id = int(cq.data.split(":")[1])
    draft_id = gen_id()
    movie_drafts[cq.from_user.id] = {"draft_id": draft_id, "tmdb_id": tmdb_id, "files": []}
    await cq.message.reply_text(
        f"✅ Draft Created!\n\n🆔 Draft ID: `{draft_id}`\n\n"
        f"Now send `/attach <t.me/c/.../msgid> <quality>` links to add files.\n\n"
        f"Example:\n`/attach https://t.me/c/2087146692/10855 1080p https://t.me/c/2087146692/10857 720p`",
        parse_mode="markdown"
    )
    await cq.answer("Draft created successfully.")


# -------------- /attach Command --------------
@Bot.on_message(filters.command("attach") & filters.user(ADMINS) & filters.private)
async def attach_files(client: Bot, message: Message):
    user_id = message.from_user.id
    if user_id not in movie_drafts:
        return await message.reply_text("❌ No active draft. Use /movie first.")

    draft = movie_drafts[user_id]
    links = message.command[1:]

    if not links:
        return await message.reply_text("Usage:\n`/attach <t.me/c/.../msgid> <quality>`", parse_mode="markdown")

    attached = []
    for i in range(0, len(links), 2):
        try:
            link = links[i]
            qual = links[i + 1] if i + 1 < len(links) else "Unknown"

            match = re.search(r"t\.me\/c\/(-?\d+)\/(\d+)", link)
            if not match:
                attached.append(f"❌ Invalid link: {link}")
                continue

            chat_part, msg_id = match.groups()
            msg_id = int(msg_id)
            encoded = await encode(f"get-{msg_id * abs(int(chat_part))}")
            file_link = f"{BASE_URL}?file_id={encoded}"

            draft["files"].append({"link": file_link, "quality": qual})
            attached.append(f"✅ Added {qual} → {file_link}")
        except Exception as e:
            attached.append(f"⚠️ Error: {e}")

    await message.reply_text("\n".join(attached))

    # ---- Auto preview and post ----
    tmdb = await tmdb_get(draft["tmdb_id"])
    title = tmdb.get("title") or tmdb.get("name")
    year = (tmdb.get("release_date") or "")[:4]
    lang = tmdb.get("original_language", "Unknown").upper()
    poster_path = tmdb.get("poster_path")
    poster = f"https://image.tmdb.org/t/p/w600{poster_path}" if poster_path else None

    caption_lines = [
        f"🎬 {title} ({year})",
        f"🗣️ Language : {lang}",
        "",
        "🚀 Download Links:"
    ]
    buttons = []

    # Group buttons by quality
    grouped = {}
    for f in draft["files"]:
        grouped.setdefault(f["quality"], []).append(f)

    order = ["2160p", "1080p", "720p", "480p", "360p", "HD", "Unknown"]
    for q in order:
        if q not in grouped:
            continue
        row = [InlineKeyboardButton(f"{q} 🚀", url=f["link"]) for f in grouped[q]]
        buttons.append(row)
        caption_lines.append(f"📦 {q} : {len(grouped[q])} files")

    caption_lines.append("")
    caption_lines.append(POWERED_BY)
    kb = InlineKeyboardMarkup(buttons)

    caption = "\n".join(caption_lines)
    sent = None
    if poster:
        sent = await client.send_photo(CHANNEL_ID, poster, caption=caption, reply_markup=kb)
    else:
        sent = await client.send_message(CHANNEL_ID, caption, reply_markup=kb)

    post_link = f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{sent.id}"
    await message.reply_text(f"✅ Movie post created!\n🔗 [View Post]({post_link})", disable_web_page_preview=True)

    # Clear draft for user
    del movie_drafts[user_id]
