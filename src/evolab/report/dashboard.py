"""Dashboard v1 (docs/02-specifikacio.md 8.): statikus HTML, `reports/index.html`.

A napi riport adatából (`report.daily.build`) és a futások equity-görbéiből készül, keretrendszer
nélkül. Grafikon: a paper-névsor variánsainak equity-görbéje kis többszörösként (egy vonal / ábra,
így nincs színkülönbség-függés), a visszateszt (2020 – holdout-határ) és – ha már van – a paper.
Világos és sötét mód a rendszerbeállítás szerint.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from evolab.config import Config
from evolab.live import paper_runner as pr

MAX_POINTS = 400

CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--line:#2a78d6;--ring:rgba(11,11,11,.10);--good:#006300;--bad:#d03b3b;
--div-neg:#2a78d6;--div-pos:#e34948;--div-mid:#f0efec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;
--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--line:#3987e5;
--ring:rgba(255,255,255,.10);--good:#0ca30c;--bad:#e66767;--div-neg:#3987e5;--div-pos:#e66767;--div-mid:#383835}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--grid:#2c2c2a;--axis:#383835;--line:#3987e5;--ring:rgba(255,255,255,.10);--good:#0ca30c;--bad:#e66767;
--div-neg:#3987e5;--div-pos:#e66767;--div-mid:#383835}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:16px}h1{font-size:20px;margin:8px 0 2px}
h2{font-size:15px;margin:28px 0 8px}.sub{color:var(--ink2);margin:0 0 12px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.tile,.card{background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:12px}
.tile b{display:block;font-size:24px;font-weight:600}.tile span{color:var(--ink2)}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--surface);font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--ink2);font-weight:600}th.n{text-align:right}td.n{text-align:right;font-variant-numeric:tabular-nums}
.pass{color:var(--good);font-weight:600}.fail{color:var(--bad)}.fails{white-space:normal;color:var(--ink2);min-width:260px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.card h3{font-size:13px;margin:0 0 4px}.card p{margin:0;color:var(--ink2);font-size:12px}
svg{display:block;width:100%;height:auto}svg .gl{stroke:var(--grid)}svg .ax{fill:var(--muted);font-size:10px}
svg .ln{fill:none;stroke:var(--line);stroke-width:2;stroke-linejoin:round}
svg .xh{stroke:var(--axis);visibility:hidden}svg .dot{fill:var(--line);stroke:var(--surface);stroke-width:2;visibility:hidden}
.tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--ring);
border-radius:6px;padding:4px 8px;font-size:12px;display:none;box-shadow:0 2px 8px rgba(0,0,0,.12)}
.empty{color:var(--muted);font-size:12px;padding:24px 0;text-align:center}
.heat{border-collapse:separate;border-spacing:2px;background:transparent;width:auto}.heat td{width:44px;height:28px;text-align:center;font-size:11px;border:0;border-radius:4px;font-variant-numeric:tabular-nums;color:var(--ink)}.heat th{font-size:11px;font-weight:500;border:0;padding:2px 6px}.heat th.col{writing-mode:vertical-rl;transform:rotate(180deg);height:210px;text-align:left;white-space:nowrap}.legend{display:flex;align-items:center;gap:8px;color:var(--ink2);font-size:12px;margin:8px 0}.legend i{display:inline-block;width:120px;height:10px;border-radius:5px;background:linear-gradient(90deg,var(--div-neg),var(--div-mid),var(--div-pos))}
"""

JS = """
const tip=document.querySelector('.tip');
document.querySelectorAll('svg[data-pts]').forEach(svg=>{
 const pts=JSON.parse(svg.dataset.pts),xh=svg.querySelector('.xh'),dot=svg.querySelector('.dot');
 svg.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*300;
  let best=pts[0];for(const p of pts){if(Math.abs(p[0]-x)<Math.abs(best[0]-x))best=p}
  xh.setAttribute('x1',best[0]);xh.setAttribute('x2',best[0]);xh.style.visibility='visible';
  dot.setAttribute('cx',best[0]);dot.setAttribute('cy',best[1]);dot.style.visibility='visible';
  tip.textContent=best[2]+' · '+best[3];tip.style.display='block';
  tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY-28)+'px'});
 svg.addEventListener('mouseleave',()=>{xh.style.visibility='hidden';dot.style.visibility='hidden';tip.style.display='none'});
});
"""


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _num(v, fmt="{:.2f}") -> str:
    return "–" if v is None or (isinstance(v, float) and v != v) else fmt.format(v)


