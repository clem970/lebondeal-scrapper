from typing import Optional, Literal

import discord
from discord import app_commands
from discord.ext import commands

import database as db
import scheduler

UNIT_SECONDS = {"secondes": 1, "minutes": 60, "heures": 3600}


class SettingsCog(commands.Cog):
    parametres = app_commands.Group(
        name="parametres", description="Réglages globaux du bot pour ce serveur",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @parametres.command(name="credits_max", description="Plafond global de crédits consommables (0 = illimité)")
    async def credits_max(self, interaction: discord.Interaction, valeur: int):
        await db.update_settings(interaction.guild_id, global_max_credits=valeur if valeur > 0 else None)
        await interaction.response.send_message(f"💳 Plafond global de crédits = {valeur if valeur > 0 else 'illimité'}.")

    @parametres.command(name="reset_consommation", description="Remet à zéro le compteur de crédits consommés (global)")
    async def reset_consommation(self, interaction: discord.Interaction):
        await db.update_settings(interaction.guild_id, global_credits_used=0)
        await interaction.response.send_message("🔄 Compteur de crédits consommés remis à zéro.")

    @parametres.command(name="salon_unifie", description="Un seul salon pour recevoir TOUTES les annonces de TOUS les filtres")
    async def salon_unifie(self, interaction: discord.Interaction, salon: Optional[discord.TextChannel] = None):
        await db.update_settings(interaction.guild_id, unify_channel_id=salon.id if salon else None)
        txt = salon.mention if salon else "désactivé (chaque filtre garde son propre salon)"
        await interaction.response.send_message(f"📌 Salon unifié : {txt}")

    @parametres.command(name="salon_logs", description="Salon où le bot envoie ses erreurs et alertes de crédits")
    async def salon_logs(self, interaction: discord.Interaction, salon: Optional[discord.TextChannel] = None):
        await db.update_settings(interaction.guild_id, log_channel_id=salon.id if salon else None)
        txt = salon.mention if salon else "désactivé"
        await interaction.response.send_message(f"🪵 Salon de logs : {txt}")

    @parametres.command(name="alerte_credits", description="Alerte dans le salon de logs quand le solde passe sous ce seuil")
    async def alerte_credits(self, interaction: discord.Interaction, seuil: int):
        await db.update_settings(interaction.guild_id, low_credit_alert_threshold=seuil if seuil > 0 else None)
        await interaction.response.send_message(f"🔻 Seuil d'alerte crédits = {seuil if seuil > 0 else 'désactivé'}.")

    @parametres.command(name="intervalle_defaut", description="Intervalle par défaut proposé pour les nouveaux filtres")
    async def intervalle_defaut(self, interaction: discord.Interaction, valeur: int,
                                 unite: Literal["secondes", "minutes", "heures"] = "secondes"):
        await db.update_settings(interaction.guild_id, default_interval=valeur * UNIT_SECONDS[unite])
        await interaction.response.send_message(f"⏱️ Intervalle par défaut = {valeur} {unite}.")

    @parametres.command(name="pause", description="Met en pause / relance TOUS les filtres de ce serveur, tous sites confondus")
    async def pause(self, interaction: discord.Interaction, actif: bool):
        await db.update_settings(interaction.guild_id, paused=1 if actif else 0)
        await scheduler.sync()
        await interaction.response.send_message("⏸️ Pause globale activée." if actif else "▶️ Pause globale désactivée.")

    @app_commands.command(name="credits", description="Affiche le dernier solde de crédits connu")
    async def credits(self, interaction: discord.Interaction):
        row = await db.get_credits_remaining(interaction.guild_id)
        if not row or row.get("credits_remaining") is None:
            await interaction.response.send_message(
                "Solde inconnu pour l'instant — il sera mis à jour dès la première recherche effectuée "
                "(l'API ne fournit pas d'endpoint de solde dédié, seulement `credits_remaining` renvoyé après chaque recherche).",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"💳 Dernier solde connu : **{row['credits_remaining']}** crédits "
            f"(<t:{row['updated_at']}:R>)."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SettingsCog(bot))
