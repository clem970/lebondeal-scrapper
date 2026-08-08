import asyncio
import os
import sqlite3
import time

from config import DB_PATH

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_lock = asyncio.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS filters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    site TEXT NOT NULL,
    url TEXT NOT NULL,
    channel_id INTEGER,
    dm_user_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    interval_seconds INTEGER NOT NULL DEFAULT 60,
    jitter_percent INTEGER NOT NULL DEFAULT 10,
    quiet_start TEXT,
    quiet_end TEXT,
    max_credits INTEGER,
    credits_used INTEGER NOT NULL DEFAULT 0,
    min_price REAL,
    max_price REAL,
    include_keywords TEXT,
    exclude_keywords TEXT,
    ping_role_id INTEGER,
    embed_style TEXT NOT NULL DEFAULT 'detailed',
    dedup INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    last_run_at INTEGER,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER PRIMARY KEY,
    global_max_credits INTEGER,
    global_credits_used INTEGER NOT NULL DEFAULT 0,
    log_channel_id INTEGER,
    low_credit_alert_threshold INTEGER,
    default_interval INTEGER NOT NULL DEFAULT 60,
    unify_channel_id INTEGER,
    paused INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sent_ads (
    filter_id INTEGER NOT NULL,
    ad_id TEXT NOT NULL,
    sent_at INTEGER NOT NULL,
    PRIMARY KEY (filter_id, ad_id)
);

CREATE TABLE IF NOT EXISTS credit_log (
    guild_id INTEGER PRIMARY KEY,
    credits_remaining INTEGER,
    updated_at INTEGER
);

-- Un dashboard = un message Discord. On stocke l'écran affiché pour que les boutons
-- restent fonctionnels même après un redémarrage du bot (routage par message_id).
CREATE TABLE IF NOT EXISTS dashboard_state (
    message_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    screen TEXT NOT NULL DEFAULT 'home',
    filter_id INTEGER,
    pending_action TEXT,
    pending_value TEXT,
    return_screen TEXT,
    updated_at INTEGER NOT NULL
);
"""
_conn.executescript(SCHEMA)
_conn.commit()


async def _run(fn, *args):
    async with _lock:
        return await asyncio.to_thread(fn, *args)


# ---------- helpers sync ----------

def _q(sql, params=(), fetch="all", commit=False):
    cur = _conn.execute(sql, params)
    if commit:
        _conn.commit()
        return cur.lastrowid
    if fetch == "all":
        return [dict(r) for r in cur.fetchall()]
    if fetch == "one":
        r = cur.fetchone()
        return dict(r) if r else None
    return None


# ---------- settings ----------

def _get_settings(guild_id):
    row = _q("SELECT * FROM settings WHERE guild_id=?", (guild_id,), "one")
    if row is None:
        _q(
            "INSERT INTO settings (guild_id, default_interval) VALUES (?, 60)",
            (guild_id,), commit=True,
        )
        row = _q("SELECT * FROM settings WHERE guild_id=?", (guild_id,), "one")
    return row


async def get_settings(guild_id):
    return await _run(_get_settings, guild_id)


async def update_settings(guild_id, **fields):
    await _run(_get_settings, guild_id)  # s'assure que la ligne existe
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    await _run(_q, f"UPDATE settings SET {cols} WHERE guild_id=?", (*fields.values(), guild_id), "all", True)


# ---------- filters ----------

async def add_filter(guild_id, name, site, url, interval_seconds, channel_id=None, dm_user_id=None):
    settings = await get_settings(guild_id)
    return await _run(
        _q,
        """INSERT INTO filters (guild_id, name, site, url, channel_id, dm_user_id, interval_seconds, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (guild_id, name, site, url, channel_id, dm_user_id, interval_seconds, int(time.time())),
        "all", True,
    )


async def get_filter(filter_id, guild_id=None):
    if guild_id is not None:
        return await _run(_q, "SELECT * FROM filters WHERE id=? AND guild_id=?", (filter_id, guild_id), "one")
    return await _run(_q, "SELECT * FROM filters WHERE id=?", (filter_id,), "one")


async def list_filters(guild_id, site=None):
    if site:
        return await _run(_q, "SELECT * FROM filters WHERE guild_id=? AND site=? ORDER BY id", (guild_id, site), "all")
    return await _run(_q, "SELECT * FROM filters WHERE guild_id=? ORDER BY id", (guild_id,), "all")


