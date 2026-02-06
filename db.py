import os
import aiosqlite

DB_PATH = os.getenv("DB_PATH", "/data/prefs.db")


def norm_city(city: str) -> str:
    return city.strip().upper()


def norm_state(st: str) -> str:
    return st.strip().upper()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Basic config per user
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_config (
            user_id INTEGER PRIMARY KEY,
            to_all INTEGER NOT NULL DEFAULT 0,
            from_scope TEXT NOT NULL DEFAULT 'first2'  -- 'first2' or 'any'
        )
        """)
        # Multiple FROM points
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_from_points (
            user_id INTEGER NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY (user_id, city, state)
        )
        """)
        # TO state list (used only if to_all=0)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_to_states (
            user_id INTEGER NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY (user_id, state)
        )
        """)
        await db.commit()


async def ensure_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_config (user_id, to_all, from_scope) VALUES (?, 0, 'first2')",
            (user_id,),
        )
        await db.commit()


async def add_from_point(user_id: int, city: str, st: str):
    await ensure_user(user_id)
    city = norm_city(city)
    st = norm_state(st)
    if len(st) != 2:
        raise ValueError("State must be 2 letters (e.g. OH).")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_from_points (user_id, city, state) VALUES (?, ?, ?)",
            (user_id, city, st),
        )
        await db.commit()


async def remove_from_point(user_id: int, city: str, st: str):
    await ensure_user(user_id)
    city = norm_city(city)
    st = norm_state(st)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_from_points WHERE user_id=? AND city=? AND state=?",
            (user_id, city, st),
        )
        await db.commit()


async def clear_from_points(user_id: int):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_from_points WHERE user_id=?", (user_id,))
        await db.commit()


async def set_to_all(user_id: int, enabled: bool):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_config SET to_all=? WHERE user_id=?",
            (1 if enabled else 0, user_id),
        )
        await db.commit()


async def add_to_state(user_id: int, st: str):
    await ensure_user(user_id)
    st = norm_state(st)
    if len(st) != 2:
        raise ValueError("State must be 2 letters (e.g. CO).")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_to_states (user_id, state) VALUES (?, ?)",
            (user_id, st),
        )
        await db.commit()


async def remove_to_state(user_id: int, st: str):
    await ensure_user(user_id)
    st = norm_state(st)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_to_states WHERE user_id=? AND state=?",
            (user_id, st),
        )
        await db.commit()


async def clear_to_states(user_id: int):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_to_states WHERE user_id=?", (user_id,))
        await db.commit()


async def set_from_scope(user_id: int, scope: str):
    await ensure_user(user_id)
    scope = scope.lower().strip()
    if scope not in ("first2", "any"):
        raise ValueError("Scope must be: first2 or any")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_config SET from_scope=? WHERE user_id=?",
            (scope, user_id),
        )
        await db.commit()


async def get_user_view(user_id: int):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT to_all, from_scope FROM user_config WHERE user_id=?",
            (user_id,),
        )
        to_all, from_scope = await cur.fetchone()

        cur2 = await db.execute(
            "SELECT city, state FROM user_from_points WHERE user_id=? ORDER BY state, city",
            (user_id,),
        )
        from_points = await cur2.fetchall()

        cur3 = await db.execute(
            "SELECT state FROM user_to_states WHERE user_id=? ORDER BY state",
            (user_id,),
        )
        to_states = [r[0] for r in await cur3.fetchall()]

    return {
        "to_all": bool(to_all),
        "from_scope": from_scope,
        "from_points": [(c, s) for c, s in from_points],
        "to_states": to_states,
    }


async def get_all_configs():
    """
    Returns list of dicts:
      {
        user_id, to_all, from_scope, from_points(set of (city,state)), to_states(set)
      }
    Only includes users with at least one FROM point.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, to_all, from_scope FROM user_config")
        cfg_rows = await cur.fetchall()

        cur2 = await db.execute("SELECT user_id, city, state FROM user_from_points")
        from_rows = await cur2.fetchall()

        cur3 = await db.execute("SELECT user_id, state FROM user_to_states")
        to_rows = await cur3.fetchall()

    from_map = {}
    for user_id, city, st in from_rows:
        from_map.setdefault(user_id, set()).add((city, st))

    to_map = {}
    for user_id, st in to_rows:
        to_map.setdefault(user_id, set()).add(st)

    out = []
    for user_id, to_all, from_scope in cfg_rows:
        fps = from_map.get(user_id, set())
        if not fps:
            continue
        out.append({
            "user_id": user_id,
            "to_all": bool(to_all),
            "from_scope": from_scope,
            "from_points": fps,
            "to_states": to_map.get(user_id, set()),
        })
    return out