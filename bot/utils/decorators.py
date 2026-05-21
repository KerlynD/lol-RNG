"""Slash-command decorators for cross-cutting concerns."""
from __future__ import annotations

import functools
from typing import Any, Awaitable, Callable

import discord

from bot.db import queries


def register_user(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Ensures the invoking user exists in the DB before the handler runs.

    Decorate every game slash command with this. First invocation grants the
    starter Roll Token (PRD §8.1).
    """

    @functools.wraps(func)
    async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
        await queries.ensure_user(interaction.user.id)
        return await func(self, interaction, *args, **kwargs)

    return wrapper
