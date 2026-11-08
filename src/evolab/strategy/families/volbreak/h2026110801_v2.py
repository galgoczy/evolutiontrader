"""
family: volbreak
hypothesis_id: H-2026-11-08-01
parent_id: volbreak-h2026110602-v1
hypothesis: >
  Két versengő mechanizmus van, és a két mód ezeket választja szét. Piacszintű összenyomódáskor (a
  BTC is szűk) a volatilitás-eladók és a szűk sávban opciós fedezést végző árjegyzők rövid gammája
  együtt oldódik fel. A kitörést ilyenkor a piaci tényező hajtja, a sáv két oldalán felhalmozott
  stopok és likvidációk az egész komplexumon egyszerre sülnek el. A vesztes oldal a sávra fogadó,
  mean-reversion pozíciót tartó szereplő. A trendkövető tőke ilyenkor a kosárba áramlik, így a
  kitörés tartósabb. Ha viszont csak az altcoin szűkült, a kitörés gyakran egyedi hír vagy vékony
  könyv miatt jön, és a BTC-ből érkező tényező-zaj könnyen visszanyomja, ami hamis kitöréseket ad.
  A szülő bb_mid-igazítása az irányt már kezeli, a volatilitás-állapot egyezését viszont nem.
  Altcoin-kitörés belépő gyertyáján megnézzük, hogy a BTCUSDT Bollinger-sávszélesség-percentilise
  (bb_n, bb_k, pct_window) az utolsó btc_sq_lookback gyertya bármelyikén squeeze_pct alatt volt-e
  (a belépő gyertya nem számít). require: csak BTC-szűkülés mellett nyit; exclude: csak anélkül.
  A tiltott kitörést később sem pótoljuk; a BTC saját belépései és a szülő teljes láncolata változatlan.
expected_regimes: [flat/low, flat/mid, up/low, up/mid]
falsifier: >
  Cáfolt, ha a 'require' változat PF 2x költségnél nem haladja meg a szülőét legalább 0.05-tel,
  miközben az 'exclude' változat PF-je sem rosszabb a szülőénél (ilyenkor a BTC-szűkülés nem
  különíti el a jó és rossz kitöréseket). Szintén cáfolt, ha a 'require' változat kötésszáma 100
  alá esik, vagy a PBO legalább 0.2.
"""


import pandas as pd

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2, 'take_atr': 1.0, 'short_allowed': ['flat'], 'btc_block_mode': 'both', 'fz_against': 2, 'align_mode': 'bb_mid', 'btc_sq_mode': 'exclude', 'btc_sq_lookback': 6}

# a szülő teljes láncolata (rezsimfeltétel, funding-felülbírálat, bb_mid-igazítás, napi BTC-tiltás,
# ATR-trailing, funding-realizálás) a volbreak-h2026110602-v1 jele; erre jön a BTC-szűkülés feltétele
PARENT = "volbreak-h2026110602-v1"
BTC = "BTCUSDT"


def _btc_squeezed(btc_bars, p):
    """Igaz, ha a BTC sávszélesség-percentilise az előző btc_sq_lookback gyertya bármelyikén küszöb alatt volt."""
    if btc_bars.empty:
        return pd.Series(dtype=bool, index=pd.Index([], dtype="int64"))
    w = lib.bollinger(btc_bars["close"], p["bb_n"], p["bb_k"])["width"]
    pct = w.rolling(p["pct_window"], min_periods=p["pct_window"] // 2).rank(pct=True) * 100
    sq = (pct < p["squeeze_pct"]).astype(float).rolling(p["btc_sq_lookback"], min_periods=1).max().shift(1)
    return sq > 0


def _gate(d, p, base, btc_sq):
    sig = base.loc[d.index]
    if d.index.get_level_values("symbol")[0] == BTC:
        return sig
    t = sig["target_position"]
    run = (t != t.shift()).cumsum()

    # a BTC szűkülési állapota a coin gyertyáira; BTC-gyertya hiányakor az utolsó ismert
    ts = d.index.get_level_values("ts")
    if btc_sq.empty:
        sq = pd.Series(False, index=d.index)
    else:
        sq = pd.Series(btc_sq.reindex(ts, method="ffill").to_numpy(), index=d.index).fillna(False).astype(bool)
    ok = sq if p["btc_sq_mode"] == "require" else ~sq

    # a döntés a szakasz elején (belépő gyertya) születik; a tiltott kitörés később sem nyílik meg
    allowed = ok.groupby(run).transform("first") | (t == 0)
    out = lib.condition(sig, allowed, f"btc_sq_{p['btc_sq_mode']}")
    out.loc[~allowed, "reason"] = ""
    return out


def signals(bars, regime, params):
    base_p = {k: v for k, v in params.items() if k not in ("btc_sq_mode", "btc_sq_lookback")}
    base = lib.parent_signals(PARENT, bars, regime, base_p)
    btc_bars = bars.xs(BTC, level="symbol").sort_index() if BTC in bars.index.get_level_values("symbol") else bars.iloc[:0]
    btc_sq = _btc_squeezed(btc_bars, params)
    return lib.per_symbol(bars, lambda d, p, reg: _gate(d, p, base, btc_sq), params)
