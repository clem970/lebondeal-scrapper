import discord

import database as db
import scheduler
from embeds import build_dashboard_embed
from site_detect import detect_site, is_valid_search_url
from parsing import parse_interval, format_interval, to_float, to_int, TIME_RE

_bot = None


def init(bot):
    global _bot
    _bot = bot


EMPTY_FILTER = {
    "id": 0, "name": "-", "site": "vinted", "url": "", "enabled": 0,
    "interval_seconds": 60, "channel_id": None, "dm_user_id": None, "ping_role_id": None,
    "quiet_start": None, "quiet_end": None, "min_price": None, "max_price": None,
    "include_keywords": None, "exclude_keywords": None, "embed_style": "detailed",
    "credits_used": 0, "max_credits": None, "last_error": None,
}

ACTION_LABELS = {
    "enable": "✅ Activer les filtres sélectionnés",
    "disable": "⛔ Désactiver les filtres sélectionnés",
    "delete": "🗑️ Supprimer les filtres sélectionnés (irréversible)",
    "interval": "🚀 Appliquer une nouvelle vitesse de scan",
    "credits_max": "💳 Appliquer un plafond de crédits",
}


def _default(snowflake_id):
    return [discord.Object(id=snowflake_id)] if snowflake_id else discord.utils.MISSING


# ---------- navigation générique ----------

async def navigate(interaction: discord.Interaction, screen: str, **kwargs):
    guild_id = interaction.guild_id
    embed, view = await RENDERERS[screen](guild_id, **kwargs)
    await interaction.response.edit_message(embed=embed, view=view)
    await db.save_dashboard_state(
        interaction.message.id, guild_id, interaction.channel_id, screen,
        filter_id=kwargs.get("filter_id"),
        pending_action=kwargs.get("pending_action"),
        pending_value=kwargs.get("pending_value"),
        return_screen=kwargs.get("return_screen"),
    )


async def refresh_detail(interaction: discord.Interaction, filter_id: int):
    embed, view = await render_filter_detail(interaction.guild_id, filter_id=filter_id)
    await interaction.response.edit_message(embed=embed, view=view)
    await db.save_dashboard_state(interaction.message.id, interaction.guild_id, interaction.channel_id,
                                   "filter_detail", filter_id=filter_id)


# ==================== ACCUEIL ====================

class HomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Filtres", emoji="🗂️", style=discord.ButtonStyle.primary, custom_id="lbd:home:filtres", row=0)
    async def btn_filtres(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "filters_list")

    @discord.ui.button(label="Destinations", emoji="🎯", style=discord.ButtonStyle.primary, custom_id="lbd:home:destinations", row=0)
    async def btn_dest(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "destinations")

    @discord.ui.button(label="Planification", emoji="⏱️", style=discord.ButtonStyle.primary, custom_id="lbd:home:planning", row=0)
    async def btn_planning(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "planning")

    @discord.ui.button(label="Limitations", emoji="💳", style=discord.ButtonStyle.primary, custom_id="lbd:home:limits", row=1)
    async def btn_limits(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "limits")

    @discord.ui.button(label="Avancé", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="lbd:home:advanced", row=1)
    async def btn_advanced(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "advanced")

    @discord.ui.button(label="Rafraîchir", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="lbd:home:refresh", row=1)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "home")


async def render_home(guild_id, **_):
    settings = await db.get_settings(guild_id)
    filters = await db.list_filters(guild_id)
    credits_row = await db.get_credits_remaining(guild_id)
    guild = _bot.get_guild(guild_id) if _bot else None
    embed = build_dashboard_embed(guild.name if guild else "Serveur", settings, filters, credits_row)
    return embed, HomeView()


# ==================== LISTE DES FILTRES ====================

