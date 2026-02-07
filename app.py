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
    add_origin_point, remove_origin_point, clear_origin_points,
    add_origin_state, remove_origin_state, clear_origin_states,
    set_to_all,
    add_destination_state, remove_destination_state, clear_destination_states,
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

SESSION_PATH = os.getenv("SESSION_PATH", "/data/listener_session")
tele_client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

# Parse: 📍 CITY, ST (2+ times)
LOC_RE = re.compile(r"📍\s*([A-Z][A-Z\s\.\'-]+?),\s*([A-Z]{2})")


# -----------------------
# Buttons (UI)
# -----------------------
BTN_ADD_ORIGIN_CITY = "➕ Add Origin (City and State)"
BTN_ADD_ORIGIN_STATE = "➕ Add Origin (State)"
BTN_CLEAR_ORIGINS = "🧹 Clear Origins"

BTN_ADD_DEST = "➕ Add Destination State"
BTN_CLEAR_DEST = "🧹 Clear Destination States"
BTN_TOGGLE_ALL = "🌎 Toggle Destination: All"

BTN_VIEW = "📋 View Settings"
BTN_TEST50 = "🔎 Test Last 50"
BTN_HELP = "❓ Help"

MAIN_KB = ReplyKeyboardMarkup(
    [
        [BTN_ADD_ORIGIN_CITY, BTN_ADD_ORIGIN_STATE],
        [BTN_ADD_DEST, BTN_TOGGLE_ALL],
        [BTN_VIEW, BTN_TEST50],
        [BTN_CLEAR_ORIGINS, BTN_CLEAR_DEST],
        [BTN_HELP],
    ],
    resize_keyboard=True
)


def title_city(city_upper: str) -> str:
    return " ".join(w.capitalize() for w in city_upper.split())


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


def parse_state_only(text: str) -> str:
    st = (text or "").strip().upper()
    if len(st) != 2 or not st.isalpha():
        raise ValueError("State must be 2 letters (e.g. OH).")
    return st


def format_user_list(view: dict) -> str:
    origin_points = view["origin_points"]
    origin_states = view["origin_states"]
    to_all = view["to_all"]
    dest_states = view["destination_states"]

    if origin_points:
        op_disp = "\n".join([f"- {title_city(c)}, {s}" for c, s in origin_points])
    else:
        op_disp = "(none)"

    os_disp = ", ".join(origin_states) if origin_states else "(none)"
    dest_disp = "ALL STATES ✅" if to_all else (", ".join(dest_states) if dest_states else "(none)")

    return (
        f"Origin cities ({len(origin_points)}):\n{op_disp}\n\n"
        f"Origin states ({len(origin_states)}): {os_disp}\n\n"
        f"Destination states: {dest_disp}\n\n"
        # f"Matching rule:\n"
        # f"- Origin = FIRST stop only\n"
        # f"- Destination = LAST stop only"
    )


# -----------------------
# Matching helpers
# -----------------------
def parse_stops(text: str):
    """
    Returns list of stops [(CITY_UPPER, ST), ...] length >= 2, or [].
    """
    locs = LOC_RE.findall(text or "")
    if len(locs) < 2:
        return []
    return [(c.strip().upper(), s.strip().upper()) for c, s in locs]


def origin_destination(stops):
    """
    Origin = first stop, Destination = last stop
    """
    return stops[0], stops[-1]


# -----------------------
# Commands (optional power users)
# -----------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "USPS Load Alerts\n\n"
        "Use the buttons below.\n"
        "Origin = FIRST stop. Destination = LAST stop.\n"
    )
    await update.message.reply_text(msg, reply_markup=MAIN_KB)


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    view = await get_user_view(update.effective_user.id)
    await update.message.reply_text(format_user_list(view), reply_markup=MAIN_KB)


async def testlast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(context.args[0]) if context.args else 20
    except ValueError:
        return await update.message.reply_text("Usage: /testlast 20", reply_markup=MAIN_KB)

    n = max(1, min(n, 200))

    view = await get_user_view(update.effective_user.id)
    origin_points = set(view["origin_points"])
    origin_states = set(view["origin_states"])
    if not origin_points and not origin_states:
        return await update.message.reply_text("Add at least one Origin city or Origin state first.", reply_markup=MAIN_KB)

    to_all = view["to_all"]
    dest_states = set(view["destination_states"])

    msgs = []
    async for m in tele_client.iter_messages(CHANNEL_USERNAME, limit=n):
        if m and m.message:
            msgs.append(m.message)
    msgs.reverse()

    def match_text(text: str) -> bool:
        stops = parse_stops(text)
        if not stops:
            return False
        (o_city, o_state), (_d_city, d_state) = origin_destination(stops)

        origin_ok = ((o_city, o_state) in origin_points) or (o_state in origin_states)
        if not origin_ok:
            return False

        if to_all:
            return True
        return d_state in dest_states

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
# Button flows
# -----------------------
async def menu_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "How to use:\n"
        f"- Tap {BTN_ADD_ORIGIN_CITY} then type: City, ST (example: Cincinnati, OH)\n"
        f"- Tap {BTN_ADD_ORIGIN_STATE} then type: ST (example: OH)\n"
        f"- Tap {BTN_ADD_DEST} then type: ST (example: CO)\n"
        f"- Tap {BTN_TOGGLE_ALL} to allow all destination states\n"
        f"- Tap {BTN_VIEW} to see your settings\n"
    )
    await update.message.reply_text(msg, reply_markup=MAIN_KB)


