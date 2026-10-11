"""Kombinatorikus tisztított keresztvalidáció (CPCV, docs/02-specifikacio.md 5.3). VÉDETT.

A holdout nélküli napi idősor `n_blocks` egyenlő, egymást követő blokkra oszlik; minden `k_test`
blokkos kombináció (8 blokk, k=2: 28 kombináció) egy teszthalmaz, a többi blokk a tanuló halmaz.
Tisztítás: a tanuló halmazból kiesik minden nap, ami a teszt-blokk előtti `purge_days` napon belül
van (a teszttel átfedő címkék), és a teszt-blokk utáni `embargo_days` nap (szivárgás a jövőből).
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


def splits(days: pd.DatetimeIndex, n_blocks: int, k_test: int, purge_days: int, embargo_days: int
           ) -> list[tuple[np.ndarray, np.ndarray]]:
    """(tanuló maszk, teszt maszk) párok a `days` napokra, kombinációnként."""
    n = len(days)
    edges = np.linspace(0, n, n_blocks + 1).astype(int)
    block = np.searchsorted(edges, np.arange(n), side="right") - 1
    out = []
    for test_blocks in combinations(range(n_blocks), k_test):
        test = np.isin(block, test_blocks)
        train = ~test
        for b in test_blocks:
            start, end = days[edges[b]], days[edges[b + 1] - 1]
            near = (days >= start - pd.Timedelta(days=purge_days)) & (days <= end + pd.Timedelta(days=embargo_days))
            train &= ~np.asarray(near)
        out.append((train, test))
    return out
