"""Deterministic per-champion drop-weight assignment.

PRD §8.4: within each tier, individual champion weights are randomly assigned
at first DB seed and never changed. Determinism keeps the seed reproducible
across re-runs of `migrate.py` on the same DB — but in practice the value is
only written once (existing rows keep their weight forever).
"""
from __future__ import annotations

import hashlib
import struct

# Tier rate bounds, derived from PRD §2. Each entry is (low, high) inclusive.
# These are drop *rates* (probability mass within the tier's slot). Rolling
# logic will combine these with overall tier weights.
TIER_BOUNDS: dict[int, tuple[float, float]] = {
    1: (1 / 10,        1 / 2),
    2: (1 / 50,        1 / 10),
    3: (1 / 500,       1 / 50),
    4: (1 / 5_000,     1 / 500),
    5: (1 / 100_000,   1 / 5_000),
    6: (1 / 1_000_000, 1 / 100_000),
    7: (1 / 10_000_000, 1 / 1_000_000),
}


def _hash_unit(name: str, seed: str) -> float:
    """Return a deterministic float in [0, 1) for (name, seed)."""
    digest = hashlib.sha256(f"{seed}|{name}".encode("utf-8")).digest()
    (raw,) = struct.unpack(">Q", digest[:8])
    return raw / 2**64


def assign_drop_weight(name: str, tier: int, seed: str) -> float:
    """Deterministic uniform sample inside the tier's drop-rate range."""
    if tier not in TIER_BOUNDS:
        raise ValueError(f"Invalid tier {tier}; expected 1-7.")
    low, high = TIER_BOUNDS[tier]
    u = _hash_unit(name, seed)
    return low + u * (high - low)
