from typing import Optional, Literal

import discord
from discord import app_commands
from discord.ext import commands

import database as db
import scheduler
from site_detect import detect_site, is_valid_search_url

UNIT_SECONDS = {"secondes": 1, "minutes": 60, "heures": 3600}
SiteChoice = Literal["vinted", "leboncoin", "kleinanzeigen"]


def to_seconds(valeur: int, unite: str) -> int:
    return max(5, valeur * UNIT_SECONDS[unite])


def fmt_filter_line(f: dict) -> str:
    etat = "🟢" if f["enabled"] else "🔴"
    cible = f"<#{f['channel_id']}>" if f["channel_id"] else ("DM" if f["dm_user_id"] else "aucune cible")
    return f"{etat} `#{f['id']}` **{f['name']}** ({f['site']}) · {f['interval_seconds']}s · → {cible}"


class FiltersCog(commands.Cog):
    filtre = app_commands.Group(
        name="filtre", description="Gérer les filtres de recherche Vinted/LeBonCoin/Kleinanzeigen",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _resync(self):
        await scheduler.sync()

    # ---------- création / suppression ----------

    @filtre.command(name="ajouter", description="Ajoute un filtre à partir d'un lien Vinted/LeBonCoin/Kleinanzeigen")
    @app_commands.describe(
        url="Lien de recherche copié depuis le site (peu importe lequel des 3 sites)",
        nom="Nom du filtre (affiché dans les annonces)",
        salon="Salon où envoyer les annonces (facultatif si DM ou salon unifié configuré)",
        dm="Envoyer aussi les annonces en message privé à cet utilisateur (facultatif)",
        intervalle="Fréquence de scan",
        unite="Unité de l'intervalle",
    )
    async def ajouter(
        self, interaction: discord.Interaction, url: str, nom: str,
        salon: Optional[discord.TextChannel] = None,
        dm: Optional[discord.User] = None,
        intervalle: int = 60,
        unite: Literal["secondes", "minutes", "heures"] = "secondes",
    ):
        site = detect_site(url)
        if site is None:
            await interaction.response.send_message(
                "❌ Ce lien ne correspond à aucun des 3 sites gérés (vinted.fr, leboncoin.fr, kleinanzeigen.de).",
                ephemeral=True,
            )
            return
        if not is_valid_search_url(url, site):
            await interaction.response.send_message(
                f"❌ Ce lien {site} ressemble à une fiche annonce, pas à une page de résultats de recherche.",
                ephemeral=True,
            )
            return

        interval_seconds = to_seconds(intervalle, unite)
        filter_id = await db.add_filter(
            interaction.guild_id, nom, site, url, interval_seconds,
            channel_id=salon.id if salon else None,
            dm_user_id=dm.id if dm else None,
        )
        await self._resync()
        await interaction.response.send_message(
            f"✅ Filtre **{nom}** créé (`#{filter_id}`, site **{site}**, scan toutes les {intervalle} {unite})."
        )

    @filtre.command(name="supprimer", description="Supprime un filtre")
    async def supprimer(self, interaction: discord.Interaction, id: int):
        f = await db.get_filter(id, interaction.guild_id)
        if not f:
            await interaction.response.send_message("❌ Filtre introuvable.", ephemeral=True)
            return
        await db.delete_filter(id)
        await self._resync()
        await interaction.response.send_message(f"🗑️ Filtre `#{id}` supprimé.")

    @filtre.command(name="supprimer_tout", description="Supprime tous les filtres (ou ceux d'un site)")
    async def supprimer_tout(self, interaction: discord.Interaction, site: Optional[SiteChoice] = None):
        await db.delete_all_filters(interaction.guild_id, site)
        await self._resync()
        cible = site or "tous les sites"
        await interaction.response.send_message(f"🗑️ Tous les filtres ({cible}) ont été supprimés.")

    # ---------- activer / désactiver / relancer ----------

    @filtre.command(name="activer", description="Active un filtre")
    async def activer(self, interaction: discord.Interaction, id: int):
        await db.set_enabled(id, True)
        await self._resync()
        await interaction.response.send_message(f"▶️ Filtre `#{id}` activé.")

    @filtre.command(name="desactiver", description="Désactive un filtre")
    async def desactiver(self, interaction: discord.Interaction, id: int):
        await db.set_enabled(id, False)
        await self._resync()
        await interaction.response.send_message(f"⏸️ Filtre `#{id}` désactivé.")

    @filtre.command(name="activer_tout", description="Active tous les filtres (ou ceux d'un site)")
    async def activer_tout(self, interaction: discord.Interaction, site: Optional[SiteChoice] = None):
        await db.set_enabled_all(interaction.guild_id, True, site)
        await self._resync()
        await interaction.response.send_message(f"▶️ Tous les filtres ({site or 'tous les sites'}) activés.")

    @filtre.command(name="desactiver_tout", description="Désactive tous les filtres (ou ceux d'un site)")
    async def desactiver_tout(self, interaction: discord.Interaction, site: Optional[SiteChoice] = None):
        await db.set_enabled_all(interaction.guild_id, False, site)
        await self._resync()
        await interaction.response.send_message(f"⏸️ Tous les filtres ({site or 'tous les sites'}) désactivés.")

    @filtre.command(name="relancer", description="Relance immédiatement un filtre (reset du minuteur)")
    async def relancer(self, interaction: discord.Interaction, id: int):
        f = await db.get_filter(id, interaction.guild_id)
        if not f:
            await interaction.response.send_message("❌ Filtre introuvable.", ephemeral=True)
            return
        await scheduler.restart_filter(id)
        await interaction.response.send_message(f"🔄 Filtre `#{id}` relancé.")

    @filtre.command(name="relancer_tout", description="Relance tous les filtres actifs")
    async def relancer_tout(self, interaction: discord.Interaction):
        filters = await db.list_filters(interaction.guild_id)
        for f in filters:
            if f["enabled"]:
                await db.reset_run(f["id"])
        await self._resync()
        await interaction.response.send_message("🔄 Tous les filtres actifs ont été relancés.")

    # ---------- réglages individuels ----------

    @filtre.command(name="intervalle", description="Change la vitesse de scan d'un filtre")
    async def intervalle(self, interaction: discord.Interaction, id: int, valeur: int,
                          unite: Literal["secondes", "minutes", "heures"] = "secondes"):
        await db.update_filter(id, interval_seconds=to_seconds(valeur, unite))
        await interaction.response.send_message(f"⏱️ Filtre `#{id}` : scan toutes les {valeur} {unite}.")

    @filtre.command(name="salon", description="Définit (ou retire) le salon de destination d'un filtre")
    async def salon(self, interaction: discord.Interaction, id: int, salon: Optional[discord.TextChannel] = None):
        await db.update_filter(id, channel_id=salon.id if salon else None)
        txt = salon.mention if salon else "aucun (utilisera le salon unifié si défini)"
        await interaction.response.send_message(f"📌 Filtre `#{id}` → salon : {txt}")

    @filtre.command(name="dm", description="Active/désactive l'envoi en message privé pour un filtre")
    async def dm(self, interaction: discord.Interaction, id: int, utilisateur: Optional[discord.User] = None):
        await db.update_filter(id, dm_user_id=utilisateur.id if utilisateur else None)
        txt = utilisateur.mention if utilisateur else "désactivé"
        await interaction.response.send_message(f"💌 Filtre `#{id}` → DM : {txt}")

    @filtre.command(name="heures_creuses", description="Coupe automatiquement le filtre entre 2 heures (HH:MM)")
    async def heures_creuses(self, interaction: discord.Interaction, id: int,
                              debut: Optional[str] = None, fin: Optional[str] = None):
        if debut is None or fin is None:
            await db.update_filter(id, quiet_start=None, quiet_end=None)
            await interaction.response.send_message(f"🕒 Filtre `#{id}` : plage de coupure retirée.")
            return
        await db.update_filter(id, quiet_start=debut, quiet_end=fin)
        await interaction.response.send_message(f"🕒 Filtre `#{id}` : coupé entre {debut} et {fin} chaque jour.")

    @filtre.command(name="prix", description="Filtre par prix min/max (annonces reçues via l'API mais non renvoyées si hors plage)")
    async def prix(self, interaction: discord.Interaction, id: int,
                    min: Optional[float] = None, max: Optional[float] = None):
        await db.update_filter(id, min_price=min, max_price=max)
        await interaction.response.send_message(f"💰 Filtre `#{id}` : prix entre {min or '—'} et {max or '—'}.")

    @filtre.command(name="motscles", description="Mots-clés à inclure / exclure (séparés par des virgules)")
    async def motscles(self, interaction: discord.Interaction, id: int,
                        inclure: Optional[str] = None, exclure: Optional[str] = None):
        await db.update_filter(id, include_keywords=inclure, exclude_keywords=exclure)
        await interaction.response.send_message(f"🔎 Filtre `#{id}` : inclure=`{inclure or '—'}` exclure=`{exclure or '—'}`")

    @filtre.command(name="role", description="Rôle à ping quand une annonce est envoyée dans le salon")
    async def role(self, interaction: discord.Interaction, id: int, role: Optional[discord.Role] = None):
        await db.update_filter(id, ping_role_id=role.id if role else None)
        await interaction.response.send_message(f"🔔 Filtre `#{id}` : rôle ping = {role.mention if role else 'aucun'}")

    @filtre.command(name="style", description="Style d'affichage des annonces (compact ou détaillé)")
    async def style(self, interaction: discord.Interaction, id: int, style: Literal["compact", "detailed"]):
        await db.update_filter(id, embed_style=style)
        await interaction.response.send_message(f"🎨 Filtre `#{id}` : style = {style}.")

    @filtre.command(name="dedoublonnage", description="Active/désactive l'anti-doublon pour ce filtre")
    async def dedoublonnage(self, interaction: discord.Interaction, id: int, actif: bool):
        await db.update_filter(id, dedup=1 if actif else 0)
        await interaction.response.send_message(f"♻️ Filtre `#{id}` : anti-doublon {'activé' if actif else 'désactivé'}.")

    @filtre.command(name="credits_max", description="Plafond de crédits consommables par CE filtre (0 = illimité)")
    async def credits_max(self, interaction: discord.Interaction, id: int, valeur: int):
        await db.update_filter(id, max_credits=valeur if valeur > 0 else None)
        await interaction.response.send_message(f"💳 Filtre `#{id}` : plafond crédits = {valeur if valeur > 0 else 'illimité'}.")

    # ---------- liste ----------

    @filtre.command(name="liste", description="Liste tous les filtres du serveur")
    async def liste(self, interaction: discord.Interaction, site: Optional[SiteChoice] = None):
        filters = await db.list_filters(interaction.guild_id, site)
        if not filters:
            await interaction.response.send_message("Aucun filtre configuré.", ephemeral=True)
            return
        lines = [fmt_filter_line(f) for f in filters]
        embed = discord.Embed(title="🗂️ Filtres", description="\n".join(lines), color=0x5865F2)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(FiltersCog(bot))
