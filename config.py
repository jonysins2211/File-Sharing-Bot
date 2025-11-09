print("✅ movie_post_style plugin loaded successfully!")

import re
import aiohttp
from pyrogram import filters
from pyrogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery
)
from bot import Bot
from config import ADMINS, TMDB_API_KEY, CHANNEL_ID, BASE_URL, POWERED_BY, MOVIE_POST_CHANNEL
from helper_func import encode


# --- TMDb API ---
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


# --- Helpers ---
def detect_quality(name):
    name = name.lower()
    if "2160" in name or "4k" in name:
        return "2160p"
    elif "1080" in name:
        return "1080p"
    elif "720" in name:
        return "720p"
    elif "480" in name:
        return "480p"
    elif "360" in name:
        return "360p"
    return "HD"


# --- /movie Command ---
@Bot.on_message(filters.command("movie") & filters.user(ADMINS) & filters.private)
async def movie_search_cmd(client: Bot, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /movie <movie name>")

    query = " ".join(message.command[1:])
    msg = await message.reply_text(f"🔍 Searching TMDb for **{query}** ...")

    js = await tmdb_search(query)
    results = js.get("results", [])
    if not results:
        return await msg.edit("❌ No results found.")

    buttons = []
    for r in results[:6]:
        title = r.get("title") or r.get("name")
        year = (r.get("release_date") or "")[:4]
        buttons.append([InlineKeyboardButton(f"{title} ({year})", callback_data=f"tmdbsel:{r['id']}:{query}")])

    print(f"✅ Movie search results for '{query}' loaded successfully.")
    await msg.edit("🎬 Select the movie:", reply_markup=InlineKeyboardMarkup(buttons))


# --- When movie is selected ---
@Bot.on_callback_query(filters.regex(r"^tmdbsel:(\d+):(.*)$"))
async def tmdb_selected_cb(client: Bot, cq: CallbackQuery):
    print(f"✅ Callback received: {cq.data}")

    tmdb_id, query = cq.data.split(":")[1:]
    tmdb_id = int(tmdb_id)

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
        f"Fetching files from DB Channel..."
    )

    temp = await cq.message.reply_text(caption)
    await cq.answer("Loading files...")

    # --- Search your FileStore Channel for matching files ---
    results = []
    async for msg in client.search_messages(chat_id=CHANNEL_ID, query=query, limit=50):
        if msg.document or msg.video:
            file_name = msg.document.file_name if msg.document else msg.video.file_name
            quality = detect_quality(file_name)
            msg_id = msg.id
            encoded = await encode(f"get-{msg_id * abs(CHANNEL_ID)}")
            file_link = f"{BASE_URL}?file_id={encoded}"
            results.append((quality, file_link, file_name))

    print(f"✅ Found {len(results)} matching files for '{query}'")

    if not results:
        return await temp.edit("❌ No matching files found in DB Channel.")

    # --- Group by Quality ---
    quality_order = ["2160p", "1080p", "720p", "480p", "360p", "HD"]
    buttons, caption_lines = [], [
        f"🎬 {title} ({year})",
        f"⭐ {rating} | {genres}",
        f"🗣️ Language: {lang}",
        "",
        "🚀 Download Links:"
    ]

    for q in quality_order:
        group = [f for f in results if f[0] == q]
        if not group:
            continue
        row = [InlineKeyboardButton(f"{q} 🚀", url=f[1]) for f in group]
        buttons.append(row)
        caption_lines.append(f"📦 {q} : {len(group)} file(s)")

    caption_lines.append("")
    caption_lines.append(POWERED_BY)
    final_caption = "\n".join(caption_lines)

    # --- Add "Post to Channel" button ---
    buttons.append([InlineKeyboardButton("📢 Post to Channel", callback_data=f"postmovie:{tmdb_id}:{query}")])

    kb = InlineKeyboardMarkup(buttons)

    # --- Send Preview ---
    if poster:
        await cq.message.reply_photo(poster, caption=final_caption, reply_markup=kb)
    else:
        await cq.message.reply_text(final_caption, reply_markup=kb)

    await temp.delete()


# --- Handle "Post to Channel" button ---
@Bot.on_callback_query(filters.regex(r"^postmovie:(\d+):(.*)$"))
async def post_movie_channel_cb(client: Bot, cq: CallbackQuery):
    print(f"✅ Post callback received: {cq.data}")

    tmdb_id, query = cq.data.split(":")[1:]
    tmdb_id = int(tmdb_id)
    await cq.answer("Posting movie to channel...")

    try:
        msg_to_forward = cq.message
        if MOVIE_POST_CHANNEL:
            await msg_to_forward.copy(MOVIE_POST_CHANNEL)
            print(f"✅ Movie '{query}' posted successfully to channel.")
            await cq.answer("✅ Movie successfully posted!", show_alert=True)
        else:
            await cq.answer("❌ MOVIE_POST_CHANNEL not set.", show_alert=True)
    except Exception as e:
        print(f"❌ Error posting movie: {e}")
        await cq.answer(f"❌ Failed to post: {e}", show_alert=True)
