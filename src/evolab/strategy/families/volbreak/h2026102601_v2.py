"""
family: volbreak
hypothesis_id: H-2026-10-26-01
parent_id: volbreak-h2026102502-v2
hypothesis: >
  Két külön mechanizmust kapcsol össze. A rezsimfeltétel (új belépés csak az előző napi flat vagy
  up címke alatt) azokat a kitöréseket tartja meg, ahol a szűkülés felhalmozódást jelez, nem egy
  lefelé tartó trend szünetét. Ott a kitörés után a később érkező, trendkövető perp-longok tolják
  tovább az árat. Ugyanezek a késői, tőkeáttételes longok emelik meg a fundingot. Magas funding-z
  mellett a pozíció egyrészt maga fizeti a carry-t, másrészt a zsúfolt oldal sérülékeny lesz egy
  likvidációs visszarázásra. Ilyenkor a késői longok és a funding-fizetők veszítenek, mi pedig
  nekik adjuk el a pozíciót: ha funding_z(30 nap) > fz_take és a pozíció a belépés óta legalább
  1 ATR(14)-et mozdult a javunkra, lapos zárással kilépünk (shortnál tükrözve). A trailing stop
  csak a visszarázás után zárna, ezzel a nyereség egy részét visszaadnánk. A zárás után ugyanarra
  a kitörésre nincs újabb belépés, így a kilépés nem növeli a belépések számát és a költségterhet.
expected_regimes: [flat/low, flat/mid, up/low, up/mid]
falsifier: >
  Cáfolt, ha egyik változatnál sem nő a 2x költségű PF a szülőéhez képest, vagy ha a
  profitrealizáló kilépések átlagos hozama a kilépés utáni 12 gyertyában (ahonnan a szülő tovább
  tartana) nem negatív. Akkor is cáfolt, ha az OOS/IS 0.5 alá esik, vagy a kötésszám 100 alá csökken.
"""


import pandas as pd

from evolab.features.indicators import atr
from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2.5, 'take_atr': 1.0}


def _take_profit(d, p, reg):
    # a szülő (volbreak-h2026102502-v2) jele változatlanul
    sig = lib.squeeze_breakout_signal(d, p)
    t = sig["target_position"]
    trend_ok = reg["trend"].isin(list(p["allowed_trend"])) if reg is not None else pd.Series(False, index=d.index)
    run = (t != t.shift()).cumsum()
    keep = trend_ok.reindex(d.index).fillna(False).astype(bool).groupby(run).transform("first")
    sig = lib.condition(sig, keep | (t == 0), "trend_gate")
    t = sig["target_position"]

    # belépő gyertya zárása és az akkor ismert ATR, szakaszonként
    c = d["close"]
    entry_c = c.groupby(run).transform("first")
    entry_atr = atr(d, p["atr_n"]).groupby(run).transform("first")
    move = (c - entry_c) * t  # a pozíció javára mért elmozdulás
    moved = move >= p["take_atr"] * entry_atr

    z = lib.funding_z(d, p["fz_days"])
    take = moved & (((t > 0) & (z > p["fz_take"])) | ((t < 0) & (z < -p["fz_take"])))
    # a realizálás után a szakasz végéig lapos: ugyanarra a kitörésre nincs újabb belépés
    done = take.astype(int).groupby(run).cummax().astype(bool)
    out = lib.condition(sig, ~done)
    out.loc[take, "reason"] = "crowd_take_profit"
    return out


def signals(bars, regime, params):
    return lib.per_symbol(bars, _take_profit, params, regime)
