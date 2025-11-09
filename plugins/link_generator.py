from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot import Bot
from config import ADMINS
from helper_func import encode, get_message_id


# ---------- Batch Link Generator ----------
@Bot.on_message(filters.private & filters.user(ADMINS) & filters.command('batch'))
async def batch(client: Client, message: Message):
    while True:
        try:
            first_message = await client.ask(
                text="📥 Forward the *first message* from DB Channel (With Quotes)\n\nOr send the DB Channel post link:",
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60
            )
        except:
            return
        f_msg_id = await get_message_id(client, first_message)
        if f_msg_id:
            break
        else:
            await first_message.reply(
                "❌ Error\n\nThis forwarded post is not from your DB Channel or invalid link.",
                quote=True
            )
            continue

    while True:
        try:
            second_message = await client.ask(
                text="📥 Forward the *last message* from DB Channel (With Quotes)\n\nOr send the DB Channel post link:",
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60
            )
        except:
            return
        s_msg_id = await get_message_id(client, second_message)
        if s_msg_id:
            break
        else:
            await second_message.reply(
                "❌ Error\n\nThis forwarded post is not from your DB Channel or invalid link.",
                quote=True
            )
            continue

    # Encode the range of messages
    string = f"get-{f_msg_id * abs(client.db_channel.id)}-{s_msg_id * abs(client.db_channel.id)}"
    base64_string = await encode(string)

    # ✅ Use your redirect page instead of t.me
    link = f"https://movieloverz-files.vercel.app?file_id={base64_string}"

    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔁 Share URL", url=f'https://telegram.me/share/url?url={link}')]]
    )

    await second_message.reply_text(
        f"<b>✅ Here is your Batch Link:</b>\n\n{link}",
        quote=True,
        reply_markup=reply_markup
    )


# ---------- Single Link Generator ----------
@Bot.on_message(filters.private & filters.user(ADMINS) & filters.command('genlink'))
async def link_generator(client: Client, message: Message):
    while True:
        try:
            channel_message = await client.ask(
                text="📤 Forward a *message* from DB Channel (With Quotes)\n\nOr send the DB Channel post link:",
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60
            )
        except:
            return
        msg_id = await get_message_id(client, channel_message)
        if msg_id:
            break
        else:
            await channel_message.reply(
                "❌ Error\n\nThis forwarded post is not from your DB Channel or invalid link.",
                quote=True
            )
            continue

    # Encode the message ID
    base64_string = await encode(f"get-{msg_id * abs(client.db_channel.id)}")

    # ✅ Use redirect page instead of t.me
    link = f"https://movieloverz-files.vercel.app?file_id={base64_string}"

    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔁 Share URL", url=f'https://telegram.me/share/url?url={link}')]]
    )

    await channel_message.reply_text(
        f"<b>✅ Here is your File Link:</b>\n\n{link}",
        quote=True,
        reply_markup=reply_markup
    )
