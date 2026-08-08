import re
import discord

SITE_COLORS = {"vinted": 0x09B1BA, "leboncoin": 0xFF6E14, "kleinanzeigen": 0x0088CC}
SITE_LABELS = {"vinted": "Vinted", "leboncoin": "LeBonCoin", "kleinanzeigen": "Kleinanzeigen"}


def parse_price(price) -> float | None:
    if price is None:
        return None
    if isinstance(price, (int, float)):
        return float(price)
    match = re.search(r"[\d]+[.,]?\d*", str(price).replace("\xa0", " "))
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def build_ad_embed(site: str, item: dict, filter_name: str, style: str = "detailed") -> discord.Embed:
    price_txt = str(item.get("price")) if item.get("price") is not None else "N/A"
    embed = discord.Embed(
        title=item.get("title") or "Annonce sans titre",
        url=item.get("url"),
        color=SITE_COLORS.get(site, 0x2F3136),
    )
    embed.set_author(name=f"{SITE_LABELS.get(site, site)} · {filter_name}")
    embed.add_field(name="Prix", value=price_txt, inline=True)
    if item.get("location"):
        embed.add_field(name="Lieu", value=item["location"], inline=True)

    if style == "detailed":
        for label, value in (item.get("extra") or {}).items():
            if value:
                embed.add_field(name=label.capitalize(), value=str(value), inline=True)
        if item.get("image"):
            embed.set_image(url=item["image"])
    else:
        if item.get("image"):
            embed.set_thumbnail(url=item["image"])

    return embed


def build_dashboard_embed(guild_name, settings, filters, credits_row):
    embed = discord.Embed(title=f"📊 Dashboard LeBonDeal — {guild_name}", color=0x5865F2)
    active = sum(1 for f in filters if f["enabled"])
    by_site = {}
    for f in filters:
        by_site[f["site"]] = by_site.get(f["site"], 0) + 1
    site_txt = "\n".join(f"• {SITE_LABELS.get(s, s)} : {n}" for s, n in by_site.items()) or "Aucun filtre configuré."

    embed.add_field(name="Filtres", value=f"{active} actif(s) / {len(filters)} au total\n{site_txt}", inline=True)

    if credits_row and credits_row.get("credits_remaining") is not None:
        credits_txt = f"{credits_row['credits_remaining']} crédits (dernière valeur observée)"
    else:
        credits_txt = "Inconnu — sera mis à jour après la 1ère recherche.\n(l'API ne fournit pas d'endpoint de solde dédié)"
    embed.add_field(name="Crédits restants", value=credits_txt, inline=True)

    used = settings.get("global_credits_used", 0)
    cap = settings.get("global_max_credits")
    cap_txt = f"{used} / {cap}" if cap else f"{used} (aucun plafond global défini)"
    embed.add_field(name="Consommation globale", value=cap_txt, inline=True)

    if settings.get("paused"):
        embed.add_field(name="⏸️ État", value="Tous les filtres sont **en pause globale**.", inline=False)

    embed.set_footer(text="Utilise les commandes /filtre et /parametres pour la configuration détaillée.")
    return embed