class FilterPickSelect(discord.ui.Select):
    def __init__(self, filters):
        if filters:
            options = [
                discord.SelectOption(
                    label=f"#{f['id']} {f['name'][:80]}",
                    description=f"{f['site']} · {'actif' if f['enabled'] else 'inactif'}",
                    value=str(f["id"]),
                ) for f in filters[:25]
            ]
        else:
            options = [discord.SelectOption(label="Aucun filtre — clique sur Ajouter", value="none")]
        super().__init__(placeholder="Voir / modifier un filtre précis...", options=options,
                          min_values=1, max_values=1, custom_id="lbd:filters:pick", row=0)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.defer()
            return
        await navigate(interaction, "filter_detail", filter_id=int(self.values[0]))


class AddFilterModal(discord.ui.Modal, title="Ajouter un filtre"):
    nom = discord.ui.TextInput(label="Nom du filtre", max_length=80, placeholder="ex: iPhone 13 pas cher")
    url = discord.ui.TextInput(label="Lien de recherche (vinted/leboncoin/kleinanzeigen)",
                                placeholder="https://www.vinted.fr/catalog?search_text=...")
    intervalle = discord.ui.TextInput(label="Vitesse de scan", default="60 secondes",
                                       placeholder="ex: 60 secondes / 5 minutes / 1 heures")

    async def on_submit(self, interaction: discord.Interaction):
        site = detect_site(self.url.value)
        if site is None:
            await interaction.response.send_message(
                "❌ Ce lien ne correspond à aucun des 3 sites gérés (vinted.fr, leboncoin.fr, kleinanzeigen.de).",
                ephemeral=True)
            return
        if not is_valid_search_url(self.url.value, site):
            await interaction.response.send_message(
                f"❌ Ce lien {site} ressemble à une fiche annonce, pas à une page de résultats.", ephemeral=True)
            return
        seconds = parse_interval(self.intervalle.value)
        if seconds is None:
            await interaction.response.send_message(
                "❌ Format de vitesse invalide. Exemple : `60 secondes`, `5 minutes`, `1 heures`.", ephemeral=True)
            return
        await db.add_filter(interaction.guild_id, self.nom.value, site, self.url.value, seconds)
        await scheduler.sync()
        embed, view = await render_filters_list(interaction.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)
        await db.save_dashboard_state(interaction.message.id, interaction.guild_id, interaction.channel_id, "filters_list")


class FiltersListView(discord.ui.View):
    def __init__(self, filters):
        super().__init__(timeout=None)
        self.add_item(FilterPickSelect(filters))

    @discord.ui.button(label="Ajouter", emoji="➕", style=discord.ButtonStyle.success, custom_id="lbd:filters:add", row=1)
    async def btn_add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddFilterModal())

    @discord.ui.button(label="Activer plusieurs", emoji="▶️", style=discord.ButtonStyle.success, custom_id="lbd:filters:group_enable", row=1)
    async def btn_group_enable(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "group_action", pending_action="enable", return_screen="filters_list")

    @discord.ui.button(label="Désactiver plusieurs", emoji="⏸️", style=discord.ButtonStyle.danger, custom_id="lbd:filters:group_disable", row=1)
    async def btn_group_disable(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "group_action", pending_action="disable", return_screen="filters_list")

    @discord.ui.button(label="Supprimer plusieurs", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="lbd:filters:group_delete", row=2)
    async def btn_group_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "group_action", pending_action="delete", return_screen="filters_list")

    @discord.ui.button(label="Retour", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="lbd:filters:back", row=2)
    async def btn_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "home")


async def render_filters_list(guild_id, **_):
    filters = await db.list_filters(guild_id)
    if filters:
        lines = []
        for f in filters:
            etat = "🟢" if f["enabled"] else "🔴"
            cible = f"<#{f['channel_id']}>" if f["channel_id"] else ("DM" if f["dm_user_id"] else "salon unifié / aucune")
            lines.append(f"{etat} `#{f['id']}` **{f['name']}** ({f['site']}) · {format_interval(f['interval_seconds'])} · → {cible}")
        desc = "\n".join(lines)
    else:
        desc = "Aucun filtre configuré pour l'instant. Clique sur **Ajouter** pour en créer un."
    embed = discord.Embed(title="🗂️ Filtres", description=desc, color=0x5865F2)
    return embed, FiltersListView(filters)


