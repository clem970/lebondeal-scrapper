import discord
from discord import app_commands
from discord.ext import commands

import database as db
import scheduler
from embeds import build_dashboard_embed
from cogs.filters import fmt_filter_line


class FilterSelect(discord.ui.Select):
    def __init__(self, filters: list[dict]):
        options = [
            discord.SelectOption(
                label=f"#{f['id']} {f['name'][:80]}",
                description=f"{f['site']} · {'actif' if f['enabled'] else 'inactif'}",
                value=str(f["id"]),
            )
            for f in filters[:25]
        ]
        super().__init__(placeholder="Activer/désactiver un filtre précis...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        filter_id = int(self.values[0])
        f = await db.get_filter(filter_id, interaction.guild_id)
        if not f:
            await interaction.response.send_message("Filtre introuvable.", ephemeral=True)
            return
        await db.set_enabled(filter_id, not f["enabled"])
        await scheduler.sync()
        await interaction.response.send_message(
            f"{'▶️ Activé' if not f['enabled'] else '⏸️ Désactivé'} : filtre `#{filter_id}` **{f['name']}**.",
            ephemeral=True,
        )


class DashboardView(discord.ui.View):
    def __init__(self, guild_id: int, filters: list[dict]):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        if filters:
            self.add_item(FilterSelect(filters))

    @discord.ui.button(label="Tout activer", style=discord.ButtonStyle.success, emoji="▶️")
    async def enable_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.set_enabled_all(self.guild_id, True)
        await scheduler.sync()
        await interaction.response.send_message("▶️ Tous les filtres ont été activés.", ephemeral=True)

    @discord.ui.button(label="Tout désactiver", style=discord.ButtonStyle.danger, emoji="⏸️")
    async def disable_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.set_enabled_all(self.guild_id, False)
        await scheduler.sync()
        await interaction.response.send_message("⏸️ Tous les filtres ont été désactivés.", ephemeral=True)

    @discord.ui.button(label="Rafraîchir", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await db.get_settings(self.guild_id)
        filters = await db.list_filters(self.guild_id)
        credits_row = await db.get_credits_remaining(self.guild_id)
        embed = build_dashboard_embed(interaction.guild.name, settings, filters, credits_row)
        view = DashboardView(self.guild_id, filters)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Voir la liste détaillée", style=discord.ButtonStyle.primary, emoji="🗂️")
    async def list_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        filters = await db.list_filters(self.guild_id)
        if not filters:
            await interaction.response.send_message("Aucun filtre configuré.", ephemeral=True)
            return
        lines = [fmt_filter_line(f) for f in filters]
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


class DashboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="dashboard", description="Affiche le tableau de bord LeBonDeal (crédits, filtres, actions rapides)")
    async def dashboard(self, interaction: discord.Interaction):
        settings = await db.get_settings(interaction.guild_id)
        filters = await db.list_filters(interaction.guild_id)
        credits_row = await db.get_credits_remaining(interaction.guild_id)
        embed = build_dashboard_embed(interaction.guild.name, settings, filters, credits_row)
        view = DashboardView(interaction.guild_id, filters)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(DashboardCog(bot))
