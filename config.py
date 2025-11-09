print("✅ movie_post_style plugin loaded successfully!")

import re
import aiohttp
from bot import Bot
from pyrogram import filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from config import ADMINS, TMDB_API_KEY, CHANNEL_ID, BASE_URL, POWERED_BY, MOVIE_POST_CHANNEL
from helper_func import encode, decode


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
def detect_quality(name: str):
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
        encoded_query = await encode(f"{r['id']}|{query}")
        buttons.append([InlineKeyboardButton(f"{title} ({year})", callback_data=f"tmdbsel:{encoded_query}")])

    await msg.edit("🎬 Select the movie:", reply_markup=InlineKeyboardMarkup(buttons))
    print(f"✅ TMDb search results for '{query}' loaded successfully.")


# --- When movie is selected ---
@Bot.on_callback_query(filters.regex(r"^tmdbsel:(.+)$"))
async def tmdb_selected_cb(client: Bot, cq: CallbackQuery):
    print(f"✅ Callback received: {cq.data}")

    try:
        encoded_str = cq.data.split(":", 1)[1]
        decoded_str = await decode(encoded_str)
        tmdb_id_str, query = decoded_str.split("|", 1)
        tmdb_id = int(tmdb_id_str)
    except Exception as e:
        print(f"❌ Callback decode error: {e}")
        return await cq.answer("Invalid callback data.", show_alert=True)

    await cq.answer("Fetching movie details...")

    info = await tmdb_get(tmdb_id)
    title = info.get("title") or info.get("name")
    year = (info.get("release_date") or "")[:4]
    rating = info.get("vote_average", "N/A")
    genres = ", ".join([g["name"] for g in info.get("genres", [])]) or "N/A"
    lang = info.get("original_language", "Unknown").upper()
    poster_path = info.get("poster_path")
    poster = f"https://image.tmdb.org/t/p/w600{poster_path}" if poster_path else None

    temp = await cq.message.reply_text(f"🎬 {title} ({year})\nFetching files from DB Channel...")

    # --- Search files in FileStore DB Channel ---
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
        await temp.edit("❌ No matching files found in DB Channel.")
        return

    # --- Build Post ---
    quality_order = ["2160p", "1080p", "720p", "480p", "360p", "HD"]
    caption_lines = [
        f"🎬 {title} ({year})",
        f"⭐ {rating} | {genres}",
        f"🗣️ Language: {lang}",
        "",
        "🚀 Download Links:"
    ]
    buttons = []

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
    encoded_post = await encode(f"{tmdb_id}|{query}")
    buttons.append([InlineKeyboardButton("📢 Post to Channel", callback_data=f"postmovie:{encoded_post}")])
    kb = InlineKeyboardMarkup(buttons)

    if poster:
        await cq.message.reply_photo(poster, caption=final_caption, reply_markup=kb)
    else:
        await cq.message.reply_text(final_caption, reply_markup=kb)

    await temp.delete()


# --- Handle "Post to Channel" button ---
@Bot.on_callback_query(filters.regex(r"^postmovie:(.+)$"))
async def post_movie_channel_cb(client: Bot, cq: CallbackQuery):
    print(f"✅ Post callback received: {cq.data}")
    await cq.answer("Posting movie to channel...")

    try:
        encoded_post = cq.data.split(":", 1)[1]
        decoded_str = await decode(encoded_post)
        tmdb_id_str, query = decoded_str.split("|", 1)
        print(f"🎬 Posting '{query}' to channel...")

        if MOVIE_POST_CHANNEL:
            await cq.message.copy(MOVIE_POST_CHANNEL)
            print(f"✅ Movie '{query}' posted successfully to channel.")
            await cq.answer("✅ Movie successfully posted!", show_alert=True)
        else:
            await cq.answer("❌ MOVIE_POST_CHANNEL not set.", show_alert=True)
    except Exception as e:
        print(f"❌ Error posting movie: {e}")
        await cq.answer(f"❌ Failed to post: {e}", show_alert=True)
