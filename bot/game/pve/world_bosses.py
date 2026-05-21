"""World boss registry — rarity, HP, rewards, spawn weights (PRD v2 Phase B)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class WorldBossSpec:
    key: str
    name: str
    flavor: str
    hp_base: int
    window: timedelta
    spawn_weight: float
    top_three_gold: int
    fragment_drop: str | None   # e.g. 'fragment_t3'; only for top-3
    extra_drop: str | None      # e.g. 'dragon_soul_elder'; only for top-3
    participation_gold: int


WORLD_BOSSES: dict[str, WorldBossSpec] = {
    "rift_herald": WorldBossSpec(
        key="rift_herald",
        name="Rift Herald",
        flavor="The earth quakes as the Rift Herald bursts from the depths.",
        hp_base=80_000,
        window=timedelta(hours=1),
        spawn_weight=35.0,
        top_three_gold=5_000,
        fragment_drop="fragment_t3",
        extra_drop=None,
        participation_gold=1_000,
    ),
    "baron": WorldBossSpec(
        key="baron",
        name="Baron Nashor",
        flavor="**Baron Nashor** has risen. Its hunger is endless.",
        hp_base=200_000,
        window=timedelta(minutes=90),
        spawn_weight=40.0,
        top_three_gold=15_000,
        fragment_drop="fragment_t4",
        extra_drop=None,
        participation_gold=2_000,
    ),
    "atakhan": WorldBossSpec(
        key="atakhan",
        name="Atakhan",
        flavor="Atakhan, the Bringer of Ruin, strides into the world.",
        hp_base=350_000,
        window=timedelta(minutes=90),
        spawn_weight=20.0,
        top_three_gold=30_000,
        fragment_drop="fragment_t5",
        extra_drop=None,
        participation_gold=3_000,
    ),
    "elder_dragon": WorldBossSpec(
        key="elder_dragon",
        name="Elder Dragon",
        flavor="The Elder Dragon descends, its breath blackening the sky.",
        hp_base=500_000,
        window=timedelta(hours=2),
        spawn_weight=5.0,
        top_three_gold=50_000,
        fragment_drop="fragment_t5",
        extra_drop="dragon_soul_elder",
        participation_gold=5_000,
    ),
}


def hp_scaled(spec: WorldBossSpec, active_users: int) -> int:
    """HP scales with active player count over the last 7 days."""
    return int(spec.hp_base * (1.0 + 0.05 * active_users))


# Server-config keys used by the scheduler
CONFIG_BOSS_CHANNEL = "world_boss_channel_id"
CONFIG_NEXT_SPAWN_AT = "world_boss_next_spawn_at"
