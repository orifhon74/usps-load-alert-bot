import os
import re
import asyncio
from dotenv import load_dotenv

from telethon import TelegramClient, events

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

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
if not API_ID or not API_HASH or not CHANNEL_USERNAME:
    raise RuntimeError("Missing API_ID/API_HASH/CHANNEL_USERNAME in .env")

# Persist Telethon session inside /data (Docker volume)
SESSION_PATH = os.getenv("SESSION_PATH", "/data/listener_session")
tele_client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

# Parse: 📍 CITY, ST (2+ times)
LOC_RE = re.compile(r"📍\s*([A-Z][A-Z\s\.\'-]+?),\s*([A-Z]{2})")


# -----------------------
# Buttons (UI)
# -----------------------
BTN_ADD_ORIGIN = "➕ Add Origin"
BTN_CLEAR_ORIGINS = "🧹 Clear Origins"
BTN_ADD_DEST = "➕ Add Destination State"
BTN_CLEAR_DEST = "🧹 Clear Destination States"
BTN_TOGGLE_ALL = "🌎 Toggle Destination: All"
BTN_VIEW = "📋 View Settings"
BTN_TEST50 = "🔎 Test Last 50"
BTN_HELP = "❓ Help"

MAIN_KB = ReplyKeyboardMarkup(
    [
        [BTN_ADD_ORIGIN, BTN_ADD_DEST],
        [BTN_TOGGLE_ALL, BTN_VIEW],
        [BTN_CLEAR_ORIGINS, BTN_CLEAR_DEST],
        [BTN_TEST50, BTN_HELP],
    ],
    resize_keyboard=True
)


def title_city(city_upper: str) -> str:
    return " ".join(w.capitalize() for w in city_upper.split())


def format_user_list(view: dict) -> str:
    # DB still calls them from_points/to_states, but UI says Origin/Destination
    origins = view["from_points"]
    scope = view["from_scope"]
    to_all = view["to_all"]
    dest_states = view["to_states"]

    if origins:
        origin_disp = "\n".join([f"- {title_city(c)}, {s}" for c, s in origins])
    else:
        origin_disp = "(none)"

    if to_all:
        dest_disp = "ALL STATES ✅"
    else:
        dest_disp = ", ".join(dest_states) if dest_states else "(none)"

    return (
        f"Origin points ({len(origins)}):\n{origin_disp}\n\n"
        f"Origin matching: {scope}\n"
        f"Destination states: {dest_disp}"
    )


