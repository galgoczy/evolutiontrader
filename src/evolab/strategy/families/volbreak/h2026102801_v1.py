"""
family: volbreak
hypothesis_id: H-2026-10-28-01
parent_id: volbreak-h2026102701-v1
hypothesis: >
  Pozícionáltsági felülbírálat a rezsimfeltételen. A szűkülés alatt a tőkeáttételes perp-szereplők
  a sáv két szélén halmozzák fel a stopjaikat és a likvidációs szintjeiket. Ha a funding erősen
  negatív, a shortok fizetnek a pozíciójuk tartásáért, és a sáv fölött sűrűn ülnek a
  kényszerzárásaik. Egy felfelé kitörés ezeket egymás után kiüti: a likvidációs motor piaci áron
  vesz, ami tovább viszi az árat (short squeeze). Ez a kaszkád a trendcímkétől függetlenül működik,
  ezért éppen a szülő által tiltott rezsimekben adhat többletkötést. A vesztes oldal a zsúfolt,
  tőkeáttételes kisbefektető, akit a likvidáció és a funding-teher kényszerít ki. Tükrözve ugyanez
  igaz pozitív funding mellett a lefelé kitörésre. Ezért a felfelé kitörés down címke alatt is
  érvényes, ha funding_z(30) < -fz_against, a lefelé kitörés up vagy down címke alatt is, ha
  funding_z(30) > +fz_against (a kitörő gyertya zárásáig ismert érték). A szülő által megengedett
  rezsimekben, a nyitott pozíción, az ATR-trailingen és a funding-alapú profitrealizáláson semmi
  sem változik.
expected_regimes: [down/low, down/mid, up/mid, up/high]
falsifier: >
  Cáfolt, ha a felülbírálat által hozzáadott kötések (a szülő által tiltott rezsimben nyitottak)
  részhalmazán a PF 2x költségnél < 1.1, vagy ha a variáns teljes PF-je 2x költségnél nem éri el
  a szülő 1.53-as értékét, vagy ha a PBO >= 0.2.
"""


import pandas as pd

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2, 'take_atr': 1.0, 'short_allowed': ['flat'], 'fz_against': 1}

# a szülő (volbreak-h2026102701-v1) a nagyszülő jelét szűri; a felülbírálat a szülő által
# eldobott kitöréseket is visszaadhatja, ezért a nagyszülőt rezsimszűrés nélkül hívjuk,
# és a teljes belépési feltételt (szülő + felülbírálat) itt alkalmazzuk
BASE = "volbreak-h2026102601-v1"
ALL_TRENDS = ["flat", "up", "down"]


def _override_gate(d, p, reg, base):
    sig = base.loc[d.index]
    t = sig["target_position"]
    run = (t != t.shift()).cumsum()

    trend = reg["trend"].reindex(d.index) if reg is not None else pd.Series(index=d.index, dtype=object)
    z = lib.funding_z(d, p["fz_days"])
    # szülő szerinti engedély
    long_parent = trend.isin(list(p["allowed_trend"]))
    short_parent = trend.isin(list(p["short_allowed"]))
    # felülbírálat: a kitöréssel ellentétes oldal zsúfolt (a kitörő gyertya zárásáig ismert funding-z)
    long_override = (trend == "down") & (z < -p["fz_against"])
    short_override = trend.isin(["up", "down"]) & (z > p["fz_against"])

    # a döntés a szakasz elején (belépő gyertya) születik, a nyitott pozíciót később nem érinti
    first = lambda s: s.fillna(False).astype(bool).groupby(run).transform("first")
    lp, lo = first(long_parent), first(long_override)
    sp, so = first(short_parent), first(short_override)
    long_ok, short_ok = lp | lo, sp | so

    out = lib.block_direction(sig, ~long_ok, ~short_ok)
    out.loc[((t > 0) & ~long_ok) | ((t < 0) & ~short_ok), "reason"] = ""
    out.loc[(t > 0) & ~lp & lo, "reason"] = "squeeze_break_up|crowd_override"
    out.loc[(t < 0) & ~sp & so, "reason"] = "squeeze_break_down|crowd_override"
    return out


def signals(bars, regime, params):
    base_p = {k: v for k, v in params.items() if k not in ("short_allowed", "fz_against")}
    base_p["allowed_trend"] = ALL_TRENDS
    base = lib.parent_signals(BASE, bars, regime, base_p)
    return lib.per_symbol(bars, lambda d, p, reg: _override_gate(d, p, reg, base), params, regime)
