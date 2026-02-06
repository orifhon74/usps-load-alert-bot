import os
import re
import asyncio
from dotenv import load_dotenv

from telethon import TelegramClient, events
from telethon.tl.types import PeerChannel

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from db import (
    init_db,
    add_from_point, remove_from_point, clear_from_points,
    set_to_all, add_to_state, remove_to_state, clear_to_states,
    set_from_scope,
    get_user_view, get_all_configs
)

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN in .env")

SESSION_PATH = os.getenv("SESSION_PATH", "/data/listener_session")
tele_client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

# Parse: 📍 CITY, ST  (can appear 2+ times)
LOC_RE = re.compile(r"📍\s*([A-Z][A-Z\s\.\'-]+?),\s*([A-Z]{2})")


def title_city(city_upper: str) -> str:
    return " ".join(w.capitalize() for w in city_upper.split())


def format_user_list(view: dict) -> str:
    fps = view["from_points"]
    from_scope = view["from_scope"]
    to_all = view["to_all"]
    to_states = view["to_states"]

    if fps:
        from_disp = "\n".join([f"- {title_city(c)}, {s}" for c, s in fps])
    else:
        from_disp = "(none)"

    if to_all:
        to_disp = "ALL STATES ✅"
    else:
        to_disp = ", ".join(to_states) if to_states else "(none)"

    return (
        f"FROM points ({len(fps)}):\n{from_disp}\n\n"
        f"FROM scope: {from_scope}\n"
        f"TO states: {to_disp}"
    )


def parse_city_state_arg(text: str):
    """
    Accepts:
      "Louisville, KY"  OR  "Louisville KY"
    Returns (city, ST) or raises ValueError
    """
    text = text.strip()
    if not text:
        raise ValueError("Missing value")

    if "," in text:
        city_part, st_part = text.split(",", 1)
        city = city_part.strip()
        st = st_part.strip().split()[0] if st_part.strip() else ""
    else:
        parts = text.split()
        if len(parts) < 2:
            raise ValueError("Use: City, ST")
        st = parts[-1]
        city = " ".join(parts[:-1])

    st = st.strip().upper()
    if len(st) != 2:
        raise ValueError("State must be 2 letters (e.g. OH).")

    return city, st


# -----------------------
# Bot commands
# -----------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "USPS Load Alerts\n\n"
        "Add FROM points (pickup/origin candidates):\n"
        "  /addfrom Cincinnati, OH\n"
        "  /removefrom Cincinnati, OH\n"
        "  /clearfrom\n\n"
        "Control how FROM matches multi-stop posts:\n"
        "  /fromscope first2   (default)\n"
        "  /fromscope any\n\n"
        "Set TO (destination) states:\n"
        "  /addto CO\n"
        "  /removeto CO\n"
        "  /clearto\n\n"
        "Allow ALL destination states:\n"
        "  /toall on\n"
        "  /toall off\n\n"
        "View settings:\n"
        "  /list\n"
    )
    await update.message.reply_text(msg)


async def addfrom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args)
    try:
        city, st = parse_city_state_arg(raw)
        await add_from_point(update.effective_user.id, city, st)
    except ValueError as e:
        return await update.message.reply_text(f"Usage: /addfrom City, ST\n({e})")

    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("✅ Added FROM point.\n\n" + format_user_list(view))


async def removefrom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args)
    try:
        city, st = parse_city_state_arg(raw)
        await remove_from_point(update.effective_user.id, city, st)
    except ValueError as e:
        return await update.message.reply_text(f"Usage: /removefrom City, ST\n({e})")

    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("🗑️ Removed FROM point.\n\n" + format_user_list(view))


async def clearfrom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await clear_from_points(update.effective_user.id)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("🧹 Cleared FROM points.\n\n" + format_user_list(view))


async def fromscope_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /fromscope first2  OR  /fromscope any")
    scope = context.args[0].lower().strip()
    try:
        await set_from_scope(update.effective_user.id, scope)
    except ValueError as e:
        return await update.message.reply_text(str(e))
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("✅ Updated FROM scope.\n\n" + format_user_list(view))


async def addto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /addto CO")
    st = context.args[0].strip().upper()
    if len(st) != 2:
        return await update.message.reply_text("State must be 2 letters (e.g. CO).")
    await add_to_state(update.effective_user.id, st)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("✅ Added TO state.\n\n" + format_user_list(view))


async def removeto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /removeto CO")
    st = context.args[0].strip().upper()
    await remove_to_state(update.effective_user.id, st)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("🗑️ Removed TO state.\n\n" + format_user_list(view))


async def clearto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await clear_to_states(update.effective_user.id)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("🧹 Cleared TO state list.\n\n" + format_user_list(view))


