print("✅ movie_post_style plugin loaded successfully!")

from bot import Bot
import aiohttp
from pyrogram import filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
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


# --- /movie Auto-Posting Command ---
@Bot.on_message(filters.command("movie") & filters.user(ADMINS) & filters.private)
async def movie_auto_post(client: Bot, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /movie <movie name>")

    query = " ".join(message.command[1:])
    msg = await message.reply_text(f"🔍 Searching TMDb for **{query}** ...")

    # --- TMDb Search ---
    js = await tmdb_search(query)
    results = js.get("results", [])
    if not results:
        return await msg.edit("❌ No results found on TMDb.")

    # Pick first result automatically
    r = results[0]
    tmdb_id = r.get("id")
    info = await tmdb_get(tmdb_id)

    title = info.get("title") or info.get("name") or query.title()
    year = (info.get("release_date") or "")[:4]
    rating = info.get("vote_average", "N/A")
    genres = ", ".join([g["name"] for g in info.get("genres", [])]) or "N/A"
    lang = info.get("original_language", "Unknown").upper()
    poster_path = info.get("poster_path")
    poster = f"https://image.tmdb.org/t/p/w600{poster_path}" if poster_path else None

    await msg.edit(f"🎬 Found **{title} ({year})** — fetching files from DB channel...")

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

    if not results:
        return await msg.edit("❌ No matching files found in DB Channel.")

    # --- Group Files by Quality ---
    quality_order = ["2160p", "1080p", "720p", "480p", "360p", "HD"]
    buttons, caption_lines = [], [
        f"🎬 {title} ({year})",
        f"⭐ TMDb: {rating}",
        f"🎥 {genres}",
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
    caption = "\n".join(caption_lines)
    markup = InlineKeyboardMarkup(buttons)

    # --- Auto Post to Channel ---
    try:
        if MOVIE_POST_CHANNEL:
            if poster:
                await client.send_photo(
                    chat_id=MOVIE_POST_CHANNEL,
                    photo=poster,
                    caption=caption,
                    reply_markup=markup
                )
            else:
                await client.send_message(
                    chat_id=MOVIE_POST_CHANNEL,
                    text=caption,
                    reply_markup=markup
                )
            await msg.edit(f"✅ Movie **{title} ({year})** posted to channel successfully!")
        else:
            await msg.edit("❌ MOVIE_POST_CHANNEL not set in config.")
    except Exception as e:
        await msg.edit(f"❌ Error posting: `{e}`")
