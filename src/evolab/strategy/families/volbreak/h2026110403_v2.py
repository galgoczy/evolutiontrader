"""
family: volbreak
hypothesis_id: H-2026-11-04-03
parent_id: volbreak-h2026110301-v2
hypothesis: >
  Két, külön-külön átment módosítás keresztezése, amelyek különböző mechanizmust céloznak, ezért elvben
  kiegészítik egymást. A funding-felülbírálat ott enged kitörést, ahol a kitöréssel szemben álló oldal
  tőkeáttételesen zsúfolt: ezek a szereplők a kitörésnél stopolnak vagy likvidálódnak, és az áramlásuk
  a mozgást erősíti. A down/down short-bővítés a piaci szintű leépülést célozza: ha a BTC és az
  altcoin is lefelé trendel, a lefelé kitörést a kockázatkerülő tőkekivonás és a long-likvidációk
  hajtják, és az altcoinok magasabb bétája miatt ezek a mozgások tartósabbak. A vesztes oldal mindkét
  esetben a rossz irányban tőkeáttétellel beszorult perp-pozíció. Elsőbbségi sorrend: (1) a coin
  rezsimfeltétele (long flat/up, short flat) a down/down bővítéssel (altcoin short, ha a coin és a
  BTCUSDT előző napi címkéje is down; a BTCUSDT saját down-shortja csak btc_short_down esetén),
  (2) a funding-felülbírálat (fz_against 2) csak a még tiltott eseteket oldja fel, (3) a BTC-vezető
  tiltás (both mód) mindig az utolsó lépés. A tiltott kitörést később sem pótoljuk; a nyitott pozíció,
  az ATR-trailing és a funding-alapú profitrealizálás a szülőé. Ha az él valódi, a két feltétel
  nagyrészt diszjunkt kötéshalmazt ad, és a kombináció PF-je nem romlik.
expected_regimes: [flat/low, flat/mid, down/mid, down/high, up/mid]
falsifier: >
  Cáfolt, ha egyik variáns PF 2x értéke sem éri el a jobbik szülőét (1.66), vagy ha a PBO >= 0.2.
  Szintén cáfolt, ha a down/down bővítésből származó kötések PF 2x értéke < 1.0, vagyis a bővítés
  csak zajt ad a funding-felülbírálathoz.
"""


import pandas as pd

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2, 'take_atr': 1.0, 'short_allowed': ['flat'], 'btc_block_mode': 'both', 'fz_against': 2, 'btc_short_down': False}

# a kitörés + ATR-trailing + funding-realizálás a volbreak-h2026102601-v1 jele, címkeszűrés nélkül;
# a rezsimfeltételt (down/down bővítéssel), a funding-felülbírálatot és a BTC-vezető tiltást itt alkalmazzuk
BASE = "volbreak-h2026102601-v1"
BTC = "BTCUSDT"
ALL_TRENDS = ["flat", "up", "down"]


def _gate(d, p, reg, base, btc_trend):
    sig = base.loc[d.index]
    t = sig["target_position"]
    run = (t != t.shift()).cumsum()
    is_btc = d.index.get_level_values("symbol")[0] == BTC

    # a coin és a BTC (előző napi) címkéje; BTC-gyertya hiányakor az utolsó ismert címke
    own = reg["trend"].reindex(d.index) if reg is not None else pd.Series(index=d.index, dtype=object)
    ts = d.index.get_level_values("ts")
    btc = own if is_btc else pd.Series(btc_trend.reindex(ts, method="ffill").to_numpy(), index=d.index)
    z = lib.funding_z(d, p["fz_days"])

    # (1) a coin rezsimfeltétele a down/down short-bővítéssel
    long_rule = own.isin(list(p["allowed_trend"]))
    short_flat = own.isin(list(p["short_allowed"]))
    down_short = (own == "down") & (btc == "down")
    if is_btc and not p["btc_short_down"]:
        down_short = pd.Series(False, index=d.index)
    # (2) funding-felülbírálat: a kitöréssel ellentétes oldal zsúfolt (a gyertya zárásáig ismert funding-z)
    long_override = (own == "down") & (z < -p["fz_against"])
    short_override = own.isin(["up", "down"]) & (z > p["fz_against"])

    # a döntés a szakasz elején (belépő gyertya) születik, a nyitott pozíciót később nem érinti
    first = lambda s: s.fillna(False).astype(bool).groupby(run).transform("first")
    lr, lo = first(long_rule), first(long_override)
    sf, ds, so = first(short_flat), first(down_short), first(short_override)
    long_ok = lr | lo
    short_ok = sf | ds | so

    # (3) BTC-vezető tiltás csak altcoinokra, utolsó lépésként (both: a short is tiltott BTC up alatt)
    block_long = ~long_ok
    block_short = ~short_ok
    if not is_btc:
        block_long = block_long | first(btc == "down")
        block_short = block_short | (first(btc == "up") & (p["btc_block_mode"] == "both"))
    out = lib.block_direction(sig, block_long, block_short)
    out.loc[((t > 0) & block_long) | ((t < 0) & block_short), "reason"] = ""
    live = out["target_position"]
    out.loc[(live > 0) & ~lr & lo, "reason"] = "squeeze_break_up|crowd_override"
    out.loc[(live < 0) & ~sf & ds, "reason"] = "squeeze_break_down|btc_down_short"
    out.loc[(live < 0) & ~sf & ~ds & so, "reason"] = "squeeze_break_down|crowd_override"
    return out


def signals(bars, regime, params):
    base_p = {k: v for k, v in params.items() if k not in ("short_allowed", "btc_block_mode", "fz_against", "btc_short_down")}
    base = lib.parent_signals(BASE, bars, regime, {**base_p, "allowed_trend": ALL_TRENDS})
    has_btc = regime is not None and BTC in regime.index.get_level_values("symbol")
    btc_trend = regime.xs(BTC, level="symbol")["trend"].sort_index() if has_btc else pd.Series(dtype=object, index=pd.Index([], dtype="int64"))
    return lib.per_symbol(bars, lambda d, p, reg: _gate(d, p, reg, base, btc_trend), params, regime)