# ==================== DÉTAIL D'UN FILTRE ====================

class FilterChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, f):
        super().__init__(placeholder="Salon dédié (vide = utilise le salon unifié si défini)",
                          channel_types=[discord.ChannelType.text], min_values=0, max_values=1,
                          custom_id="lbd:detail:channel_select", row=2,
                          default_values=_default(f.get("channel_id")))

    async def callback(self, interaction: discord.Interaction):
        state = await db.get_dashboard_state(interaction.message.id)
        channel_id = self.values[0].id if self.values else None
        await db.update_filter(state["filter_id"], channel_id=channel_id)
        await refresh_detail(interaction, state["filter_id"])


class FilterRoleSelect(discord.ui.RoleSelect):
    def __init__(self, f):
        super().__init__(placeholder="Rôle à ping (facultatif)", min_values=0, max_values=1,
                          custom_id="lbd:detail:role_select", row=3,
                          default_values=_default(f.get("ping_role_id")))

    async def callback(self, interaction: discord.Interaction):
        state = await db.get_dashboard_state(interaction.message.id)
        role_id = self.values[0].id if self.values else None
        await db.update_filter(state["filter_id"], ping_role_id=role_id)
        await refresh_detail(interaction, state["filter_id"])


class FilterDMSelect(discord.ui.UserSelect):
    def __init__(self, f):
        super().__init__(placeholder="Envoyer aussi en DM à... (facultatif)", min_values=0, max_values=1,
                          custom_id="lbd:detail:dm_select", row=4,
                          default_values=_default(f.get("dm_user_id")))

    async def callback(self, interaction: discord.Interaction):
        state = await db.get_dashboard_state(interaction.message.id)
        user_id = self.values[0].id if self.values else None
        await db.update_filter(state["filter_id"], dm_user_id=user_id)
        await refresh_detail(interaction, state["filter_id"])


class FilterSettingsModal(discord.ui.Modal, title="Réglages du filtre"):
    def __init__(self, f):
        super().__init__()
        self.filter_id = f["id"]
        self.intervalle = discord.ui.TextInput(label="Vitesse (ex: 60 secondes / 5 minutes)",
                                                default=format_interval(f["interval_seconds"]))
        self.prix_min = discord.ui.TextInput(label="Prix minimum (vide = aucun)", required=False,
                                              default="" if f["min_price"] is None else str(f["min_price"]))
        self.prix_max = discord.ui.TextInput(label="Prix maximum (vide = aucun)", required=False,
                                              default="" if f["max_price"] is None else str(f["max_price"]))
        self.inclure = discord.ui.TextInput(label="Mots-clés à inclure (séparés par ,)", required=False,
                                             default=f["include_keywords"] or "")
        self.exclure = discord.ui.TextInput(label="Mots-clés à exclure (séparés par ,)", required=False,
                                             default=f["exclude_keywords"] or "")
        for item in (self.intervalle, self.prix_min, self.prix_max, self.inclure, self.exclure):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        seconds = parse_interval(self.intervalle.value)
        if seconds is None:
            await interaction.response.send_message("❌ Format de vitesse invalide.", ephemeral=True)
            return
        try:
            min_p, max_p = to_float(self.prix_min.value), to_float(self.prix_max.value)
        except ValueError:
            await interaction.response.send_message("❌ Prix invalide.", ephemeral=True)
            return
        await db.update_filter(
            self.filter_id, interval_seconds=seconds, min_price=min_p, max_price=max_p,
            include_keywords=self.inclure.value or None, exclude_keywords=self.exclure.value or None,
        )
        await refresh_detail(interaction, self.filter_id)


