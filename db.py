import os
import aiosqlite

DB_PATH = os.getenv("DB_PATH", "/data/prefs.db")


def norm_city(city: str) -> str:
    return city.strip().upper()


def norm_state(st: str) -> str:
    return st.strip().upper()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Keep user_config minimal. (If your old DB already has from_scope, that's fine; we just ignore it.)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_config (
            user_id INTEGER PRIMARY KEY,
            to_all INTEGER NOT NULL DEFAULT 0
        )
        """)

        # Origin points by exact city+state
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_origin_points (
            user_id INTEGER NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY (user_id, city, state)
        )
        """)

        # Origin states (match if FIRST stop state is in this list)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_origin_states (
            user_id INTEGER NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY (user_id, state)
        )
        """)

        # Destination state list (used only if to_all=0)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_destination_states (
            user_id INTEGER NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY (user_id, state)
        )
        """)

        await db.commit()


async def ensure_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_config (user_id, to_all) VALUES (?, 0)",
            (user_id,),
        )
        await db.commit()


# ---------- Origin (city+state) ----------
async def add_origin_point(user_id: int, city: str, st: str):
    await ensure_user(user_id)
    city = norm_city(city)
    st = norm_state(st)
    if len(st) != 2:
        raise ValueError("State must be 2 letters (e.g. OH).")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_origin_points (user_id, city, state) VALUES (?, ?, ?)",
            (user_id, city, st),
        )
        await db.commit()


async def remove_origin_point(user_id: int, city: str, st: str):
    await ensure_user(user_id)
    city = norm_city(city)
    st = norm_state(st)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_origin_points WHERE user_id=? AND city=? AND state=?",
            (user_id, city, st),
        )
        await db.commit()


async def clear_origin_points(user_id: int):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_origin_points WHERE user_id=?", (user_id,))
        await db.commit()


# ---------- Origin (states) ----------
async def add_origin_state(user_id: int, st: str):
    await ensure_user(user_id)
    st = norm_state(st)
    if len(st) != 2:
        raise ValueError("State must be 2 letters (e.g. OH).")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_origin_states (user_id, state) VALUES (?, ?)",
            (user_id, st),
        )
        await db.commit()


async def remove_origin_state(user_id: int, st: str):
    await ensure_user(user_id)
    st = norm_state(st)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_origin_states WHERE user_id=? AND state=?",
            (user_id, st),
        )
        await db.commit()


async def clear_origin_states(user_id: int):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_origin_states WHERE user_id=?", (user_id,))
        await db.commit()


# ---------- Destination ----------
async def set_to_all(user_id: int, enabled: bool):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_config SET to_all=? WHERE user_id=?",
            (1 if enabled else 0, user_id),
        )
        await db.commit()


async def add_destination_state(user_id: int, st: str):
    await ensure_user(user_id)
    st = norm_state(st)
    if len(st) != 2:
        raise ValueError("State must be 2 letters (e.g. CO).")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_destination_states (user_id, state) VALUES (?, ?)",
            (user_id, st),
        )
        await db.commit()


async def remove_destination_state(user_id: int, st: str):
    await ensure_user(user_id)
    st = norm_state(st)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_destination_states WHERE user_id=? AND state=?",
            (user_id, st),
        )
        await db.commit()


async def clear_destination_states(user_id: int):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_destination_states WHERE user_id=?", (user_id,))
        await db.commit()


# ---------- Views ----------
async def get_user_view(user_id: int):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT to_all FROM user_config WHERE user_id=?",
            (user_id,),
        )
        (to_all,) = await cur.fetchone()

        cur2 = await db.execute(
            "SELECT city, state FROM user_origin_points WHERE user_id=? ORDER BY state, city",
            (user_id,),
        )
        origin_points = await cur2.fetchall()

        cur3 = await db.execute(
            "SELECT state FROM user_origin_states WHERE user_id=? ORDER BY state",
            (user_id,),
        )
        origin_states = [r[0] for r in await cur3.fetchall()]

        cur4 = await db.execute(
            "SELECT state FROM user_destination_states WHERE user_id=? ORDER BY state",
            (user_id,),
        )
        dest_states = [r[0] for r in await cur4.fetchall()]

    return {
        "to_all": bool(to_all),
        "origin_points": [(c, s) for c, s in origin_points],
        "origin_states": origin_states,
        "destination_states": dest_states,
    }


async def get_all_configs():
    """
    Returns list of dicts:
      {
        user_id,
        to_all,
        origin_points(set of (CITY_UPPER, ST)),
        origin_states(set of ST),
        destination_states(set of ST)
      }

    Only includes users with at least one origin rule (point or state).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, to_all FROM user_config")
        cfg_rows = await cur.fetchall()

        cur2 = await db.execute("SELECT user_id, city, state FROM user_origin_points")
        op_rows = await cur2.fetchall()

        cur3 = await db.execute("SELECT user_id, state FROM user_origin_states")
        os_rows = await cur3.fetchall()

        cur4 = await db.execute("SELECT user_id, state FROM user_destination_states")
        ds_rows = await cur4.fetchall()

    op_map = {}
    for user_id, city, st in op_rows:
        op_map.setdefault(user_id, set()).add((city, st))

    os_map = {}
    for user_id, st in os_rows:
        os_map.setdefault(user_id, set()).add(st)

    ds_map = {}
    for user_id, st in ds_rows:
        ds_map.setdefault(user_id, set()).add(st)

    out = []
    for user_id, to_all in cfg_rows:
        origin_points = op_map.get(user_id, set())
        origin_states = os_map.get(user_id, set())

        if not origin_points and not origin_states:
            continue

        out.append({
            "user_id": user_id,
            "to_all": bool(to_all),
            "origin_points": origin_points,
            "origin_states": origin_states,
            "destination_states": ds_map.get(user_id, set()),
        })
    return out