async def list_all_active_filters():
    return await _run(_q, "SELECT * FROM filters WHERE enabled=1", (), "all")


async def update_filter(filter_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    await _run(_q, f"UPDATE filters SET {cols} WHERE id=?", (*fields.values(), filter_id), "all", True)


async def delete_filter(filter_id):
    await _run(_q, "DELETE FROM filters WHERE id=?", (filter_id,), "all", True)
    await _run(_q, "DELETE FROM sent_ads WHERE filter_id=?", (filter_id,), "all", True)


async def delete_all_filters(guild_id, site=None):
    ids = [f["id"] for f in await list_filters(guild_id, site)]
    if site:
        await _run(_q, "DELETE FROM filters WHERE guild_id=? AND site=?", (guild_id, site), "all", True)
    else:
        await _run(_q, "DELETE FROM filters WHERE guild_id=?", (guild_id,), "all", True)
    for fid in ids:
        await _run(_q, "DELETE FROM sent_ads WHERE filter_id=?", (fid,), "all", True)


async def set_enabled(filter_id, enabled: bool):
    await update_filter(filter_id, enabled=1 if enabled else 0)


async def set_enabled_all(guild_id, enabled: bool, site=None):
    if site:
        await _run(_q, "UPDATE filters SET enabled=? WHERE guild_id=? AND site=?", (1 if enabled else 0, guild_id, site), "all", True)
    else:
        await _run(_q, "UPDATE filters SET enabled=? WHERE guild_id=?", (1 if enabled else 0, guild_id), "all", True)


async def reset_run(filter_id):
    """Relance immédiate: force le prochain tick du scheduler."""
    await update_filter(filter_id, last_run_at=None, last_error=None)


# ---------- dédoublonnage des annonces déjà envoyées ----------

def _has_sent(filter_id, ad_id):
    row = _q("SELECT 1 FROM sent_ads WHERE filter_id=? AND ad_id=?", (filter_id, ad_id), "one")
    return row is not None


async def has_sent(filter_id, ad_id):
    return await _run(_has_sent, filter_id, ad_id)


async def mark_sent(filter_id, ad_id):
    await _run(
        _q,
        "INSERT OR IGNORE INTO sent_ads (filter_id, ad_id, sent_at) VALUES (?,?,?)",
        (filter_id, ad_id, int(time.time())), "all", True,
    )


# ---------- crédits ----------

async def log_credits_remaining(guild_id, remaining):
    await _run(
        _q,
        """INSERT INTO credit_log (guild_id, credits_remaining, updated_at) VALUES (?,?,?)
           ON CONFLICT(guild_id) DO UPDATE SET credits_remaining=excluded.credits_remaining, updated_at=excluded.updated_at""",
        (guild_id, remaining, int(time.time())), "all", True,
    )


async def get_credits_remaining(guild_id):
    return await _run(_q, "SELECT * FROM credit_log WHERE guild_id=?", (guild_id,), "one")


async def add_credits_used(filter_id, guild_id, amount):
    if amount <= 0:
        return
    await _run(_q, "UPDATE filters SET credits_used = credits_used + ? WHERE id=?", (amount, filter_id), "all", True)
    await _run(_q, "UPDATE settings SET global_credits_used = global_credits_used + ? WHERE guild_id=?", (amount, guild_id), "all", True)


# ---------- état des dashboards persistants ----------

async def save_dashboard_state(message_id, guild_id, channel_id, screen, filter_id=None,
                                pending_action=None, pending_value=None, return_screen=None):
    await _run(
        _q,
        """INSERT INTO dashboard_state
               (message_id, guild_id, channel_id, screen, filter_id, pending_action, pending_value, return_screen, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(message_id) DO UPDATE SET
               screen=excluded.screen, filter_id=excluded.filter_id,
               pending_action=excluded.pending_action, pending_value=excluded.pending_value,
               return_screen=excluded.return_screen, updated_at=excluded.updated_at""",
        (message_id, guild_id, channel_id, screen, filter_id, pending_action, pending_value,
         return_screen, int(time.time())),
        "all", True,
    )


async def get_dashboard_state(message_id):
    return await _run(_q, "SELECT * FROM dashboard_state WHERE message_id=?", (message_id,), "one")