class QuietHoursModal(discord.ui.Modal, title="Heures creuses"):
    def __init__(self, f):
        super().__init__()
        self.filter_id = f["id"]
        self.debut = discord.ui.TextInput(label="Début (HH:MM, vide = désactivé)", required=False,
                                           default=f["quiet_start"] or "")
        self.fin = discord.ui.TextInput(label="Fin (HH:MM)", required=False, default=f["quiet_end"] or "")
        self.add_item(self.debut)
        self.add_item(self.fin)

    async def on_submit(self, interaction: discord.Interaction):
        debut, fin = self.debut.value.strip(), self.fin.value.strip()
        if not debut or not fin:
            await db.update_filter(self.filter_id, quiet_start=None, quiet_end=None)
        else:
            if not TIME_RE.match(debut) or not TIME_RE.match(fin):
                await interaction.response.send_message("❌ Format attendu HH:MM (ex: 23:00).", ephemeral=True)
                return
            await db.update_filter(self.filter_id, quiet_start=debut, quiet_end=fin)
        await refresh_detail(interaction, self.filter_id)


class FilterCreditsModal(discord.ui.Modal, title="Plafond de crédits du filtre"):
    def __init__(self, f):
        super().__init__()
        self.filter_id = f["id"]
        self.valeur = discord.ui.TextInput(label="Plafond (0 = illimité)", default=str(f["max_credits"] or 0))
        self.add_item(self.valeur)

    async def on_submit(self, interaction: discord.Interaction):
        v = to_int(self.valeur.value)
        if v is None:
            await interaction.response.send_message("❌ Nombre entier attendu.", ephemeral=True)
            return
        await db.update_filter(self.filter_id, max_credits=v if v > 0 else None)
        await refresh_detail(interaction, self.filter_id)


