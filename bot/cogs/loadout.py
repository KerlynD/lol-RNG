"""Loadout cog — single /loadout command.

`/loadout` is the only command players need for everything loadout-related:
- View current loadout (with champion images via Community Dragon CDN)
- 🛠 Edit — interactive per-slot Select menus to equip/unequip
- 📚 Collection — paginated view of every champion you own
- 🔒/🔓 still available as standalone commands for quick toggling

Replaces the old /loadout + /equip + /champions trio.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.db.queries import Champion, OwnedChampion
from bot.game.leveling import unlocks_for
from bot.utils.champion_images import tile_url
from bot.utils.decorators import register_user
from bot.utils.embeds import TIER_COLOR, TIER_NAME, failure_embed, info_embed

LOADOUT_SWAP_COOLDOWN = timedelta(minutes=30)

# Discord max options in a single Select menu
_SELECT_MAX_OPTIONS = 25
# Champs shown per page in collection view
_COLLECTION_PAGE_SIZE = 12


# ============================================================================
# Helpers
# ============================================================================


def _swap_cooldown_remaining(last_swap: datetime | None) -> float:
    if last_swap is None:
        return 0.0
    now = datetime.now(tz=timezone.utc)
    elapsed = (now - last_swap).total_seconds()
    return max(0.0, LOADOUT_SWAP_COOLDOWN.total_seconds() - elapsed)


def _format_seconds(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60}s"


def _slot_line(slot: int, champ: Champion | None) -> str:
    if champ is None:
        return f"**Slot {slot}:** _empty_"
    tier_emoji = "⬜⬜🟩🟦🟪🟨🟧⬛"[champ.tier]   # T0 unused, T1-7 indexed
    return (
        f"**Slot {slot}:** {tier_emoji} **{champ.name}** "
        f"(T{champ.tier} {TIER_NAME[champ.tier]} · {champ.region or '—'} · {champ.damage_type})"
    )


async def _build_dashboard_embed(user_id: int) -> discord.Embed:
    """Single-embed view (legacy compat — used in sub-view back transitions)."""
    user = await queries.get_user(user_id)
    entries = await queries.get_loadout(user_id)
    owned = await queries.list_owned(user_id)
    dead = {cid for cid, _, _ in await queries.dead_champions_for_user(user_id)}
    cap = unlocks_for(user.level).loadout_slots

    by_slot: dict[int, Champion] = {e.slot: e.champion for e in entries}

    lines: list[str] = []
    for slot in range(1, cap + 1):
        champ = by_slot.get(slot)
        line = _slot_line(slot, champ)
        if champ and champ.id in dead:
            line += " 💀"
        lines.append(line)

    desc = (
        "\n".join(lines)
        + f"\n\n_Cap_: {cap} slots · _Owned_: {len(owned)} champions"
    )
    remaining = _swap_cooldown_remaining(user.last_loadout_swap)
    if remaining > 0:
        desc += f"\n_Swap cooldown_: {_format_seconds(remaining)}"

    embed = discord.Embed(
        title=f"{await _username(user_id)}'s loadout",
        description=desc,
        color=0x3F51B5,
    )
    if entries:
        top = max((e.champion for e in entries), key=lambda c: c.tier)
        embed.set_thumbnail(url=tile_url(top.name))
    return embed


async def _build_dashboard_embeds(user_id: int, display_name: str) -> list[discord.Embed]:
    """Multi-embed dashboard: header + one embed per slot with champion icon."""
    user = await queries.get_user(user_id)
    entries = await queries.get_loadout(user_id)
    owned = await queries.list_owned(user_id)
    dead = {cid for cid, _, _ in await queries.dead_champions_for_user(user_id)}
    cap = unlocks_for(user.level).loadout_slots

    by_slot: dict[int, Champion] = {e.slot: e.champion for e in entries}
    embeds: list[discord.Embed] = []

    # Header embed
    remaining = _swap_cooldown_remaining(user.last_loadout_swap)
    header_desc = f"Slots: **{len(entries)}/{cap}** equipped · Owned: **{len(owned)}**"
    if remaining > 0:
        header_desc += f"\nSwap cooldown: **{_format_seconds(remaining)}**"
    header_desc += "\n\nUse the buttons below to edit or browse your collection."
    header = discord.Embed(
        title=f"{display_name}'s loadout",
        description=header_desc,
        color=0x3F51B5,
    )
    embeds.append(header)

    # One embed per slot
    for slot in range(1, cap + 1):
        champ = by_slot.get(slot)
        if champ is None:
            slot_embed = discord.Embed(
                title=f"Slot {slot}",
                description="_empty_",
                color=0x607D8B,
            )
        else:
            is_dead = champ.id in dead
            tier_name = TIER_NAME[champ.tier]
            desc_lines = [
                f"**{champ.name}**",
                f"T{champ.tier} {tier_name} · {champ.region or '—'} · {champ.damage_type}",
            ]
            if is_dead:
                desc_lines.append("💀 _Dead — check /menu for revive timer._")
            slot_embed = discord.Embed(
                title=f"Slot {slot}",
                description="\n".join(desc_lines),
                color=TIER_COLOR.get(champ.tier, 0x607D8B),
            )
            slot_embed.set_thumbnail(url=tile_url(champ.name))
        embeds.append(slot_embed)

    return embeds


async def _username(user_id: int) -> str:
    # No bot ref in this scope — just return a generic header; cogs that
    # have an interaction can pass the display name explicitly later.
    return "Your"


def _champ_select_options(
    owned: list[OwnedChampion],
    current_champ_id: int | None,
) -> list[discord.SelectOption]:
    """Sorted by tier desc, name. Returns up to 25 (Discord limit) + an Empty option."""
    sorted_owned = sorted(
        owned, key=lambda oc: (-oc.champion.tier, oc.champion.name)
    )
    options: list[discord.SelectOption] = [
        discord.SelectOption(
            label="— Empty slot —",
            value="empty",
            description="Unequip the champion in this slot.",
            default=(current_champ_id is None),
        )
    ]
    for oc in sorted_owned[:_SELECT_MAX_OPTIONS - 1]:
        c = oc.champion
        label = f"{c.name} (T{c.tier})"
        desc = f"{c.region or '—'} · {c.damage_type}" + (" 🔒" if oc.locked else "")
        options.append(
            discord.SelectOption(
                label=label[:100],
                value=str(c.id),
                description=desc[:100],
                default=(c.id == current_champ_id),
            )
        )
    return options


# ============================================================================
# Dashboard View (main /loadout response)
# ============================================================================


class LoadoutDashView(discord.ui.View):
    def __init__(self, owner_id: int, display_name: str):
        super().__init__(timeout=180.0)
        self.owner_id = owner_id
        self.display_name = display_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't your loadout.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary, emoji="🛠️")
    async def edit_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        view = await LoadoutEditView.build(self.owner_id, self.display_name)
        embed = await view.build_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Collection", style=discord.ButtonStyle.secondary, emoji="📚")
    async def collection_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        view = await CollectionView.build(self.owner_id, self.display_name, page=0)
        embed = await view.build_embed()
        await interaction.response.edit_message(embed=embed, view=view)


# ============================================================================
# Edit View — Select menu per slot
# ============================================================================


class SlotSelect(discord.ui.Select):
    """A select menu bound to a specific loadout slot."""

    def __init__(self, parent: "LoadoutEditView", slot: int, options: list[discord.SelectOption]):
        super().__init__(
            placeholder=f"Slot {slot}",
            options=options,
            min_values=1,
            max_values=1,
            row=slot - 1,   # one row per slot
        )
        self._parent_view = parent
        self._slot = slot

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        owner_id = self._parent_view.owner_id

        user = await queries.get_user(owner_id)
        current_loadout = await queries.get_loadout(owner_id)
        cap = unlocks_for(user.level).loadout_slots
        # The swap cooldown only bites when the loadout is already full —
        # filling open slots (e.g. building a fresh loadout) is always free.
        loadout_full = len(current_loadout) >= cap

        if loadout_full:
            remaining = _swap_cooldown_remaining(user.last_loadout_swap)
            if remaining > 0:
                await interaction.response.send_message(
                    embed=failure_embed(
                        f"Loadout swap is on cooldown — try again in {_format_seconds(remaining)}."
                    ),
                    ephemeral=True,
                )
                return

        if value == "empty":
            cleared = await queries.clear_loadout_slot(owner_id, self._slot)
            if cleared and loadout_full:
                await queries.stamp_loadout_swap(owner_id)
            msg = f"Slot {self._slot} cleared." if cleared else f"Slot {self._slot} was already empty."
        else:
            try:
                champ_id = int(value)
            except ValueError:
                await interaction.response.send_message(
                    embed=failure_embed("Invalid selection."), ephemeral=True
                )
                return
            if not await queries.owns_champion(owner_id, champ_id):
                await interaction.response.send_message(
                    embed=failure_embed("You don't own that champion anymore."),
                    ephemeral=True,
                )
                return
            # If the champion is in another slot, move it (clear old slot first).
            for entry in current_loadout:
                if entry.champion.id == champ_id and entry.slot != self._slot:
                    await queries.clear_loadout_slot(owner_id, entry.slot)
                    break
            await queries.set_loadout_slot(owner_id, self._slot, champ_id)
            if loadout_full:
                await queries.stamp_loadout_swap(owner_id)
            champ = await queries.get_champion_by_id(champ_id)
            msg = f"Equipped **{champ.name}** to slot {self._slot}."

        # Rebuild the entire edit view to reflect the new state.
        new_view = await LoadoutEditView.build(owner_id, self._parent_view.display_name)
        embed = await new_view.build_embed()
        embed.set_footer(text=msg)
        await interaction.response.edit_message(embed=embed, view=new_view)


class LoadoutEditView(discord.ui.View):
    def __init__(self, owner_id: int, display_name: str):
        super().__init__(timeout=180.0)
        self.owner_id = owner_id
        self.display_name = display_name

    @classmethod
    async def build(cls, owner_id: int, display_name: str) -> "LoadoutEditView":
        view = cls(owner_id, display_name)

        user = await queries.get_user(owner_id)
        cap = unlocks_for(user.level).loadout_slots
        owned = await queries.list_owned(owner_id)
        loadout = await queries.get_loadout(owner_id)
        by_slot: dict[int, int] = {e.slot: e.champion.id for e in loadout}

        # One Select per slot. If user has no owned champs, we still render
        # empty selects so the structure is visible.
        for slot in range(1, cap + 1):
            options = _champ_select_options(owned, by_slot.get(slot))
            view.add_item(SlotSelect(view, slot, options))

        # Back button on the last available row.
        view.add_item(_BackToDashButton(view))
        return view

    async def build_embed(self) -> discord.Embed:
        user = await queries.get_user(self.owner_id)
        owned_count = len(await queries.list_owned(self.owner_id))
        cap = unlocks_for(user.level).loadout_slots
        remaining = _swap_cooldown_remaining(user.last_loadout_swap)
        cd_line = (
            f"\n⏳ Swap cooldown: **{_format_seconds(remaining)}**"
            if remaining > 0 else ""
        )
        desc = (
            f"Pick a champion for each slot. Changes save instantly. "
            f"Selecting **— Empty slot —** unequips.\n\n"
            f"Slots unlocked: **{cap}** · Owned: **{owned_count}**"
            f"{cd_line}"
        )
        if owned_count > _SELECT_MAX_OPTIONS - 1:
            desc += (
                f"\n\n_Only the top {_SELECT_MAX_OPTIONS - 1} highest-tier "
                f"champions are listed per slot. Filter by tier coming later._"
            )
        return discord.Embed(
            title=f"🛠 Edit loadout — {self.display_name}",
            description=desc,
            color=0x3F51B5,
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't your loadout.", ephemeral=True
            )
            return False
        return True


class _BackToDashButton(discord.ui.Button):
    def __init__(self, parent_view: discord.ui.View):
        super().__init__(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=4)
        self._parent_view_ref = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        owner_id = getattr(self._parent_view_ref, "owner_id", interaction.user.id)
        display_name = getattr(self._parent_view_ref, "display_name", "Your")
        embeds = await _build_dashboard_embeds(owner_id, display_name)
        view = LoadoutDashView(owner_id, display_name)
        await interaction.response.edit_message(embeds=embeds, view=view, attachments=[])


# ============================================================================
# Collection View — paginated full list
# ============================================================================


class CollectionView(discord.ui.View):
    def __init__(self, owner_id: int, display_name: str, owned: list[OwnedChampion], page: int):
        super().__init__(timeout=180.0)
        self.owner_id = owner_id
        self.display_name = display_name
        self.owned = owned
        self.page = page
        self.total_pages = max(
            1, (len(owned) + _COLLECTION_PAGE_SIZE - 1) // _COLLECTION_PAGE_SIZE
        )
        self._update_button_state()

    @classmethod
    async def build(cls, owner_id: int, display_name: str, page: int) -> "CollectionView":
        owned = await queries.list_owned(owner_id)
        return cls(owner_id, display_name, owned, page)

    def _update_button_state(self) -> None:
        self.prev_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= self.total_pages - 1

    async def build_embed(self) -> discord.Embed:
        if not self.owned:
            return discord.Embed(
                title="📚 Collection",
                description="_You haven't rolled any champions yet. Try `/roll`!_",
                color=0x607D8B,
            )

        start = self.page * _COLLECTION_PAGE_SIZE
        end = start + _COLLECTION_PAGE_SIZE
        page_items = self.owned[start:end]

        lines: list[str] = []
        for oc in page_items:
            c = oc.champion
            tier_emoji = "⬜⬜🟩🟦🟪🟨🟧⬛"[c.tier]
            lock = " 🔒" if oc.locked else ""
            lines.append(
                f"{tier_emoji} **{c.name}** — T{c.tier} {TIER_NAME[c.tier]} · "
                f"{c.region or '—'} · {c.damage_type}{lock}"
            )

        embed = discord.Embed(
            title=f"📚 Collection — {self.display_name} ({len(self.owned)})",
            description="\n".join(lines),
            color=0x3F51B5,
        )
        embed.set_footer(text=f"Page {self.page + 1} / {self.total_pages}")
        # Use the top-tier owned champ on this page as the thumbnail.
        if page_items:
            top = max(page_items, key=lambda oc: oc.champion.tier).champion
            embed.set_thumbnail(url=tile_url(top.name))
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't your collection.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def prev_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self.page > 0:
            self.page -= 1
            self._update_button_state()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="➡️")
    async def next_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self.page < self.total_pages - 1:
            self.page += 1
            self._update_button_state()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Back", style=discord.ButtonStyle.primary, emoji="🏠")
    async def back_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        embeds = await _build_dashboard_embeds(self.owner_id, self.display_name)
        view = LoadoutDashView(self.owner_id, self.display_name)
        await interaction.response.edit_message(embeds=embeds, view=view, attachments=[])


# ============================================================================
# Cog
# ============================================================================


class Loadout(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="loadout",
        description="View, edit, and browse your champion loadout and collection.",
    )
    @register_user
    async def loadout(self, interaction: discord.Interaction) -> None:
        display_name = interaction.user.display_name
        embeds = await _build_dashboard_embeds(interaction.user.id, display_name)
        view = LoadoutDashView(interaction.user.id, display_name)
        await interaction.response.send_message(embeds=embeds, view=view, ephemeral=True)

    # /lock and /unlock kept as standalone for quick access (also still
    # usable inside the collection workflow later).

    @app_commands.command(name="lock", description="Lock a champion — protected from trade/sacrifice/steal.")
    @app_commands.describe(champion="Champion name (case-insensitive).")
    @register_user
    async def lock(self, interaction: discord.Interaction, champion: str) -> None:
        champ = await queries.get_champion_by_name(champion)
        if champ is None or not await queries.owns_champion(interaction.user.id, champ.id):
            await interaction.response.send_message(
                embed=failure_embed(f"You don't own **{champion}**."),
                ephemeral=True,
            )
            return
        await queries.set_locked(interaction.user.id, champ.id, True)
        await interaction.response.send_message(
            embed=info_embed(f"🔒 **{champ.name}** locked."),
            ephemeral=True,
        )

    @app_commands.command(name="unlock", description="Unlock a champion.")
    @app_commands.describe(champion="Champion name (case-insensitive).")
    @register_user
    async def unlock(self, interaction: discord.Interaction, champion: str) -> None:
        champ = await queries.get_champion_by_name(champion)
        if champ is None or not await queries.owns_champion(interaction.user.id, champ.id):
            await interaction.response.send_message(
                embed=failure_embed(f"You don't own **{champion}**."),
                ephemeral=True,
            )
            return
        await queries.set_locked(interaction.user.id, champ.id, False)
        await interaction.response.send_message(
            embed=info_embed(f"🔓 **{champ.name}** unlocked."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Loadout(bot))
