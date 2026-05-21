"""Dragon soul buffs — 1h temporary effects that auto-activate on drop.

Each soul corresponds to a specific gameplay hook. Active souls are tracked
via the existing cooldowns table with action_key `_soul:<type>` and a 1h TTL.
"""
from __future__ import annotations

import random
from datetime import timedelta

from bot.db import queries

SOUL_DURATION = timedelta(hours=1)

SOUL_TYPES = (
    "cloud", "ocean", "mountain", "infernal", "chemtech", "hextech",
)

SOUL_EFFECT_DESC = {
    "cloud":    "-20% cooldowns on all game actions",
    "ocean":    "+50% Gold from /work and /daily",
    "mountain": "every camp win drops a random shield",
    "infernal": "+10% PvP attacker damage",
    "chemtech": "every camp win drops a corruption stack",
    "hextech":  "+25% chance of a random fragment on camp win",
}

# Map drop item_type → soul type
SOUL_DROP_TO_TYPE = {
    f"dragon_soul_{t}": t for t in SOUL_TYPES
}


def soul_cooldown_key(soul_type: str) -> str:
    return f"_soul:{soul_type}"


async def activate_soul(user_id: int, soul_type: str) -> None:
    """Set a 1h cooldown row for this soul. Idempotent (resets the timer)."""
    if soul_type not in SOUL_TYPES:
        return
    await queries.set_cooldown(user_id, soul_cooldown_key(soul_type), SOUL_DURATION)


async def is_soul_active(user_id: int, soul_type: str) -> bool:
    remaining = await queries.check_cooldown(user_id, soul_cooldown_key(soul_type))
    return remaining is not None


async def active_souls(user_id: int) -> dict[str, float]:
    """Returns {soul_type: seconds_remaining} for every active soul."""
    cooldowns = await queries.get_all_cooldowns(user_id)
    out: dict[str, float] = {}
    for key, remaining in cooldowns.items():
        if key.startswith("_soul:"):
            soul_type = key[len("_soul:"):]
            if soul_type in SOUL_TYPES:
                out[soul_type] = remaining
    return out


# --- Effect application helpers (called from various hot paths) ---


async def cooldown_factor(user_id: int) -> float:
    """Cloud soul: cooldowns set on this user are multiplied by this factor."""
    return 0.8 if await is_soul_active(user_id, "cloud") else 1.0


async def gold_factor_for_action(user_id: int, action_key: str) -> float:
    """Ocean soul: /work and /daily payouts get +50%."""
    if action_key in ("work", "daily"):
        if await is_soul_active(user_id, "ocean"):
            return 1.5
    return 1.0


async def pvp_attacker_power_factor(user_id: int) -> float:
    """Infernal soul: attacker Power multiplier."""
    return 1.1 if await is_soul_active(user_id, "infernal") else 1.0


async def apply_camp_win_bonuses(
    user_id: int,
    drops: list[tuple[str, int]],
    rng: random.Random | None = None,
) -> list[tuple[str, int]]:
    """Mountain / Chemtech / Hextech add bonus drops on camp win.

    Returns drops list extended with whatever bonuses applied. The original
    `drops` list is not mutated.
    """
    rng = rng or random
    extras: list[tuple[str, int]] = []

    if await is_soul_active(user_id, "mountain"):
        shield_type = rng.choice([
            "shield_physical", "shield_magic", "aegis"
        ])
        extras.append((shield_type, 1))

    if await is_soul_active(user_id, "chemtech"):
        extras.append(("corruption_stack", 1))

    if await is_soul_active(user_id, "hextech"):
        if rng.random() < 0.25:
            tier = rng.choice([1, 2, 3])
            extras.append((f"fragment_t{tier}", 1))

    return list(drops) + extras