class FilterDetailView(discord.ui.View):
    def __init__(self, f):
        super().__init__(timeout=None)
        self.toggle.label = "Désactiver" if f["enabled"] else "Activer"
        self.toggle.emoji = "⏸️" if f["enabled"] else "▶️"
        self.toggle.style = discord.ButtonStyle.danger if f["enabled"] else discord.ButtonStyle.success
        self.style_btn.label = "Style: compact" if f["embed_style"] == "detailed" else "Style: détaillé"
        self.add_item(FilterChannelSelect(f))
        self.add_item(FilterRoleSelect(f))
        self.add_item(FilterDMSelect(f))

    @discord.ui.button(custom_id="lbd:detail:toggle", row=0)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await db.get_dashboard_state(interaction.message.id)
        f = await db.get_filter(state["filter_id"])
        await db.set_enabled(f["id"], not f["enabled"])
        await scheduler.sync()
        await refresh_detail(interaction, f["id"])

    @discord.ui.button(label="Relancer", emoji="🔄", style=discord.ButtonStyle.primary, custom_id="lbd:detail:restart", row=0)
    async def restart(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await db.get_dashboard_state(interaction.message.id)
        await scheduler.restart_filter(state["filter_id"])
        await refresh_detail(interaction, state["filter_id"])

    @discord.ui.button(emoji="🎨", style=discord.ButtonStyle.secondary, custom_id="lbd:detail:style", row=0)
    async def style_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await db.get_dashboard_state(interaction.message.id)
        f = await db.get_filter(state["filter_id"])
        await db.update_filter(f["id"], embed_style="compact" if f["embed_style"] == "detailed" else "detailed")
        await refresh_detail(interaction, f["id"])

    @discord.ui.button(label="Supprimer", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="lbd:detail:delete", row=0)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await db.get_dashboard_state(interaction.message.id)
        await db.delete_filter(state["filter_id"])
        await scheduler.sync()
        await navigate(interaction, "filters_list")

    @discord.ui.button(label="Réglages", emoji="⚙️", style=discord.ButtonStyle.primary, custom_id="lbd:detail:settings", row=1)
    async def settings_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await db.get_dashboard_state(interaction.message.id)
        f = await db.get_filter(state["filter_id"])
        await interaction.response.send_modal(FilterSettingsModal(f))

    @discord.ui.button(label="Heures creuses", emoji="🕒", style=discord.ButtonStyle.secondary, custom_id="lbd:detail:quiet", row=1)
    async def quiet_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await db.get_dashboard_state(interaction.message.id)
        f = await db.get_filter(state["filter_id"])
        await interaction.response.send_modal(QuietHoursModal(f))

    @discord.ui.button(label="Plafond crédits", emoji="💳", style=discord.ButtonStyle.secondary, custom_id="lbd:detail:credits", row=1)
    async def credits_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await db.get_dashboard_state(interaction.message.id)
        f = await db.get_filter(state["filter_id"])
        await interaction.response.send_modal(FilterCreditsModal(f))

    @discord.ui.button(label="Retour", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="lbd:detail:back", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "filters_list")


def _filter_detail_embed(f) -> discord.Embed:
    embed = discord.Embed(title=f"🗂️ Filtre #{f['id']} — {f['name']}", color=0x5865F2)
    embed.add_field(name="Site", value=f["site"], inline=True)
    embed.add_field(name="État", value="🟢 Actif" if f["enabled"] else "🔴 Inactif", inline=True)
    embed.add_field(name="Vitesse", value=format_interval(f["interval_seconds"]), inline=True)
    embed.add_field(name="Salon", value=f"<#{f['channel_id']}>" if f["channel_id"] else "— (salon unifié si défini)", inline=True)
    embed.add_field(name="DM", value=f"<@{f['dm_user_id']}>" if f["dm_user_id"] else "désactivé", inline=True)
    embed.add_field(name="Rôle ping", value=f"<@&{f['ping_role_id']}>" if f["ping_role_id"] else "aucun", inline=True)
    embed.add_field(name="Heures creuses", value=f"{f['quiet_start']} → {f['quiet_end']}" if f["quiet_start"] else "aucune", inline=True)
    embed.add_field(name="Prix", value=f"{f['min_price'] if f['min_price'] is not None else '—'} à "
                                        f"{f['max_price'] if f['max_price'] is not None else '—'}", inline=True)
    used, cap = f["credits_used"], f["max_credits"]
    embed.add_field(name="Crédits utilisés", value=f"{used} / {cap}" if cap else f"{used} (illimité)", inline=True)
    embed.add_field(name="Mots-clés", value=f"inclure : {f['include_keywords'] or '—'}\nexclure : {f['exclude_keywords'] or '—'}", inline=False)
    embed.add_field(name="Style d'affichage", value=f["embed_style"], inline=True)
    embed.add_field(name="Anti-doublon", value="🔒 toujours actif", inline=True)
    if f.get("last_error"):
        embed.add_field(name="Dernière erreur", value=str(f["last_error"])[:200], inline=False)
    embed.set_footer(text=(f["url"] or "")[:250])
    return embed


class FiltersListBackStub(discord.ui.View):
    """Vue de secours si le filtre affiché a été supprimé entre-temps."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Retour", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="lbd:detail:back_missing")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "filters_list")


async def render_filter_detail(guild_id, filter_id=None, **_):
    f = await db.get_filter(filter_id, guild_id) if filter_id else None
    if not f:
        embed = discord.Embed(title="❌ Filtre introuvable", description="Il a peut-être été supprimé.", color=0xED4245)
        return embed, FiltersListBackStub()
    return _filter_detail_embed(f), FilterDetailView(f)


# ==================== DESTINATIONS ====================

class UnifyChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, settings):
        super().__init__(placeholder="Salon unifié pour tous les filtres sans salon dédié",
                          channel_types=[discord.ChannelType.text], min_values=0, max_values=1,
                          custom_id="lbd:dest:unify_select", row=0,
                          default_values=_default(settings.get("unify_channel_id")))

    async def callback(self, interaction: discord.Interaction):
        channel_id = self.values[0].id if self.values else None
        await db.update_settings(interaction.guild_id, unify_channel_id=channel_id)
        await navigate(interaction, "destinations")


class DestinationsView(discord.ui.View):
    def __init__(self, settings):
        super().__init__(timeout=None)
        self.add_item(UnifyChannelSelect(settings))

    @discord.ui.button(label="Retour", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="lbd:dest:back", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "home")


async def render_destinations(guild_id, **_):
    settings = await db.get_settings(guild_id)
    unify = f"<#{settings['unify_channel_id']}>" if settings.get("unify_channel_id") else "aucun"
    embed = discord.Embed(
        title="🎯 Destinations",
        description=(f"**Salon unifié actuel :** {unify}\n\n"
                      "Ce salon reçoit les annonces de tous les filtres qui n'ont **pas** de salon dédié.\n"
                      "Un filtre avec son propre salon (réglé dans `Filtres > (le filtre) > Salon dédié`) "
                      "garde toujours la priorité, même si un salon unifié est défini ici."),
        color=0x5865F2,
    )
    return embed, DestinationsView(settings)


# ==================== PLANIFICATION ====================

class DefaultIntervalModal(discord.ui.Modal, title="Intervalle par défaut"):
    valeur = discord.ui.TextInput(label="Vitesse (ex: 60 secondes / 5 minutes)", default="60 secondes")

    async def on_submit(self, interaction: discord.Interaction):
        seconds = parse_interval(self.valeur.value)
        if seconds is None:
            await interaction.response.send_message("❌ Format invalide.", ephemeral=True)
            return
        await db.update_settings(interaction.guild_id, default_interval=seconds)
        await navigate(interaction, "planning")


class GroupIntervalModal(discord.ui.Modal, title="Vitesse — plusieurs filtres"):
    valeur = discord.ui.TextInput(label="Nouvelle vitesse (ex: 5 minutes)", default="60 secondes")

    async def on_submit(self, interaction: discord.Interaction):
        seconds = parse_interval(self.valeur.value)
        if seconds is None:
            await interaction.response.send_message("❌ Format invalide.", ephemeral=True)
            return
        await navigate(interaction, "group_action", pending_action="interval",
                        pending_value=str(seconds), return_screen="planning")


class PlanningView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Intervalle par défaut", emoji="⏱️", style=discord.ButtonStyle.primary, custom_id="lbd:planning:default_interval", row=0)
    async def default_interval(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DefaultIntervalModal())

    @discord.ui.button(label="Vitesse — plusieurs filtres", emoji="🚀", style=discord.ButtonStyle.primary, custom_id="lbd:planning:group_interval", row=0)
    async def group_interval(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GroupIntervalModal())

    @discord.ui.button(label="Retour", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="lbd:planning:back", row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "home")


async def render_planning(guild_id, **_):
    settings = await db.get_settings(guild_id)
    embed = discord.Embed(
        title="⏱️ Planification",
        description=(f"**Intervalle par défaut (nouveaux filtres) :** {format_interval(settings['default_interval'])}\n\n"
                      "Les heures creuses se règlent filtre par filtre, dans `Filtres > (le filtre) > Heures creuses`."),
        color=0x5865F2,
    )
    return embed, PlanningView()


# ==================== LIMITATIONS ====================

class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, settings):
        super().__init__(placeholder="Salon de logs (erreurs, alertes de crédits)",
                          channel_types=[discord.ChannelType.text], min_values=0, max_values=1,
                          custom_id="lbd:limits:log_select", row=2,
                          default_values=_default(settings.get("log_channel_id")))

    async def callback(self, interaction: discord.Interaction):
        channel_id = self.values[0].id if self.values else None
        await db.update_settings(interaction.guild_id, log_channel_id=channel_id)
        await navigate(interaction, "limits")


class GlobalCreditsModal(discord.ui.Modal, title="Plafond global de crédits"):
    valeur = discord.ui.TextInput(label="Plafond (0 = illimité)", default="0")

    async def on_submit(self, interaction: discord.Interaction):
        v = to_int(self.valeur.value)
        if v is None:
            await interaction.response.send_message("❌ Nombre entier attendu.", ephemeral=True)
            return
        await db.update_settings(interaction.guild_id, global_max_credits=v if v > 0 else None)
        await navigate(interaction, "limits")


class GroupCreditsModal(discord.ui.Modal, title="Plafond crédits — plusieurs filtres"):
    valeur = discord.ui.TextInput(label="Plafond (0 = illimité)", default="0")

    async def on_submit(self, interaction: discord.Interaction):
        v = to_int(self.valeur.value)
        if v is None:
            await interaction.response.send_message("❌ Nombre entier attendu.", ephemeral=True)
            return
        await navigate(interaction, "group_action", pending_action="credits_max",
                        pending_value=str(v), return_screen="limits")


class AlertThresholdModal(discord.ui.Modal, title="Seuil d'alerte crédits"):
    valeur = discord.ui.TextInput(label="Seuil (0 = désactivé)", default="0")

    async def on_submit(self, interaction: discord.Interaction):
        v = to_int(self.valeur.value)
        if v is None:
            await interaction.response.send_message("❌ Nombre entier attendu.", ephemeral=True)
            return
        await db.update_settings(interaction.guild_id, low_credit_alert_threshold=v if v > 0 else None)
        await navigate(interaction, "limits")


class LimitsView(discord.ui.View):
    def __init__(self, settings):
        super().__init__(timeout=None)
        self.add_item(LogChannelSelect(settings))

    @discord.ui.button(label="Plafond global", emoji="💳", style=discord.ButtonStyle.primary, custom_id="lbd:limits:global_cap", row=0)
    async def global_cap(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GlobalCreditsModal())

    @discord.ui.button(label="Réinitialiser conso.", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="lbd:limits:reset", row=0)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.update_settings(interaction.guild_id, global_credits_used=0)
        await navigate(interaction, "limits")

    @discord.ui.button(label="Plafond — plusieurs filtres", emoji="💳", style=discord.ButtonStyle.primary, custom_id="lbd:limits:group_cap", row=1)
    async def group_cap(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GroupCreditsModal())

    @discord.ui.button(label="Seuil d'alerte", emoji="🔻", style=discord.ButtonStyle.secondary, custom_id="lbd:limits:threshold", row=1)
    async def threshold(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AlertThresholdModal())

    @discord.ui.button(label="Retour", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="lbd:limits:back", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "home")


async def render_limits(guild_id, **_):
    settings = await db.get_settings(guild_id)
    cap = settings.get("global_max_credits")
    log_txt = f"<#{settings['log_channel_id']}>" if settings.get("log_channel_id") else "aucun"
    embed = discord.Embed(
        title="💳 Limitations",
        description=(f"**Consommation globale :** {settings['global_credits_used']} / {cap if cap else 'illimité'}\n"
                      f"**Seuil d'alerte crédits :** {settings.get('low_credit_alert_threshold') or 'désactivé'}\n"
                      f"**Salon de logs :** {log_txt}"),
        color=0x5865F2,
    )
    return embed, LimitsView(settings)


# ==================== AVANCÉ ====================

class AdvancedView(discord.ui.View):
    def __init__(self, settings):
        super().__init__(timeout=None)
        paused = bool(settings.get("paused"))
        self.pause_btn.label = "Reprendre tout" if paused else "Pause globale"
        self.pause_btn.emoji = "▶️" if paused else "⏸️"
        self.pause_btn.style = discord.ButtonStyle.success if paused else discord.ButtonStyle.danger

    @discord.ui.button(custom_id="lbd:advanced:pause", row=0)
    async def pause_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await db.get_settings(interaction.guild_id)
        await db.update_settings(interaction.guild_id, paused=0 if settings["paused"] else 1)
        await scheduler.sync()
        await navigate(interaction, "advanced")

    @discord.ui.button(label="Retour", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="lbd:advanced:back", row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await navigate(interaction, "home")


async def render_advanced(guild_id, **_):
    settings = await db.get_settings(guild_id)
    embed = discord.Embed(
        title="⚙️ Avancé",
        description=("**Anti-doublonnage :** 🔒 toujours actif sur tous les filtres — le bot ne renvoie jamais "
                      "deux fois la même annonce, ce réglage n'est pas désactivable.\n\n"
                      f"**Pause globale :** {'🔴 activée' if settings.get('paused') else '🟢 désactivée'}"),
        color=0x5865F2,
    )
    return embed, AdvancedView(settings)


# ==================== ACTION GROUPÉE ====================

class GroupActionSelect(discord.ui.Select):
    def __init__(self, filters):
        if filters:
            options = [discord.SelectOption(label=f"#{f['id']} {f['name'][:80]}", value=str(f["id"])) for f in filters[:25]]
            max_v = len(options)
        else:
            options = [discord.SelectOption(label="Aucun filtre disponible", value="none")]
            max_v = 1
        super().__init__(placeholder="Choisis les filtres concernés...", options=options,
                          min_values=1, max_values=max_v, custom_id="lbd:group:select", row=0)

    async def callback(self, interaction: discord.Interaction):
        if self.values == ["none"]:
            await interaction.response.defer()
            return
        state = await db.get_dashboard_state(interaction.message.id)
        action, value = state["pending_action"], state["pending_value"]
        for fid in (int(v) for v in self.values):
            if action == "enable":
                await db.set_enabled(fid, True)
            elif action == "disable":
                await db.set_enabled(fid, False)
            elif action == "delete":
                await db.delete_filter(fid)
            elif action == "interval":
                await db.update_filter(fid, interval_seconds=int(value))
            elif action == "credits_max":
                v = int(value)
                await db.update_filter(fid, max_credits=v if v > 0 else None)
        await scheduler.sync()
        await navigate(interaction, state["return_screen"] or "filters_list")


class GroupActionView(discord.ui.View):
    def __init__(self, filters):
        super().__init__(timeout=None)
        self.add_item(GroupActionSelect(filters))

    @discord.ui.button(label="Annuler", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="lbd:group:cancel", row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await db.get_dashboard_state(interaction.message.id)
        await navigate(interaction, (state["return_screen"] if state else None) or "filters_list")


async def render_group_action(guild_id, pending_action=None, pending_value=None, return_screen=None, **_):
    filters = await db.list_filters(guild_id)
    title = ACTION_LABELS.get(pending_action, "Action groupée")
    desc = "Sélectionne un ou plusieurs filtres dans le menu ci-dessous — l'action s'applique dès la validation."
    if pending_action == "interval" and pending_value:
        desc += f"\n\nNouvelle vitesse : **{format_interval(int(pending_value))}**"
    elif pending_action == "credits_max" and pending_value:
        v = int(pending_value)
        desc += f"\n\nNouveau plafond : **{v if v > 0 else 'illimité'}**"
    embed = discord.Embed(title=title, description=desc, color=0x5865F2)
    return embed, GroupActionView(filters)


# ==================== registre des écrans ====================

RENDERERS = {
    "home": render_home,
    "filters_list": render_filters_list,
    "filter_detail": render_filter_detail,
    "destinations": render_destinations,
    "planning": render_planning,
    "limits": render_limits,
    "advanced": render_advanced,
    "group_action": render_group_action,
}


def persistent_view_instances():
    """Instances 'gabarit' à enregistrer une seule fois au démarrage pour que TOUS les boutons/menus
    déjà envoyés (même avant un redémarrage) restent cliquables — le routage se fait par custom_id."""
    return [
        HomeView(),
        FiltersListView([]),
        FilterDetailView(EMPTY_FILTER),
        FiltersListBackStub(),
        DestinationsView({"unify_channel_id": None}),
        PlanningView(),
        LimitsView({"log_channel_id": None}),
        AdvancedView({"paused": 0}),
        GroupActionView([]),
    ]