def short_failures(text: str | None) -> str:
    """A bukott kapuk rövidítve: a paraméter-stabilitásnál csak a negatív változatok száma."""
    if not text:
        return "–"
    parts = []
    for f in text.split("; "):
        if f.startswith("paraméter-stabilitás: negatív lett "):
            n = len(f.removeprefix("paraméter-stabilitás: negatív lett ").split(", "))
            f = f"paraméter-stabilitás: {n} változat negatív"
        parts.append(f)
    return "; ".join(parts)


def line_chart(equity: pd.DataFrame, label: str) -> str:
    """Egy vonalas equity-ábra (300×120), crosshair-tooltippel. `equity`: ts (ms, zárás), equity."""
    if equity is None or equity.empty:
        return f'<div class="empty">{_esc(label)}: még nincs lezárt gyertya</div>'
    e = equity.iloc[:: max(1, len(equity) // MAX_POINTS)]
    if e.index[-1] != equity.index[-1]:
        e = pd.concat([e, equity.iloc[[-1]]])
    x0, x1 = float(e["ts"].iloc[0]), float(e["ts"].iloc[-1])
    y0, y1 = float(e["equity"].min()), float(e["equity"].max())
    pad = (y1 - y0) * 0.08 or 1.0
    y0, y1 = y0 - pad, y1 + pad
    left, right, top, bottom = 34.0, 296.0, 8.0, 100.0

    def px(t):
        return left + (t - x0) / ((x1 - x0) or 1) * (right - left)

    def py(v):
        return bottom - (v - y0) / (y1 - y0) * (bottom - top)

    pts = [[round(px(t), 1), round(py(v), 1), pd.Timestamp(int(t), unit="ms", tz="UTC").strftime("%Y-%m-%d"),
            f"{v:,.0f} USD".replace(",", " ")] for t, v in zip(e["ts"], e["equity"])]
    d = "M" + " L".join(f"{p[0]},{p[1]}" for p in pts)
    grid = "".join(f'<line class="gl" x1="{left}" x2="{right}" y1="{py(v):.1f}" y2="{py(v):.1f}"/>'
                   f'<text class="ax" x="{left - 4}" y="{py(v) + 3:.1f}" text-anchor="end">{v / 1000:.1f}k</text>'
                   for v in (y0 + pad, (y0 + y1) / 2, y1 - pad))
    xlab = (f'<text class="ax" x="{left}" y="116">{pts[0][2]}</text>'
            f'<text class="ax" x="{right}" y="116" text-anchor="end">{pts[-1][2]}</text>')
    return (f'<svg viewBox="0 0 300 120" role="img" aria-label="{_esc(label)} equity" '
            f"data-pts='{json.dumps(pts)}'>{grid}<path class=\"ln\" d=\"{d}\"/>"
            f'<line class="xh" x1="0" x2="0" y1="{top}" y2="{bottom}"/><circle class="dot" r="4"/>{xlab}</svg>')


def heatmap(ids: list[str], matrix: list[list[float]], corr_max: float) -> str:
    """Korrelációs hőtérkép: eltérő skála kék (−1) – szürke (0) – piros (+1); az érték a cellában is."""
    if len(ids) < 2:
        return '<div class="empty">A diverzitáshoz legalább 2 egyed hozamsora kell.</div>'
    head = "".join(f"<th class='col'>{_esc(i)}</th>" for i in ids)
    rows = []
    for a, row in zip(ids, matrix):
        cells = []
        for b, v in zip(ids, row):
            pole = "var(--div-pos)" if v >= 0 else "var(--div-neg)"
            pct = round(min(1.0, abs(v)) * 100)
            mark = " ●" if a != b and v > corr_max else ""
            cells.append(f"<td style='background:color-mix(in oklab, {pole} {pct}%, var(--div-mid))' "
                         f"title='{_esc(a)} × {_esc(b)}: {v:.2f}'>{v:.2f}{mark}</td>")
        rows.append(f"<tr><th>{_esc(a)}</th>{''.join(cells)}</tr>")
    return (f"<div class='legend'><span>−1</span><i></i><span>+1</span><span>● = korreláció > {corr_max} "
            f"(a gyengébb DSR-ű büntetést kap)</span></div><div class='wrap'><table class='heat'>"
            f"<tr><th></th>{head}</tr>{''.join(rows)}</table></div>")


def _backtest_equity(variant: dict) -> pd.DataFrame | None:
    out = variant.get("out_dir")
    p = Path(out) / "equity.parquet" if out else None
    return pd.read_parquet(p) if p and p.exists() else None


def build_html(cfg: Config, r: dict) -> str:
    variants = sorted(r["variants"], key=lambda v: -(v["dsr"] or 0))
    passed = sum(f["passed"] for f in r["families"])
    total = sum(f["variants"] for f in r["families"])
    cov = min((h["coverage"] for h in r["recorder"].values()), default=0.0)
    tiles = [(f"{passed}/{total}", "átment L1-en"), (str(len(r["awaiting_approval"])), "jóváhagyásra vár"),
             (str(len(r["paper"])), "stratégia paperben"), (f"{100 * cov:.1f}%", "rögzítő lefedettség, 24 óra"),
             (f"v{r['judge_version']}", "bíró (judge.yaml)")]
    H = [f'<!doctype html><html lang="hu"><head><meta charset="utf-8">'
         f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>EvolutionTrader</title>'
         f"<style>{CSS}</style></head><body><main>",
         f"<h1>EvolutionTrader</h1><p class=\"sub\">Napi állapot – {r['date']}</p>",
         '<div class="tiles">' + "".join(f'<div class="tile"><b>{_esc(a)}</b><span>{_esc(b)}</span></div>'
                                         for a, b in tiles) + "</div>"]
    H.append("<h2>Családok</h2><div class='wrap'><table><tr><th>család</th><th class='n'>variáns</th><th class='n'>átment L1-en</th>"
             "<th class='n'>futás (90 nap)</th><th class='n'>konfiguráció</th><th class='n'>hatékony N</th><th class='n'>DSR-küszöb (SR0, évesített)</th></tr>")
    tc = {t["family"]: t for t in r["trial_counts"]}
    for f in r["families"]:
        t = tc.get(f["family"], {})
        H.append(f"<tr><td>{_esc(f['family'])}</td><td class='n'>{f['variants']}</td><td class='n'>{f['passed']}</td>"
                 f"<td class='n'>{t.get('runs', '–')}</td><td class='n'>{t.get('configs', '–')}</td>"
                 f"<td class='n'>{t.get('n_eff', '–')}</td><td class='n'>{_num(t.get('sr0_annual'))}</td></tr>")
    H.append("</table></div>")
    H.append("<h2>Torna-rangsor (L1, DSR szerint)</h2><div class='wrap'><table><tr><th>variáns</th><th>család</th>"
             "<th>ítélet</th><th class='n'>kötés</th><th class='n'>PF 1x</th><th class='n'>PF 2x</th><th class='n'>DSR</th><th class='n'>PBO</th><th class='n'>max DD</th>"
             "<th class='n'>OOS/IS</th><th class='n'>rezsim+</th><th>bukott kapuk</th></tr>")
    for v in variants:
        H.append(f"<tr><td>{_esc(v['strategy_id'])}</td><td>{_esc(v['family'])}</td>"
                 f"<td class='{_esc(v['result'])}'>{_esc(v['result'])}</td><td class='n'>{v['trades']}</td>"
                 f"<td class='n'>{_num(v['pf_1x'])}</td><td class='n'>{_num(v['pf_2x'])}</td>"
                 f"<td class='n'>{_num(v['dsr'], '{:.3f}')}</td><td class='n'>{_num(v['pbo'])}</td>"
                 f"<td class='n'>{_num(v['max_dd_pct'], '{:.1f}%')}</td><td class='n'>{_num(v['oos_is'])}</td>"
                 f"<td class='n'>{v['regimes_pos']}</td><td class='fails'>{_esc(short_failures(v['failures']))}</td></tr>")
    H.append("</table></div>")
    H.append("<h2>Élő paper (Hyperliquid)</h2><div class='wrap'><table><tr><th>stratégia</th><th>mód</th><th>nap</th>"
             "<th>kötés</th><th>nyitott</th><th>hozam</th><th>max DD</th><th>eltérés a visszateszttől</th></tr>")
    for p in r["paper"]:
        m = "–" if p["match_ok"] is None else ("OK" if p["match_ok"] else "ELTÉR")
        H.append(f"<tr><td>{_esc(p['strategy_id'])}</td><td>{_esc(p['mode'])}</td><td class='n'>{_num(p['days'], '{:.1f}')}</td>"
                 f"<td class='n'>{p['trades'] or 0}</td><td class='n'>{p['open_positions'] or 0}</td>"
                 f"<td class='n'>{_num(p['return_pct'], '{:+.2f}%')}</td><td class='n'>{_num(p['max_dd_pct'], '{:.1f}%')}</td>"
                 f"<td class='n'>{_num(p['diff_pct'], '{:.2f}%')} {m}</td></tr>")
    H.append("</table></div>")
    by_id = {v["strategy_id"]: v for v in r["variants"]}
    H.append("<h2>Equity-görbék: paper-névsor</h2><p class='sub'>Felül a visszateszt (2020 – holdout-határ), "
             "alul az élő paper. Mozgasd az egeret a görbe fölött az értékekért.</p><div class='grid'>")
    for p in r["paper"]:
        sid = p["strategy_id"]
        bt = _backtest_equity(by_id.get(sid, {}))
        pe = pr.paper_dir(cfg) / sid / "equity.parquet"
        paper_eq = pd.read_parquet(pe) if pe.exists() else None
        H.append(f"<div class='card'><h3>{_esc(sid)}</h3><p>visszateszt</p>{line_chart(bt, 'visszateszt')}"
                 f"<p>paper</p>{line_chart(paper_eq, 'paper')}</div>")
    H.append("</div>")
    dv = r.get("diversity") or {}
    if dv.get("ranking"):
        H.append("<h2>Diverzitás (paper-névsor)</h2><p class='sub'>Napi hozamok korrelációja; a rangsor-DSR a "
                 "büntetés utáni érték (spec 5.7).</p>")
        H.append(heatmap(dv["corr"]["ids"], dv["corr"]["matrix"], dv["corr_max"]))
        H.append("<div class='wrap'><table><tr><th>rang</th><th>stratégia</th><th class='n'>DSR</th>"
                 "<th class='n'>rangsor-DSR</th><th>büntetve (hasonló ehhez)</th></tr>")
        H += [f"<tr><td class='n'>{k}</td><td>{_esc(d['strategy_id'])}</td><td class='n'>{_num(d['dsr'], '{:.3f}')}</td>"
              f"<td class='n'>{_num(d['dsr_ranked'], '{:.3f}')}</td><td>{_esc(d['penalized_by'] or '–')}</td></tr>"
              for k, d in enumerate(dv["ranking"], 1)]
        H.append("</table></div>")
    H.append("<h2>Slippage: mért vs. modell</h2><div class='wrap'><table><tr><th>coin</th><th>minta</th>"
             "<th>mért (medián)</th><th>mért p95</th><th>modell (4h)</th></tr>")
    for s in r["slippage"]:
        H.append(f"<tr><td>{_esc(s['symbol'])}</td><td class='n'>{s['samples']}</td>"
                 f"<td class='n'>{_num(s.get('measured_pct'), '{:.4f}%')}</td>"
                 f"<td class='n'>{_num(s.get('measured_p95_pct'), '{:.4f}%')}</td>"
                 f"<td class='n'>{_num(s.get('model_pct'), '{:.4f}%')}</td></tr>")
    H.append("</table></div><h2>Rezsim (legutolsó napi címke)</h2><div class='wrap'><table><tr><th>coin</th>"
             "<th>nap</th><th>trend</th><th>vol</th><th>pozícionáltság</th></tr>")
    H += [f"<tr><td>{_esc(g['symbol'])}</td><td>{_esc(g['date'])}</td><td>{_esc(g['trend'])}</td>"
          f"<td>{_esc(g['vol'])}</td><td>{_esc(g['positioning'])}</td></tr>" for g in r["regime"]]
    H.append(f"</table></div></main><div class='tip'></div><script>{JS}</script></body></html>")
    return "".join(H)


def write(cfg: Config, r: dict) -> Path:
    path = cfg.path("reports") / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_html(cfg, r), encoding="utf-8")
    return path
