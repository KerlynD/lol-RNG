# PRD — LoL-RNG Discord Bot (v0.2 draft)

A Discord gambling/gacha bot where players roll for League of Legends champions sorted by **lore-based rarity** (Common → Death). Collected champions are equipped to a loadout that unlocks **actions** — flavored mini-games that earn currency, items, and rarer rolls. Rarity gates content, AP/AD combat drives always-on PvP, and the chase ends at Kindred herself.

---

## 1. Core Loop

1. **Earn** Gold + XP via actions.
2. **Level up** to unlock loadout slots, action tiers, and combat stats.
3. **Roll** for champions using Gold or Roll Tokens.
4. **Equip** champions to a loadout (3 → 5 slots, level-gated).
5. **Do actions** — gated by tier / region / faction / specific champ.
6. **Survive PvP** — always-on, mitigated by shields and loadout composition.
7. **Trade** champions with other players.

---

## 2. Rarity Tiers & Roster

Per-champion drop chance is a range within tier (we'll assign individual weights later).

### Tier 1 — Common | 1/2 to 1/10
Renata Glasc, Seraphine, Caitlyn, Draven, Gangplank, Graves, Jhin, Jinx, Miss Fortune, Quinn, Sivir, Vayne, Akshan

### Tier 2 — Uncommon | 1/10 to 1/50
Darius, Fiora, Garen, Jarvan IV, K'Sante, Samira, Sett, Xin Zhao, Blitzcrank, Camille, Dr. Mundo, Ekko, Heimerdinger, Jayce, Orianna, Singed, Urgot, Vi, Viktor, Warwick, Zac, Aphelios, Ashe, Lucian, Riven, Senna, Tryndamere, Akali, Alistar, Braum, Briar, Corki, Fizz, Gragas, Kennen, Kled, Milio, Nami, Nidalee, Olaf, Rakan, Rengar, Rumble, Sejuani, Smolder, Sona, Teemo, Tristana, Twisted Fate, Twitch, Xayah, Yuumi, Zeri, Ziggs, Ezreal, Katarina, Ambessa, Yunara

### Tier 3 — Rare | 1/50 to 1/500
Ahri, Annie, Cassiopeia, Hwei, Lulu, Lux, Malzahar, Neeko, Qiyana, Swain, Sylas, Taliyah, Veigar, Vex, Zyra, Gwen, Irelia, Jax, Lee Sin, Master Yi, Rell, Shen, Udyr, Wukong, Yasuo, Yone, Zed, Amumu, Elise, Gnar, Hecarim, Illaoi, Ivern, Kai'Sa, Kalista, Kassadin, Kha'Zix, Kog'Maw, Lillia, Maokai, Nautilus, Poppy, Pyke, Rammus, Rek'Sai, Shaco, Shyvana, Sion, Skarner, Thresh, Trundle, Yorick, Aurora, Mel, Nilah, Talon, Nunu & Willump

### Tier 4 — Epic | 1/500 to 1/5,000
Azir, Naafiri, Nasus, Renekton, Varus, Xerath, Karthus, Mordekaiser, Viego, Bel'Veth, Cho'Gath, Malphite, Vel'Koz, Brand, Evelynn, Galio, Kayn, Lissandra, Nocturne, Tahm Kench, Zilean, Syndra, Ryze, Vladimir, Karma, LeBlanc, Zaheen

### Tier 5 — Legendary | 1/5,000 to 1/100,000
Anivia, Janna, Ornn, Volibear, Diana, Kayle, Leona, Morgana, Pantheon, Soraka, Taric, Fiddlesticks

### Tier 6 — God-Tier | 1/100,000 to 1/1,000,000
Aatrox, Aurelion Sol, Bard, Zoe

### Tier 7 — Death | 1/1,000,000 to 1/10,000,000+
Kindred

---

## 3. Level System

XP earned from every successful action (and a small amount from PvP wins/losses).

| Level | Unlocks |
|---|---|
| 1 | Loadout slots: **3**, Tier 1–2 actions |
| 5 | Tier 3 actions, +1 max HP tier, Shield inventory unlocked |
| 10 | **Loadout slot 4**, Tier 4 actions, region-synergy bonuses active |
| 15 | Tier 5 actions, double-roll on `/daily` |
| 20 | **Loadout slot 5**, Tier 6 (God) actions usable |
| 25 | Tier 7 (Death) actions usable, prestige soft-cap |
| 30 (cap) | Prestige path — reset for cosmetic title, permanent **+5% Gold income**, and **improved Death-tier roll rate (1/1M → 1/500K)** |

**XP curve:** moderate-grind. Hitting 20 should take serious play (weeks of casual, days of hardcore) so God actions feel earned even after the pull.

**Level vs. Pull luck:** the chad twist — a Lv3 lucky puller could *own* Aatrox but can't use `/world-ender` until Lv20. Pulls and progression are independent.

---

## 4. Loadout System

- **Slots:** start at **3**, expand to **4 at Lv10**, **5 at Lv20**. Hard cap: 5.
- Only equipped champs can perform actions or defend in PvP.
- **Swap cooldown:** 30 minutes — prevents per-action min-maxing.
- **Synergy bonuses (unlocked Lv10):**
  - 2+ same region → +10% Gold from that region's actions
  - 3+ same faction → unlocks faction-only actions
  - 2+ same damage type → +5% PvP offense of that type

---

## 5. Combat — Always-On PvP

Always-on means any player can be targeted by PvP actions at any time. Protections, not opt-out, are the safety valve.

### 5.1 Damage Types
Every champion is tagged **AD** (Attack Damage), **AP** (Ability Power), or **Hybrid**.

- **AD champs**: Garen, Darius, Jhin, Vayne, Yasuo, Zed, Aatrox, etc.
- **AP champs**: Lux, Ahri, Veigar, Syndra, Aurelion Sol, etc.
- **Hybrid** (rare): Ekko, Kayle, Akali, etc. — flexible, slightly weaker pure damage

Damage type matters because **shields are typed.**

### 5.2 PvP Resolution — Multi-Round Skirmish

Every PvP encounter is a **best-of-3 skirmish** between the two players' loadouts. Each round plays out in the channel with flavor text, building tension.

**Per round:**
1. Attacker's next available champ steps forward (highest unused Power, or attacker-picked if action allows).
2. Defender's loadout auto-selects its best counter (highest defense vs. the attacker's damage type).
3. Compute a **Power score** for each side: `Power = (HP × 0.4) + (ATK × 0.4) + (DEF × 0.2)`, plus tier/level modifiers.
4. Convert ratio to a win % (e.g. 60/40 power split → attacker has 60% win chance). Soft-clamped to [10%, 90%] so upsets are always possible.
5. **Hidden d100 roll** decides the round. Players never see the % beforehand — keeps drama in chat.
6. Flavor line prints based on outcome ("Garen cleaves through Lux's barrier…").

