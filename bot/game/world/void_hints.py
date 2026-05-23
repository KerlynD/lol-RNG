"""Subtle in-game hints that the Void exists.

The Void region is hidden=True (see regions.py); without these hints, players
discover it only by blindly hitting the unlock goals. Three flavors of nudge
fire only while standing in Shurima or Targon:

  - a static cryptic line rendered into the /adventure hub embed (always),
  - a louder variant once the player is >= 80% of the way to ALL three Void
    unlock goals (200k Gold, Level 27, 40 won hunts in Shurima),
  - a 5% per-/hunt-camp whisper appended to the encounter card.

Pure data + pure functions. No Discord, no DB. The Void's unlock goal targets
mirror REGION_UNLOCK_GOALS["void"] in goals.py — keep these in sync.
"""
from __future__ import annotations

STATIC_HINT: dict[str, str] = {
    "shurima": (
        "🌫 *The sand whispers in a tongue with no mouth. Something beneath "
        "stirs, and remembers your name.*"
    ),
    "targon": (
        "✨ *Between the stars there is a cold, hungry silence. It is closer "
        "than it should be.*"
    ),
}

LOUD_HINT: dict[str, str] = {
    "shurima": (
        "🌫 *The whispers sharpen into a name you almost recognize. Something "
        "below knows you are nearly ready.*"
    ),
    "targon": (
        "✨ *The silence between the stars has shape now — it leans toward "
        "you, waiting.*"
    ),
}

HUNT_WHISPERS: dict[str, tuple[str, ...]] = {
    "shurima": (
        "*The dunes hum, and the sound is hungry.*",
        "*Something just beneath the sand opens an eye.*",
        "*A shadow that wasn't there a moment ago is there now.*",
        "*The air tastes faintly of copper and the end of the world.*",
    ),
    "targon": (
        "*The stars are wrong in a way you can't name.*",
        "*A constellation you've never seen winks out for one heartbeat.*",
        "*The mountain remembers something that hasn't happened yet.*",
        "*Cold light from no source falls on your hand.*",
    ),
}

LOUD_THRESHOLD = 0.80
HUNT_WHISPER_CHANCE = 0.05

# Mirror of REGION_UNLOCK_GOALS["void"] in goals.py.
_VOID_GOLD_TARGET = 200_000
_VOID_LEVEL_TARGET = 27
_VOID_HUNT_TARGET = 40


def void_proximity(user_gold: int, user_level: int, shurima_hunt_wins: int) -> float:
    """How close (0.0..) the player is to the Void's unlock goals.

    Uses the MIN of the three normalized progresses — the slowest pillar caps
    the score, matching the all-goals-must-be-met semantics in goals.py. The
    result can exceed 1.0 if some pillars are over-achieved; that's fine, the
    threshold check is one-sided.
    """
    return min(
        user_gold / _VOID_GOLD_TARGET,
        user_level / _VOID_LEVEL_TARGET,
        shurima_hunt_wins / _VOID_HUNT_TARGET,
    )


def pick_hint(region_key: str, proximity: float) -> str | None:
    """Return the right cryptic line for the hub embed, or None if the region
    has no Void-adjacent vibe (i.e. anywhere other than Shurima / Targon).

    Loud variant kicks in at proximity >= 0.80.
    """
    if region_key not in STATIC_HINT:
        return None
    if proximity >= LOUD_THRESHOLD:
        return LOUD_HINT[region_key]
    return STATIC_HINT[region_key]
