"""Region unlock goals + arrival story beats (v3 Phase 3).

To travel into a new region you must first complete that region's *unlock
goals* — a short checklist of three: a Gold threshold, a Level threshold, and
a deed (kill wild champions / win hunts in the region before it).

Goals are pure data. Threshold goals (gold/level) are checked live against the
users row; deed goals are counters stored in `user_goal_progress`.
"""
from __future__ import annotations

from dataclasses import dataclass

# Counter goal_key conventions (written by the PVE cog on a won hunt):
#   "{region}:hunt_wins"  — any won hunt in that region
#   "{region}:wild_kills" — a won hunt against a wild champion in that region


@dataclass(frozen=True)
class Goal:
    kind: str                       # 'gold' | 'level' | 'count'
    target: int
    label: str
    counter_key: str | None = None  # required for 'count' goals


@dataclass(frozen=True)
class GoalStatus:
    goal: Goal
    current: int
    done: bool


def _gold(amount: int) -> Goal:
    return Goal("gold", amount, f"Hold at least {amount:,} Gold")


def _level(level: int) -> Goal:
    return Goal("level", level, f"Reach Level {level}")


def _count(counter_key: str, target: int, label: str) -> Goal:
    return Goal("count", target, label, counter_key=counter_key)


# Keyed by the region being unlocked. bandle_city is the start — no goals.
REGION_UNLOCK_GOALS: dict[str, tuple[Goal, ...]] = {
    "demacia": (
        _gold(5_000), _level(3),
        _count("bandle_city:wild_kills", 1, "Defeat a wild champion in Bandle City"),
    ),
    "freljord": (
        _gold(12_000), _level(6),
        _count("demacia:hunt_wins", 15, "Win 15 hunts in Demacia"),
    ),
    "ionia": (
        _gold(25_000), _level(9),
        _count("freljord:wild_kills", 3, "Defeat 3 wild champions in Freljord"),
    ),
    "piltover_zaun": (
        _gold(40_000), _level(12),
        _count("ionia:hunt_wins", 20, "Win 20 hunts in Ionia"),
    ),
    "bilgewater": (
        _gold(60_000), _level(15),
        _count("piltover_zaun:wild_kills", 5, "Defeat 5 wild champions in Piltover & Zaun"),
    ),
    "ixtal": (
        _gold(55_000), _level(15),
        _count("piltover_zaun:hunt_wins", 20, "Win 20 hunts in Piltover & Zaun"),
    ),
    "shadow_isles": (
        _gold(80_000), _level(18),
        _count("bilgewater:wild_kills", 5, "Defeat 5 wild champions in Bilgewater"),
    ),
    "noxus": (
        _gold(90_000), _level(16),
        _count("freljord:hunt_wins", 25, "Win 25 hunts in Freljord"),
    ),
    "shurima": (
        _gold(100_000), _level(20),
        _count("ixtal:hunt_wins", 30, "Win 30 hunts in Ixtal"),
    ),
    "targon": (
        _gold(150_000), _level(24),
        _count("shurima:wild_kills", 8, "Defeat 8 wild champions in Shurima"),
    ),
    "void": (
        _gold(200_000), _level(27),
        _count("shurima:hunt_wins", 40, "Win 40 hunts in Shurima"),
    ),
}


# Arrival story beats — a greeting champion (splash shown) + flavor text.
ARRIVAL: dict[str, tuple[str, str]] = {
    "demacia": (
        "Garen",
        "Garen meets you at the High Silvermere gate, greatsword resting on "
        "his shoulder. \"Bandle City sends another wanderer. Demacia will test "
        "your steel — and your honor.\"",
    ),
    "freljord": (
        "Ashe",
        "Ashe lowers her bow as you crest the ridge. \"The Freljord does not "
        "forgive the unprepared. Keep moving, keep warm — and keep your blade "
        "close.\"",
    ),
    "ionia": (
        "Irelia",
        "Irelia's blades drift around her like leaves on the wind. \"The First "
        "Lands feel your arrival. Walk gently here — Ionia remembers everything.\"",
    ),
    "piltover_zaun": (
        "Jayce",
        "Jayce flags you down on the bridge between the cities. \"Progress "
        "above, desperation below. Watch your step in both, traveler.\"",
    ),
    "bilgewater": (
        "Gangplank",
        "Gangplank flips a gold coin as you step off the dock. \"Bilgewater "
        "runs on coin and grudges. You'll need plenty of the first.\"",
    ),
    "ixtal": (
        "Qiyana",
        "Qiyana regards you coldly from a throne of living vines. \"Few "
        "outsiders find Ixtal. Fewer leave it. The elements will judge you.\"",
    ),
    "shadow_isles": (
        "Thresh",
        "A lantern glows green in the mist. \"Welcome,\" Thresh whispers, "
        "\"to the isles where nothing — and no one — ever truly leaves.\"",
    ),
    "noxus": (
        "Darius",
        "Darius blocks the road, axe biting the dirt. \"Noxus respects only "
        "strength. Show me yours, or be trampled by it.\"",
    ),
    "shurima": (
        "Nasus",
        "Nasus studies you with ancient, patient eyes. \"The sands have "
        "swallowed empires, traveler. Tread the ruins of Shurima with respect.\"",
    ),
    "targon": (
        "Leona",
        "Leona's shield blazes like a second sun atop the peak. \"You have "
        "climbed far. The Aspects are watching now — do not falter.\"",
    ),
    "void": (
        "Kai'Sa",
        "Kai'Sa's voidsuit hisses in the dark. \"You shouldn't be here. "
        "Nothing should. But the Void is hungry, and now it knows your name.\"",
    ),
}


def evaluate_goals(
    region_key: str, user_gold: int, user_level: int, progress: dict[str, int]
) -> list[GoalStatus]:
    """Status of every unlock goal for `region_key`. Empty list if no goals."""
    statuses: list[GoalStatus] = []
    for goal in REGION_UNLOCK_GOALS.get(region_key, ()):
        if goal.kind == "gold":
            current = user_gold
        elif goal.kind == "level":
            current = user_level
        else:  # count
            current = progress.get(goal.counter_key or "", 0)
        statuses.append(
            GoalStatus(goal=goal, current=current, done=current >= goal.target)
        )
    return statuses


def all_goals_met(
    region_key: str, user_gold: int, user_level: int, progress: dict[str, int]
) -> bool:
    statuses = evaluate_goals(region_key, user_gold, user_level, progress)
    return all(s.done for s in statuses)  # all() of [] is True (no goals = open)