**Tier difference modifier:** each tier of advantage = +5% effective Power. Caps at +25% (so a God doesn't trivially auto-win every round vs. an Uncommon, but it's still very tough).

**Match end:** first to 2 round wins takes the encounter. Loser pays out (Gold % stolen, item dropped, etc. — depends on which action triggered the PvP).

Strategic and cinematic: hidden rolls preserve drama, but loadout composition determines the odds — players who think about AP/AD balance and tier mix beat lazy loadouts.

### 5.3 Shields (PvP Protection)
Shields drop from actions (rarer drop, higher value).

| Shield | Blocks | Source |
|---|---|---|
| **Physical Shield** | Next AD hit | `/patrol-demacia`, `/work` (rare) |
| **Magic Shield** | Next AP hit | `/meditate-ionia`, `/celestial-gaze` |
| **Aegis** | Next hit of any type | Epic+ actions, very rare |
| **Stasis** | Skips one PvP loss (Zhonya's flavor) | Lv15+ Legendary actions |

Shields auto-consume on incoming PvP hit. Stockpile freely. **No cap** on shields held — incentivizes grinding defensive actions.

### 5.4 PvP Attack Cap
**Max 3 PvP attacks received per defender per 24h.** After 3 incoming hits, a player is automatically protected for the rest of the day. Prevents farming / harassment while keeping the always-on vibe intact. Attackers see a clear "this target is rested" message — not a silent failure.

---

## 6. Actions

Each action has: tier req, cooldown, cost, payout, flavor.

### 6.0 Cooldown Pyramid (default cadence)
| Tier | Cooldown range |
|---|---|
| T1 (Common) | 30 min – 1 h |
| T2 (Uncommon) | 1 – 2 h |
| T3 (Rare) | 4 – 6 h |
| T4 (Epic) | 12 h |
| T5 (Legendary) | 24 h |
| T6 (God) | **weekly** (7 days) |
| T7 (Death) | **monthly** (30 days) |

Specific actions may deviate (e.g. `/daily` is always 24h regardless of tier), but the pyramid is the default frame.

### 6.1 Tier 1 — Common (no champ required)
- `/work` 1h — small Gold, tiny chance of Physical Shield
- `/beg` 30m — tiny Gold, occasional joke result
- `/daily` 24h — guaranteed Gold + 1 Roll Token (2 at Lv15+)

### 6.2 Tier 2 — Uncommon (≥1 Tier 2+ champ; some region-gated)
- `/forage` — Yordle equipped (Teemo, Tristana, Kennen, Corki, Kled, Rumble, Ziggs, Heimerdinger). Small Gold + crafting mats.
- `/tinker` — Piltover/Zaun inventor (Heimer, Viktor, Jayce, Ekko, Ziggs, Corki). Build tools that buff other actions.
- `/prank` — Steal small % Gold from another player (Teemo, Kled, Twitch, Shaco flavor — Tier 2+).
- `/duel` — Challenge another user, both pick one champ, AD vs AP matters here.

### 6.3 Tier 3 — Rare (regional/faction)
- `/patrol-demacia` — Demacian champ (Garen, Lux, Quinn, Sona, Galio). Steady Gold, anti-AP bonus. Drops Physical Shield.
- `/heist-piltover` — Piltover/Zaun champ. High variance, can fail and lose Gold.
- `/meditate-ionia` — Ionian (Yasuo, Yone, Master Yi, Shen, Akali, Karma). Builds passive XP buff. Drops Magic Shield.
- `/hunt-shadowisles` — Shadow Isles (Thresh, Hecarim, Yorick, Maokai). Chance at **Soul** items.
- `/raid-noxus` — Noxian (Darius, Katarina, Sion, Cassiopeia, LeBlanc). PvP — challenge another user, winner takes Gold pool.

### 6.4 Tier 4 — Epic (faction power)
- `/ascend` — Shuriman Ascended (Azir, Nasus, Renekton, Xerath). Convert mats → Fragments.
- `/darkin-pact` — Darkin (Aatrox, Rhaast/Kayn, Varus, Naafiri). Sacrifice a Common champ → big Gold + corruption stack.
- `/defend-targon` — Targonian (when not Legendary). Group event others can join.
- `/void-touch` — Voidborn Epic (Cho'Gath, Vel'Koz, Kha'Zix). Drains target's next action's Gold.

### 6.5 Tier 5 — Legendary (cosmic)
- `/void-incursion` — Voidborn Legendary (Bel'Veth tier-shifted, or specific casts). Multi-player participation event.
- `/celestial-gaze` — Celestial (Soraka, Pantheon, Diana, Leona, Taric). Peek at next roll's tier before rolling.
- `/freljord-storm` — Freljord Legendary (Anivia, Volibear, Ornn). Area effect: buffs your next 3 actions.
- `/judgment` — Kayle/Morgana. Mark a player; their next PvP attempt on you fails outright.

### 6.6 Tier 6 — God-Tier (**weekly cooldown**, server-visible)
*Personal activation — you own the God, you press the button.*
- `/reshape-stars` (Aurelion Sol) — Re-roll a champion you own into another of the same tier.
- `/world-ender` (Aatrox) — Trigger a personal "War" buff: next 24h all your PvP wins double Gold; you can be attacked freely.
- `/wander` (Bard) — Execute any Tier 1–4 action for free, ignoring cooldown.
- `/portal` (Zoe) — Force-swap a champion 1-for-1 with another user (both must be same tier; target must consent within 1h or it cancels).

### 6.7 Tier 7 — Death (Kindred-only, **monthly cooldown**)
*The endgame. Server-shaking.*
- `/reap` — Mark a player. The next time they roll a champion you don't own, you get a copy instead. Lasts 7 days or until triggered. **Exclusive:** only one `/reap` mark can be active per target server-wide. Subsequent casters see *"Lamb already walks beside them."*
- `/lambs-respite` — Total PvP immunity for 72h. No exceptions.
- `/eternal-hunt` — See another user's exact loadout, Gold, and shield count for 7 days.
- `/never-one-without-the-other` — Force a tie on any one incoming PvP attempt against you (passive, auto-triggers once when held).

---

## 7. Currency & Items

- **Gold** — primary, earned everywhere.
- **Roll Tokens** — guaranteed roll, no Gold cost.
- **Fragments** — tier-specific; X fragments = guaranteed roll at that tier (pity system).
- **Mats** — Yordle/tinker output, feeds crafting.
- **Souls** — Shadow Isles drops, fuels Death-tier actions.
- **Shields** — Physical / Magic / Aegis / Stasis (see §5.3).
- **Corruption Stacks** — from Darkin actions; cosmetic + small Gold boost at thresholds.

---

## 8. Rolling

### 8.1 Roll Types — Multiplier Tiers
Every new player starts with **1 free Roll Token** to bootstrap.

| Command | Cost | Effect |
|---|---|---|
| `/roll` (1x) | base Gold | Standard odds — the default gamble |
| `/roll10` (10x) | 10× base Gold | Odds shift one tier up (Common rate ↓, Uncommon ↑, Rare ↑↑). ≥1 Tier 2 guaranteed |
| `/roll100` (100x) | 100× base Gold | Big odds shift toward higher tiers. ≥1 Tier 3 guaranteed. Realistic shot at Epic+ |
| `/roll1000` (1000x) | 1000× base Gold | Endgame "all-in." Massive shift. ≥1 Tier 4 guaranteed. Real shot at Legendary/God |

Multiplier rolls are **single weighted pulls**, not 10/100/1000 individual rolls — the multiplier is the *cost*, the shift toward better tiers is the reward. Keeps the gamble feeling, scales with player wealth.

### 8.2 Roll Costs
**Flat regardless of player level** — leveling makes you *earn* faster, not roll cheaper. Preserves the value of high-multiplier rolls at every stage.

### 8.3 Fragments & Duplicates
- **Duplicates** → auto-convert to Fragments of that tier. No dead pulls.
- **Conversion thresholds (placeholder):**
  - 10 Common Fragments → 1 guaranteed Common roll
  - 15 Uncommon → 1 guaranteed Uncommon
  - 25 Rare → 1 guaranteed Rare
  - 40 Epic → 1 guaranteed Epic
  - 75 Legendary → 1 guaranteed Legendary
  - 150 God Fragments → 1 guaranteed God roll
  - Death has no fragment path — only true rolls (or `/reap`).

### 8.4 Weighting Rules
- **Within-tier weighting:** individual champion drop weights are **randomly assigned at bot init** within each tier's range. Impersonal, removes "why is X rarer than Y" debates.
- **Death-tier rate scales with prestige:** base 1/1M → 1/500K after first Lv30 prestige.

---

## 9. Trading

- `/trade @user offer:<champ> request:<champ>` — both sides must `/accept` within **1 hour** or the trade auto-cancels. Short window forces synchronous trading and keeps the pending list clean.
- **Flat Gold tax** per trade (placeholder: 500 Gold, paid by initiator). Flat keeps high-tier trading from feeling punitive.
- Champions can be **locked** — locked champs can't be traded, sacrificed, or stolen.
- Tier mismatch allowed but logged (one user could low-ball, the other can refuse).
- Trade history per user viewable via `/trade-log @user`.

---

## 10. Tech Stack

- **Language / framework:** Python + **discord.py** (functionally parity with discord.js for our needs; user prefers Python).
- **DB:** **PostgreSQL** — picked over SQLite because we want to store champion art, shield icons, fragment images, etc. as either bytea or referenced from object storage with metadata in Postgres. Also gives us proper concurrency for PvP race conditions.
- **Hosting:** **Fly.io** — small VM + managed Postgres add-on. Easy deploys, free tier covers early single-server use.
- **Asset pipeline:** champion splash art from Riot's Data Dragon CDN, cached locally.

---

## 11. Resolved Decisions (locked in v0.3)

- **AP/AD/Hybrid tagging** — manual list maintained by us. Mistakes are easy fixes.
- **Per-champ drop weights** — randomly assigned at bot init within each tier's range.
- **PvP cap** — 3 attacks received per defender per 24h.
- **Lv30 prestige reward** — +5% Gold income (permanent) + improved Death-tier roll rate (1/1M → 1/500K).
- **Trading tax** — flat 500 Gold placeholder.
- **Trade window** — 1 hour, then auto-cancel.
- **Death tier rarity** — 1/1M base. Prestige is the only softener. No blanket pity.
- **Hosting** — Fly.io.
- **Combat model** — best-of-3 multi-round skirmish using Power scores + hidden d100 per round, with tier-difference modifier capped at +25%.
- **Economy direction** — tiered scaling (action payouts grow with level, roll costs stay flat). Starter: 1 free Roll Token.
- **Rolling** — multiplier rolls (1x / 10x / 100x / 1000x), each a single weighted pull with a guaranteed minimum tier.
- **Fragment conversion** — placeholder thresholds set (§8.3), Death tier has no fragment path.
- **Cooldown frame** — per-action pyramid (§6.0).
- **`/reap` collisions** — exclusive, one mark per target server-wide.

## 12. Still Open (tunables, not blockers for v1 build)

These are numbers/edge cases to dial in during implementation — none should block starting the code:

- Exact Gold curves per action per level (needs a balancing spreadsheet during build).
- Specific Power-score formula coefficients (HP/ATK/DEF derivation from tier — iterate via playtest).
- Multiplier roll exact odds shifts per tier (we'll start with reasonable defaults and tune).
- Per-action cooldowns where they deviate from the pyramid default.
- Server-wide event triggers (currently all God/Death actions are personal — fine for v1).

---

## 13. Out of Scope (v0.2)

- Cosmetic skins / chromas
- Voice channel integration
- Real money anything
- Multi-server support (single server only for v1)
