import discord
from discord import app_commands
from discord.ext import commands

import database as db
import views


class DashboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="dashboard", description="Ouvre le tableau de bord LeBonDeal (persistant, navigable par boutons)")
    @app_commands.default_permissions(manage_guild=True)
    async def dashboard(self, interaction: discord.Interaction):
        embed, view = await views.render_home(interaction.guild_id)
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        await db.save_dashboard_state(msg.id, interaction.guild_id, interaction.channel_id, "home")


async def setup(bot: commands.Bot):
    await bot.add_cog(DashboardCog(bot))