def parse_city_state_arg(text: str):
    """
    Accepts:
      "Louisville, KY" OR "Louisville KY"
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


# -----------------------
# Bot commands (power users)
# -----------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "USPS Load Alerts\n\n"
        "Use the buttons below.\n"
        "Tip: Origin should be exact City + State like: Cincinnati, OH\n"
    )
    await update.message.reply_text(msg, reply_markup=MAIN_KB)


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text(format_user_list(view), reply_markup=MAIN_KB)


async def addfrom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args)
    try:
        city, st = parse_city_state_arg(raw)
        await add_from_point(update.effective_user.id, city, st)
    except ValueError as e:
        return await update.message.reply_text(f"Usage: /addfrom City, ST\n({e})", reply_markup=MAIN_KB)

    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("✅ Added origin.\n\n" + format_user_list(view), reply_markup=MAIN_KB)


async def removefrom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args)
    try:
        city, st = parse_city_state_arg(raw)
        await remove_from_point(update.effective_user.id, city, st)
    except ValueError as e:
        return await update.message.reply_text(f"Usage: /removefrom City, ST\n({e})", reply_markup=MAIN_KB)

    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("🗑️ Removed origin.\n\n" + format_user_list(view), reply_markup=MAIN_KB)


async def clearfrom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await clear_from_points(update.effective_user.id)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("🧹 Cleared origins.\n\n" + format_user_list(view), reply_markup=MAIN_KB)


async def fromscope_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /fromscope first2  OR  /fromscope any", reply_markup=MAIN_KB)
    scope = context.args[0].lower().strip()
    try:
        await set_from_scope(update.effective_user.id, scope)
    except ValueError as e:
        return await update.message.reply_text(str(e), reply_markup=MAIN_KB)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("✅ Updated origin matching.\n\n" + format_user_list(view), reply_markup=MAIN_KB)


async def addto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /addto CO", reply_markup=MAIN_KB)
    st = context.args[0].strip().upper()
    if len(st) != 2:
        return await update.message.reply_text("State must be 2 letters (e.g. CO).", reply_markup=MAIN_KB)
    await add_to_state(update.effective_user.id, st)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("✅ Added destination state.\n\n" + format_user_list(view), reply_markup=MAIN_KB)


async def removeto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /removeto CO", reply_markup=MAIN_KB)
    st = context.args[0].strip().upper()
    await remove_to_state(update.effective_user.id, st)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("🗑️ Removed destination state.\n\n" + format_user_list(view), reply_markup=MAIN_KB)


async def clearto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await clear_to_states(update.effective_user.id)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("🧹 Cleared destination states.\n\n" + format_user_list(view), reply_markup=MAIN_KB)


async def toall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ("on", "off"):
        return await update.message.reply_text("Usage: /toall on  OR  /toall off", reply_markup=MAIN_KB)
    enabled = context.args[0].lower() == "on"
    await set_to_all(update.effective_user.id, enabled)
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text("✅ Updated destination setting.\n\n" + format_user_list(view), reply_markup=MAIN_KB)


async def testlast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(context.args[0]) if context.args else 20
    except ValueError:
        return await update.message.reply_text("Usage: /testlast 20", reply_markup=MAIN_KB)

    n = max(1, min(n, 200))

    view = await get_user_view(update.effective_user.id)
    from_points = set(view["from_points"])
    if not from_points:
        return await update.message.reply_text("Set at least one Origin first (Add Origin).", reply_markup=MAIN_KB)

    to_all = view["to_all"]
    to_states = set(view["to_states"])
    scope = view["from_scope"]

    msgs = []
    async for m in tele_client.iter_messages(CHANNEL_USERNAME, limit=n):
        if m and m.message:
            msgs.append(m.message)

    msgs.reverse()

    def match_text(text: str) -> bool:
        stops = parse_stops(text)
        if not stops:
            return False
        final_city, final_state = stops[-1]
        scoped = stops_for_scope(stops, scope)
        origin_ok = any(stop in from_points for stop in scoped)
        if not origin_ok:
            return False
        if to_all:
            return True
        return final_state in to_states

    matches = [t for t in msgs if match_text(t)]

    header = (
        f"🔎 Tested last {len(msgs)} posts\n"
        f"✅ Matches: {len(matches)}\n\n"
        f"{format_user_list(view)}"
    )

    if not matches:
        return await update.message.reply_text(header + "\n\nNo matches found.", reply_markup=MAIN_KB)

    samples = matches[-3:]
    sample_text = ""
    for i, t in enumerate(samples, 1):
        snippet = t.strip()
        if len(snippet) > 700:
            snippet = snippet[:700] + "…"
        sample_text += f"\n\n--- Match {i} ---\n{snippet}"

    await update.message.reply_text(header + sample_text, reply_markup=MAIN_KB)


# -----------------------
# Button flows (parents use this)
# -----------------------
async def menu_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "How to use:\n"
        f"- Tap {BTN_ADD_ORIGIN} then type: City, ST\n"
        f"- Tap {BTN_ADD_DEST} then type: ST (example: CO)\n"
        f"- Tap {BTN_TOGGLE_ALL} to allow all destination states\n"
        f"- Tap {BTN_VIEW} to see your settings\n"
    )
    await update.message.reply_text(msg, reply_markup=MAIN_KB)


async def handle_free_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles typed input AFTER user tapped a button that requests input.
    """
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return

    uid = update.effective_user.id
    text = (update.message.text or "").strip()

    if awaiting == "origin":
        try:
            city, st = parse_city_state_arg(text)
            await add_from_point(uid, city, st)
            context.user_data.pop("awaiting", None)
            view = await get_user_view(uid)
            return await update.message.reply_text("✅ Added origin.\n\n" + format_user_list(view), reply_markup=MAIN_KB)
        except Exception as e:
            return await update.message.reply_text(
                f"Try again: City, ST\nExample: Cincinnati, OH\n({e})",
                reply_markup=ReplyKeyboardRemove()
            )

    if awaiting == "dest_state":
        st = text.strip().upper()
        if len(st) != 2:
            return await update.message.reply_text("State must be 2 letters.\nExample: CO", reply_markup=ReplyKeyboardRemove())
        await add_to_state(uid, st)
        context.user_data.pop("awaiting", None)
        view = await get_user_view(uid)
        return await update.message.reply_text("✅ Added destination state.\n\n" + format_user_list(view), reply_markup=MAIN_KB)


