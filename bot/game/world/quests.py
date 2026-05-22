"""Region quests — champion-given missions (v3 Phase 4).

Each region has a couple of quests handed out by its champions. Quests are
content (Gold/XP/item rewards + lore), distinct from the region *unlock goals*
in goals.py. A quest's objective is tracked against the cumulative region
counters (see goals.py) using a per-quest baseline snapshot taken on accept.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Quest:
    key: str
    region: str
    giver: str                       # champion name — splash shown on the card
    title: str
    description: str
    objective_kind: str              # 'hunt' | 'wild' | 'level' | 'gold'
    objective_target: int
    reward_gold: int
    reward_xp: int
    reward_item: str | None = None
    reward_item_qty: int = 0

    @property
    def objective_label(self) -> str:
        if self.objective_kind == "hunt":
            return f"Win {self.objective_target} hunts in this region"
        if self.objective_kind == "wild":
            return f"Defeat {self.objective_target} wild champions in this region"
        if self.objective_kind == "level":
            return f"Reach Level {self.objective_target}"
        return f"Hold {self.objective_target:,} Gold"

    def counter_key(self) -> str | None:
        """The cumulative region counter this quest tracks, or None if the
        objective is an absolute check (level/gold)."""
        if self.objective_kind == "hunt":
            return f"{self.region}:hunt_wins"
        if self.objective_kind == "wild":
            return f"{self.region}:wild_kills"
        return None


# (slug, giver, title, kind, target, gold, xp, item, item_qty, description)
_QuestRow = tuple[str, str, str, str, int, int, int, "str | None", int, str]

_REGION_QUEST_ROWS: dict[str, tuple[_QuestRow, ...]] = {
    "bandle_city": (
        ("lulu_whimsy", "Lulu", "A Touch of Whimsy", "hunt", 5, 1200, 90,
         "mat", 3,
         "Lulu wants you to \"shoo the grumpy things\" from the Glade. Win 5 "
         "hunts and Pix will reward you handsomely."),
        ("teemo_scout", "Teemo", "Captain Teemo's Patrol", "wild", 1, 1800, 120,
         None, 0,
         "Teemo needs the Bandle militia tested. Best one wild champion in "
         "the field to prove the patrol is ready."),
    ),
    "demacia": (
        ("garen_duty", "Garen", "For Demacia", "hunt", 12, 4500, 280,
         "shield_physical", 2,
         "Garen sets you a soldier's task: clear 12 threats from the "
         "petricite woods. Demacia rewards diligence."),
        ("lux_light", "Lux", "Hidden Light", "wild", 2, 6000, 360,
         None, 0,
         "Lux asks you, quietly, to drive off two renegade champions before "
         "the Mageseekers find them first."),
    ),
    "freljord": (
        ("ashe_unity", "Ashe", "The Long Hunt", "hunt", 16, 9000, 520,
         "mat", 5,
         "Ashe needs the tundra trails made safe for the Avarosan. Win 16 "
         "hunts across the Freljord."),
        ("sejuani_proof", "Sejuani", "Strength of the Storm", "wild", 3, 12000, 680,
         "soul", 1,
         "Sejuani respects only the strong. Defeat 3 wild champions and the "
         "Winter's Claw will call you kin."),
    ),
    "ionia": (
        ("karma_balance", "Karma", "Restoring Balance", "hunt", 20, 16000, 900,
         "shield_magic", 2,
         "Karma asks you to soothe the unrest haunting the First Lands — "
         "win 20 hunts to mend the spirit realm."),
        ("yasuo_redemption", "Yasuo", "An Unforgiven Debt", "wild", 4, 21000, 1100,
         None, 0,
         "Yasuo cannot face them himself. Defeat 4 wild champions in his "
         "stead, and he will owe you a swordsman's honor."),
    ),
    "piltover_zaun": (
        ("vi_cleanup", "Vi", "Enforcer's Overtime", "hunt", 22, 24000, 1200,
         "mat", 6,
         "Vi has more trouble than fists. Win 22 hunts to clear the worst of "
         "Zaun's overflow into Piltover."),
        ("ekko_timeline", "Ekko", "A Better Tomorrow", "wild", 5, 30000, 1500,
         "fragment_t4", 1,
         "Ekko has seen a future where the Lanes burn. Defeat 5 wild "
         "champions to bend the timeline somewhere kinder."),
    ),
    "bilgewater": (
        ("missfortune_bounty", "Miss Fortune", "Bounty Board", "hunt", 24, 36000, 1700,
         "soul", 1,
         "Miss Fortune fronts you a stack of bounty marks. Win 24 hunts and "
         "the coin is yours — minus her cut, of course."),
        ("illaoi_test", "Illaoi", "The Kraken's Judgement", "wild", 6, 44000, 2100,
         None, 0,
         "Illaoi will test your spirit against the Mother Serpent's will. "
         "Defeat 6 wild champions to prove your soul has weight."),
    ),
    "ixtal": (
        ("qiyana_empress", "Qiyana", "Elements of an Empress", "hunt", 24, 38000, 1800,
         "mat", 6,
         "Qiyana will tolerate your presence in Ixtal — if you win 24 hunts "
         "and prove the jungle answers to you, too."),
        ("neeko_curious", "Neeko", "Curious Chameleon", "wild", 6, 46000, 2200,
         "fragment_t5", 1,
         "Neeko, ever curious, wants to watch you face 6 wild champions — "
         "and maybe learn a new shape from the winners."),
    ),
    "shadow_isles": (
        ("thresh_collection", "Thresh", "Souls for the Lantern", "hunt", 26, 50000, 2400,
         "soul", 2,
         "Thresh offers a bargain you shouldn't take. Win 26 hunts on the "
         "isles and his lantern will glow a little brighter — for you."),
        ("kalista_vengeance", "Kalista", "A Spear of Vengeance", "wild", 7, 60000, 2900,
         None, 0,
         "Kalista answers oaths of vengeance. Defeat 7 wild champions and "
         "the Spear of Vengeance will mark you an ally."),
    ),
    "noxus": (
        ("darius_hand", "Darius", "The Hand of Noxus", "hunt", 28, 70000, 3400,
         "soul", 2,
         "Darius has no patience for the weak. Win 28 hunts and the Hand of "
         "Noxus may consider you worth its time."),
        ("katarina_contract", "Katarina", "A Sinister Contract", "wild", 8, 84000, 4000,
         "fragment_t5", 1,
         "Katarina slides you a contract across the table. Defeat 8 wild "
         "champions — no questions, no witnesses."),
    ),
    "shurima": (
        ("nasus_chronicle", "Nasus", "The Curator's Request", "hunt", 30, 90000, 4400,
         "mat", 8,
         "Nasus is recording the age. Win 30 hunts so the chronicle of "
         "Shurima's rebirth has a worthy hero in its pages."),
        ("sivir_fortune", "Sivir", "Fortune Hunter", "wild", 9, 110000, 5200,
         "fragment_t6", 1,
         "Sivir never works for free, and neither should you. Defeat 9 wild "
         "champions and split the relic-hunter's haul."),
    ),
    "targon": (
        ("leona_dawn", "Leona", "The Dawn's Vigil", "hunt", 32, 130000, 6200,
         "soul", 3,
         "Leona asks you to hold the dawn against the dark. Win 32 hunts on "
         "the mountain and the Solari will name you Radiant."),
        ("diana_moonfall", "Diana", "Children of the Moon", "wild", 10, 160000, 7400,
         "fragment_t6", 1,
         "Diana fights a war few will acknowledge. Defeat 10 wild champions "
         "beneath the moon and the Lunari will not forget it."),
    ),
    "void": (
        ("kaisa_survivor", "Kai'Sa", "Daughter of the Void", "hunt", 36, 200000, 9000,
         "soul", 4,
         "Kai'Sa survived the Void by never stopping. Win 36 hunts in the "
         "dark and she'll trust you to watch her back."),
        ("khazix_apex", "Kha'Zix", "Become the Apex", "wild", 12, 250000, 11000,
         "fragment_t6", 2,
         "Kha'Zix hungers to evolve. Defeat 12 wild champions and the Void "
         "itself will reshape you into something that endures."),
    ),
}


def _build(region: str, row: _QuestRow) -> Quest:
    slug, giver, title, kind, target, gold, xp, item, item_qty, desc = row
    return Quest(
        key=f"{region}:{slug}",
        region=region,
        giver=giver,
        title=title,
        description=desc,
        objective_kind=kind,
        objective_target=target,
        reward_gold=gold,
        reward_xp=xp,
        reward_item=item,
        reward_item_qty=item_qty,
    )


REGION_QUESTS: dict[str, tuple[Quest, ...]] = {
    region: tuple(_build(region, row) for row in rows)
    for region, rows in _REGION_QUEST_ROWS.items()
}

QUESTS: dict[str, Quest] = {
    quest.key: quest for quests in REGION_QUESTS.values() for quest in quests
}


def quests_for_region(region_key: str) -> tuple[Quest, ...]:
    return REGION_QUESTS.get(region_key, ())


def get_quest(quest_key: str) -> Quest | None:
    return QUESTS.get(quest_key)


def quest_current(
    quest: Quest, *, counter_value: int, baseline: int, user_level: int, user_gold: int
) -> int:
    """Progress toward a quest's objective given the relevant inputs."""
    if quest.objective_kind == "level":
        return user_level
    if quest.objective_kind == "gold":
        return user_gold
    # counter-based: progress since the quest was accepted
    return max(0, counter_value - baseline)
