import asyncio
import random
import time
from datetime import datetime

import discord

import database as db
import api_client
from embeds import build_ad_embed, parse_price
from ratelimiter import rate_limiter

# id_filtre -> asyncio.Task
_tasks: dict[int, asyncio.Task] = {}
_bot = None


def init(bot):
    global _bot
    _bot = bot


def _in_quiet_hours(quiet_start, quiet_end) -> bool:
    if not quiet_start or not quiet_end:
        return False
    now = datetime.now().strftime("%H:%M")
    if quiet_start <= quiet_end:
        return quiet_start <= now < quiet_end
    return now >= quiet_start or now < quiet_end  # plage à cheval sur minuit


def _keyword_ok(title: str, include_kw, exclude_kw) -> bool:
    title_low = (title or "").lower()
    if include_kw:
        wanted = [w.strip().lower() for w in include_kw.split(",") if w.strip()]
        if wanted and not any(w in title_low for w in wanted):
            return False
    if exclude_kw:
        banned = [w.strip().lower() for w in exclude_kw.split(",") if w.strip()]
        if any(w in title_low for w in banned):
            return False
    return True


def _price_ok(price_val, min_price, max_price) -> bool:
    if price_val is None:
        return True  # on ne bloque pas une annonce dont le prix n'a pas pu être lu
    if min_price is not None and price_val < min_price:
        return False
    if max_price is not None and price_val > max_price:
        return False
    return True


async def _log(guild_id, message: str):
    settings = await db.get_settings(guild_id)
    channel_id = settings.get("log_channel_id")
    if not channel_id or _bot is None:
        return
    channel = _bot.get_channel(channel_id)
    if channel:
        try:
            await channel.send(message[:1900])
        except discord.HTTPException:
            pass


async def _send_item(f, site, item):
    embed = build_ad_embed(site, item, f["name"], f["embed_style"])
    content = None
    if f["ping_role_id"]:
        content = f"<@&{f['ping_role_id']}>"

    if f["channel_id"] and _bot:
        channel = _bot.get_channel(f["channel_id"])
        if channel:
            try:
                await channel.send(content=content, embed=embed)
            except discord.HTTPException:
                pass

    if f["dm_user_id"] and _bot:
        user = _bot.get_user(f["dm_user_id"]) or await _bot.fetch_user(f["dm_user_id"])
        if user:
            try:
                await user.send(embed=embed)
            except discord.HTTPException:
                pass


async def _tick(filter_id: int):
    f = await db.get_filter(filter_id)
    if f is None or not f["enabled"]:
        return

    settings = await db.get_settings(f["guild_id"])

    if settings.get("paused"):
        return
    if settings.get("global_max_credits") and settings["global_credits_used"] >= settings["global_max_credits"]:
        return
    if f["max_credits"] and f["credits_used"] >= f["max_credits"]:
        return
    if _in_quiet_hours(f["quiet_start"], f["quiet_end"]):
        return

    channel_id = f["channel_id"] or settings.get("unify_channel_id")

    await rate_limiter.acquire(f["site"])
    try:
        data = await api_client.search(f["site"], f["url"])
    except api_client.APIError as e:
        await db.update_filter(filter_id, last_run_at=int(time.time()), last_error=str(e))
        if e.error_code not in ("unexpected_error", "rate_limited"):
            await _log(f["guild_id"], f"⚠️ Filtre **{f['name']}** (#{filter_id}) : {e.message}")
        return
    except Exception as e:  # réseau, timeout, etc.
        await db.update_filter(filter_id, last_run_at=int(time.time()), last_error=str(e))
        return

    credits_charged = int(data.get("credits_charged", 0) or 0)
    credits_remaining = data.get("credits_remaining")
    if credits_remaining is not None:
        await db.log_credits_remaining(f["guild_id"], credits_remaining)
    if credits_charged:
        await db.add_credits_used(filter_id, f["guild_id"], credits_charged)

    threshold = settings.get("low_credit_alert_threshold")
    if threshold and credits_remaining is not None and credits_remaining <= threshold:
        await _log(f["guild_id"], f"🔻 Crédits restants faibles : **{credits_remaining}** (seuil {threshold}).")

    items = api_client.extract_items(f["site"], data)
    f_row = dict(f)
    f_row["channel_id"] = channel_id

    for item in items:
        if not item.get("id"):
            continue
        # Anti-doublonnage: toujours actif, non désactivable — évite de renvoyer 2x la même annonce.
        if await db.has_sent(filter_id, item["id"]):
            continue
        if not _keyword_ok(item.get("title"), f["include_keywords"], f["exclude_keywords"]):
            continue
        if not _price_ok(parse_price(item.get("price")), f["min_price"], f["max_price"]):
            continue

        await _send_item(f_row, f["site"], item)
        await db.mark_sent(filter_id, item["id"])

    await db.update_filter(filter_id, last_run_at=int(time.time()), last_error=None)


async def _loop(filter_id: int):
    try:
        while True:
            f = await db.get_filter(filter_id)
            if f is None or not f["enabled"]:
                return
            await _tick(filter_id)
            f = await db.get_filter(filter_id)
            base = f["interval_seconds"] if f else 60
            jitter_pct = (f["jitter_percent"] if f else 0) / 100
            jitter = base * jitter_pct * random.uniform(-1, 1)
            await asyncio.sleep(max(5, base + jitter))
    except asyncio.CancelledError:
        pass


async def sync():
    """Aligne les tâches en cours d'exécution sur l'état actuel de la base (à appeler après chaque changement)."""
    active = await db.list_all_active_filters()
    active_ids = {f["id"] for f in active}

    for fid in list(_tasks.keys()):
        if fid not in active_ids or _tasks[fid].done():
            _tasks[fid].cancel()
            _tasks.pop(fid, None)

    for f in active:
        if f["id"] not in _tasks:
            _tasks[f["id"]] = asyncio.create_task(_loop(f["id"]))


async def restart_filter(filter_id: int):
    """Force un cycle immédiat en réinitialisant le timer (relance)."""
    if filter_id in _tasks:
        _tasks[filter_id].cancel()
        _tasks.pop(filter_id, None)
    await db.reset_run(filter_id)
    await sync()