async def toall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ("on", "off"):
        return await update.message.reply_text("Usage: /toall on  OR  /toall off")
    enabled = context.args[0].lower() == "on"
    await set_to_all(update.effective_user.id, enabled)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("✅ Updated TO setting.\n\n" + format_user_list(view))


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text(format_user_list(view))


# TESTING
async def testlast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Usage: /testlast 50
    try:
        n = int(context.args[0]) if context.args else 20
    except ValueError:
        return await update.message.reply_text("Usage: /testlast 20")

    n = max(1, min(n, 200))  # cap it

    # Get this user's config only
    view = await get_user_view(update.effective_user.id)
    from_points = set(view["from_points"])
    if not from_points:
        return await update.message.reply_text("Set at least one FROM point first using /addfrom City, ST")

    to_all = view["to_all"]
    to_states = set(view["to_states"])
    scope = view["from_scope"]

    # Fetch last N messages from channel
    msgs = []
    async for m in tele_client.iter_messages(CHANNEL_USERNAME, limit=n):
        if m and m.message:
            msgs.append(m.message)

    msgs.reverse()  # oldest -> newest for nicer display

    def match_text(text: str) -> bool:
        stops = parse_stops(text)
        if not stops:
            return False
        final_city, final_state = stops[-1]
        scoped = stops_for_scope(stops, scope)
        from_ok = any(stop in from_points for stop in scoped)
        if not from_ok:
            return False
        if to_all:
            return True
        return final_state in to_states

    matches = []
    for t in msgs:
        if match_text(t):
            matches.append(t)

    # Summarize
    header = (
        f"🔎 Tested last {len(msgs)} posts\n"
        f"✅ Matches: {len(matches)}\n\n"
        f"{format_user_list(view)}"
    )

    if not matches:
        return await update.message.reply_text(header + "\n\nNo matches found. (Maybe widen TO states or check spelling.)")

    # Show up to 3 sample matches (trim text)
    samples = matches[-3:]
    sample_text = ""
    for i, t in enumerate(samples, 1):
        snippet = t.strip()
        if len(snippet) > 500:
            snippet = snippet[:500] + "…"
        sample_text += f"\n\n--- Match {i} ---\n{snippet}"

    await update.message.reply_text(header + sample_text)


# -----------------------
# Matching
# -----------------------
def parse_stops(text: str):
    """
    Returns list of stops [(CITY_UPPER, ST), ...] length >= 2, or [].
    """
    locs = LOC_RE.findall(text or "")
    if len(locs) < 2:
        return []
    return [(c.strip().upper(), s.strip().upper()) for c, s in locs]


def stops_for_scope(stops, scope: str):
    if scope == "any":
        return stops
    # default first2
    return stops[:2]


@tele_client.on(events.NewMessage(chats=CHANNEL_USERNAME))
async def on_new_message(event):
    text = event.raw_text or ""
    stops = parse_stops(text)
    if not stops:
        return

    final_city, final_state = stops[-1]

    configs = await get_all_configs()
    if not configs:
        return

    alert = f"🚚 LOAD MATCH\n\n{text}"

    for cfg in configs:
        scoped_stops = stops_for_scope(stops, cfg["from_scope"])
        # Does any scoped stop match any of user's FROM points?
        if not any(stop in cfg["from_points"] for stop in scoped_stops):
            continue

        # TO match is based on FINAL stop's state
        if cfg["to_all"] or (final_state in cfg["to_states"]):
            try:
                await bot_app.bot.send_message(chat_id=cfg["user_id"], text=alert)
            except Exception:
                pass


# -----------------------
# Run both clients
# -----------------------
async def run_telethon():
    await tele_client.start()
    await tele_client.run_until_disconnected()


async def main():
    global bot_app
    await init_db()

    bot_app = Application.builder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start_cmd))
    bot_app.add_handler(CommandHandler("addfrom", addfrom_cmd))
    bot_app.add_handler(CommandHandler("removefrom", removefrom_cmd))
    bot_app.add_handler(CommandHandler("clearfrom", clearfrom_cmd))
    bot_app.add_handler(CommandHandler("fromscope", fromscope_cmd))

    bot_app.add_handler(CommandHandler("addto", addto_cmd))
    bot_app.add_handler(CommandHandler("removeto", removeto_cmd))
    bot_app.add_handler(CommandHandler("clearto", clearto_cmd))
    bot_app.add_handler(CommandHandler("toall", toall_cmd))

    bot_app.add_handler(CommandHandler("list", list_cmd))
    bot_app.add_handler(CommandHandler("testlast", testlast_cmd))

    await bot_app.initialize()
    await bot_app.start()
    bot_task = asyncio.create_task(bot_app.updater.start_polling())

    tele_task = asyncio.create_task(run_telethon())

    await asyncio.gather(bot_task, tele_task)


if __name__ == "__main__":
    asyncio.run(main())