async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles button taps (they arrive as normal text messages).
    """
    text = (update.message.text or "").strip()

    if text == BTN_ADD_ORIGIN:
        context.user_data["awaiting"] = "origin"
        return await update.message.reply_text(
            "Send Origin as: City, ST\nExample: Cincinnati, OH",
            reply_markup=ReplyKeyboardRemove()
        )

    if text == BTN_ADD_DEST:
        context.user_data["awaiting"] = "dest_state"
        return await update.message.reply_text(
            "Send Destination state as 2 letters.\nExample: CO",
            reply_markup=ReplyKeyboardRemove()
        )

    if text == BTN_CLEAR_ORIGINS:
        await clear_from_points(update.effective_user.id)
        view = await get_user_view(update.effective_user.id)
        return await update.message.reply_text("✅ Cleared origins.\n\n" + format_user_list(view), reply_markup=MAIN_KB)

    if text == BTN_CLEAR_DEST:
        await clear_to_states(update.effective_user.id)
        view = await get_user_view(update.effective_user.id)
        return await update.message.reply_text("✅ Cleared destination states.\n\n" + format_user_list(view), reply_markup=MAIN_KB)

    if text == BTN_TOGGLE_ALL:
        view = await get_user_view(update.effective_user.id)
        await set_to_all(update.effective_user.id, not view["to_all"])
        view2 = await get_user_view(update.effective_user.id)
        return await update.message.reply_text("✅ Updated destination setting.\n\n" + format_user_list(view2), reply_markup=MAIN_KB)

    if text == BTN_VIEW:
        view = await get_user_view(update.effective_user.id)
        return await update.message.reply_text(format_user_list(view), reply_markup=MAIN_KB)

    if text == BTN_TEST50:
        context.args = ["50"]
        return await testlast_cmd(update, context)

    if text == BTN_HELP:
        return await menu_help(update, context)

    # If they typed random text (not a menu action), show menu again
    return await update.message.reply_text("Use the menu buttons below 👇", reply_markup=MAIN_KB)


# -----------------------
# Telethon listener -> bot alerts
# -----------------------
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

        # Origin match: any scoped stop equals one of user's origin points
        if not any(stop in cfg["from_points"] for stop in scoped_stops):
            continue

        # Destination match: final stop state
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

    # Commands (optional / for you)
    bot_app.add_handler(CommandHandler("start", start_cmd))
    bot_app.add_handler(CommandHandler("list", list_cmd))

    bot_app.add_handler(CommandHandler("addfrom", addfrom_cmd))
    bot_app.add_handler(CommandHandler("removefrom", removefrom_cmd))
    bot_app.add_handler(CommandHandler("clearfrom", clearfrom_cmd))
    bot_app.add_handler(CommandHandler("fromscope", fromscope_cmd))

    bot_app.add_handler(CommandHandler("addto", addto_cmd))
    bot_app.add_handler(CommandHandler("removeto", removeto_cmd))
    bot_app.add_handler(CommandHandler("clearto", clearto_cmd))
    bot_app.add_handler(CommandHandler("toall", toall_cmd))

    bot_app.add_handler(CommandHandler("testlast", testlast_cmd))

    # UI: typed input first, then button taps
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text_input), group=0)
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons), group=1)

    await bot_app.initialize()
    await bot_app.start()
    bot_task = asyncio.create_task(bot_app.updater.start_polling())

    tele_task = asyncio.create_task(run_telethon())

    await asyncio.gather(bot_task, tele_task)


if __name__ == "__main__":
    asyncio.run(main())