async def handle_free_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return

    uid = update.effective_user.id
    text = (update.message.text or "").strip()

    if awaiting == "origin_city":
        try:
            city, st = parse_city_state_arg(text)
            await add_origin_point(uid, city, st)
            context.user_data.pop("awaiting", None)
            view = await get_user_view(uid)
            return await update.message.reply_text("✅ Added origin city.\n\n" + format_user_list(view), reply_markup=MAIN_KB)
        except Exception as e:
            return await update.message.reply_text(
                f"Try again: City, ST\nExample: Cincinnati, OH\n({e})",
                reply_markup=ReplyKeyboardRemove()
            )

    if awaiting == "origin_state":
        try:
            st = parse_state_only(text)
            await add_origin_state(uid, st)
            context.user_data.pop("awaiting", None)
            view = await get_user_view(uid)
            return await update.message.reply_text("✅ Added origin state.\n\n" + format_user_list(view), reply_markup=MAIN_KB)
        except Exception as e:
            return await update.message.reply_text(
                f"Try again: ST\nExample: OH\n({e})",
                reply_markup=ReplyKeyboardRemove()
            )

    if awaiting == "dest_state":
        try:
            st = parse_state_only(text)
            await add_destination_state(uid, st)
            context.user_data.pop("awaiting", None)
            view = await get_user_view(uid)
            return await update.message.reply_text("✅ Added destination state.\n\n" + format_user_list(view), reply_markup=MAIN_KB)
        except Exception as e:
            return await update.message.reply_text(
                f"Try again: ST\nExample: CO\n({e})",
                reply_markup=ReplyKeyboardRemove()
            )


async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    uid = update.effective_user.id

    if text == BTN_ADD_ORIGIN_CITY:
        context.user_data["awaiting"] = "origin_city"
        return await update.message.reply_text(
            "Send Origin City as: City, ST\nExample: Cincinnati, OH",
            reply_markup=ReplyKeyboardRemove()
        )

    if text == BTN_ADD_ORIGIN_STATE:
        context.user_data["awaiting"] = "origin_state"
        return await update.message.reply_text(
            "Send Origin State as 2 letters.\nExample: OH",
            reply_markup=ReplyKeyboardRemove()
        )

    if text == BTN_ADD_DEST:
        context.user_data["awaiting"] = "dest_state"
        return await update.message.reply_text(
            "Send Destination State as 2 letters.\nExample: CO",
            reply_markup=ReplyKeyboardRemove()
        )

    if text == BTN_CLEAR_ORIGINS:
        await clear_origin_points(uid)
        await clear_origin_states(uid)
        view = await get_user_view(uid)
        return await update.message.reply_text("✅ Cleared all origins.\n\n" + format_user_list(view), reply_markup=MAIN_KB)

    if text == BTN_CLEAR_DEST:
        await clear_destination_states(uid)
        view = await get_user_view(uid)
        return await update.message.reply_text("✅ Cleared destination states.\n\n" + format_user_list(view), reply_markup=MAIN_KB)

    if text == BTN_TOGGLE_ALL:
        view = await get_user_view(uid)
        await set_to_all(uid, not view["to_all"])
        view2 = await get_user_view(uid)
        return await update.message.reply_text("✅ Updated destination setting.\n\n" + format_user_list(view2), reply_markup=MAIN_KB)

    if text == BTN_VIEW:
        view = await get_user_view(uid)
        return await update.message.reply_text(format_user_list(view), reply_markup=MAIN_KB)

    if text == BTN_TEST50:
        context.args = ["50"]
        return await testlast_cmd(update, context)

    if text == BTN_HELP:
        return await menu_help(update, context)

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

    (o_city, o_state), (_d_city, d_state) = origin_destination(stops)

    configs = await get_all_configs()
    if not configs:
        return

    alert = f"🚚 LOAD MATCH\n\n{text}"

    for cfg in configs:
        # Origin match: FIRST stop only
        origin_ok = ((o_city, o_state) in cfg["origin_points"]) or (o_state in cfg["origin_states"])
        if not origin_ok:
            continue

        # Destination match: LAST stop state only
        if cfg["to_all"] or (d_state in cfg["destination_states"]):
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
    bot_app.add_handler(CommandHandler("list", list_cmd))
    bot_app.add_handler(CommandHandler("testlast", testlast_cmd))

    # UI handlers (typed input first, then menu buttons)
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text_input), group=0)
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons), group=1)

    await bot_app.initialize()
    await bot_app.start()
    bot_task = asyncio.create_task(bot_app.updater.start_polling())
    tele_task = asyncio.create_task(run_telethon())

    await asyncio.gather(bot_task, tele_task)


if __name__ == "__main__":
    asyncio.run(main())