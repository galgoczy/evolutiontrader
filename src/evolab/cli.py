"""`evolab` parancssori felület."""

from __future__ import annotations

import argparse
import datetime as dt
import platform
import sys

from evolab import __version__
from evolab.config import load_config
from evolab.db import connect, init_db, list_tables
from evolab.notify import telegram

# A napi futás lépései (docs/02-specifikacio.md 6.1), mind valódi a 6. fázistól.
DAILY_STEPS = ["data", "judge", "report", "researcher", "developer", "ladder"]


def step_data(cfg) -> str:
    """Binance pótlás + rezsimcímkék (szabályalapú és HMM-variáns). (A Hyperliquid rögzítő külön folyamat.)"""
    from evolab.data import binance_bulk
    from evolab.features import regime

    from evolab.features import regime_hmm

    rep = binance_bulk.update(cfg, log=lambda *_: None)
    n = regime.update(cfg)
    n_hmm = regime_hmm.update(cfg)
    if rep.errors:
        raise RuntimeError(f"{rep.summary()}; első hiba: {rep.errors[0]}")
    return f"{rep.summary()}; rezsimcímkék: {n} sor, HMM-variáns: {n_hmm} sor"


def step_report(cfg) -> str:
    """Napi riport (`reports/YYYY-MM-DD.md` + `.json`) és dashboard (`reports/index.html`)."""
    from evolab.report import daily, dashboard

    r = daily.build(cfg)
    md, _ = daily.write(cfg, r)
    dashboard.write(cfg, r)
    return f"{md.name} + index.html\n{daily.telegram_text(r)}"


def step_judge(cfg) -> str:
    """L2 paper-ítélet minden L2-es stratégiára + automatikus létra-lépések."""
    from evolab.evolve import ladder
    from evolab.judge.paper import evaluate_population

    verdicts = evaluate_population(cfg)
    res = ladder.apply(cfg, paper_verdicts=verdicts)
    v = ", ".join(f"{x['strategy_id']}={x['result']}" for x in verdicts) or "nincs L2-es"
    ch = ", ".join(f"{s} {a}→{b}" for s, a, b in res["changes"]) or "nincs szintváltás"
    return f"paper-ítélet: {v}; {ch}"


def step_researcher(cfg) -> str:
    from evolab.evolve import researcher

    ok, rejected = researcher.run(cfg)
    ids = ", ".join(f"{h.id} ({h.family}/{h.mutation_type})" for h in ok) or "-"
    return f"{len(ok)} hipotézis: {ids}; elutasítva: {len(rejected)}"


def step_developer(cfg) -> str:
    from evolab.evolve import developer

    return developer.summary(developer.run(cfg, log=lambda *_: None))


def waiting_text(cfg) -> str:
    """A jóváhagyásra váró egyedek a spec 6.4 szerinti adatokkal."""
    import json as _json

    from evolab.evolve import ladder
    from evolab.evolve.population import latest_verdicts
    from evolab.strategy import registry

    w = ladder.waiting(cfg)
    if w.empty:
        return "Jóváhagyásra vár: nincs"
    v = latest_verdicts(cfg).set_index("strategy_id")
    lines = ["Jóváhagyásra vár (válasz: /approve <id> vagy /reject <id> <ok>):"]
    for r in w.itertuples():
        row = v.loc[r.strategy_id] if r.strategy_id in v.index else None
        m = _json.loads(row["is_metrics_json"]) if row is not None else {}
        wf = _json.loads(row["wf_metrics_json"] or "{}") if row is not None else {}
        try:
            hyp = registry.load(r.strategy_id).meta.header.get("hypothesis", "")
        except Exception:
            hyp = ""
        first = hyp.strip().split(". ")[0][:160]
        lines.append(f"- {r.strategy_id} ({r.family}): DSR {row['dsr']:.3f}, PBO {row['pbo']:.2f}, "
                     f"PF 2x {m.get('pf_2x', 0):.2f}, OOS/IS {wf.get('oos_is_ratio', 0):.2f}. {first}"
                     if row is not None else f"- {r.strategy_id} ({r.family})")
    return "\n".join(lines)


def step_ladder(cfg) -> str:
    from evolab.evolve import ladder

    res = ladder.apply(cfg)
    ch = ", ".join(f"{s} {a}→{b}" for s, a, b in res["changes"]) or "nincs szintváltás"
    return f"{ch}\n{waiting_text(cfg)}"


STEP_FUNCS = {"data": step_data, "judge": step_judge, "report": step_report, "researcher": step_researcher,
              "developer": step_developer, "ladder": step_ladder}


def cmd_init_db(args: argparse.Namespace) -> int:
    cfg = load_config()
    path = init_db(cfg)
    with connect(path) as conn:
        tables = list_tables(conn)
    print(f"DB kész: {path}")
    print("Táblák: " + ", ".join(tables))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    print(f"evolab {__version__} | Python {platform.python_version()} | {platform.platform()}")
    print(f"Repó gyökér: {cfg.root}")
    print(f"Bíró verzió: {cfg.judge_version}")
    print(f"Univerzum: {', '.join(cfg.lab['universe'])}")
    print(f"STOP kapcsoló: {'BEKAPCSOLVA' if cfg.stop_file.exists() else 'nincs'}")
    if cfg.db_path.exists():
        with connect(cfg.db_path) as conn:
            n_trials = conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
            n_strat = conn.execute("SELECT COUNT(*) FROM strategies").fetchone()[0]
            last = conn.execute(
                "SELECT kind, status, started_at FROM runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
        print(f"DB: {cfg.db_path} | stratégiák: {n_strat} | kísérletek: {n_trials}")
        print(f"Utolsó futás: {dict(last) if last else 'még nem volt'}")
    else:
        print("DB: még nincs létrehozva (evolab init-db)")
    return 0


def cmd_telegram_ping(args: argparse.Namespace) -> int:
    load_config()
    text = args.text or (
        f"EvolutionTrader ping ✅\nevolab {__version__} | {platform.node()}\n"
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    msg_id = telegram.send(text)
    print(f"Telegram üzenet elküldve (id={msg_id}).")
    return 0


def cmd_telegram_chatid(args: argparse.Namespace) -> int:
    load_config()
    chats = telegram.recent_chats()
    if not chats:
        print("Nincs üzenet a botnál. Nyisd meg a botot a Telegramban, írj neki bármit, és futtasd újra.")
        return 1
    for chat_id, name in chats:
        print(f"TELEGRAM_CHAT_ID={chat_id}   ({name})")
    print("Másold a fenti sort a .env fájlba.")
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    """Napi futás. 0. fázis: csak szívverés (DB-napló + Telegram), a lépések csonkok."""
    cfg = load_config()
    init_db(cfg)
    steps = [args.step] if args.step else DAILY_STEPS
    with connect(cfg.db_path) as conn:
        cur = conn.execute(
            "INSERT INTO runs(kind, step, status) VALUES ('daily', ?, 'running')",
            (",".join(steps),),
        )
        run_id = cur.lastrowid
    lines = []
    if cfg.stop_file.exists():
        lines.append("STOP kapcsoló aktív: paper és fejlesztő lépés kihagyva.")
    status = "ok"
    for step in steps:
        func = STEP_FUNCS.get(step)
        if func is None:
            lines.append(f"- {step}: még nincs megvalósítva")
            continue
        try:
            lines.append(f"- {step}: {func(cfg)}")
        except Exception as e:  # egy lépés hibája ne állítsa le a többit; a Telegram jelzi
            status = "error"
            lines.append(f"- {step}: HIBA: {e}")
    message = "\n".join(lines)
    try:
        telegram.send(f"EvolutionTrader napi futás #{run_id}\n{message}")
    except telegram.TelegramNotConfigured as e:
        message += f"\nTelegram kihagyva: {e}"
    except Exception as e:  # a futás ne álljon le egy értesítési hiba miatt
        status = "warn" if status == "ok" else status
        message += f"\nTelegram hiba: {e}"
    with connect(cfg.db_path) as conn:
        conn.execute(
            "UPDATE runs SET status=?, message=?, finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE run_id=?",
            (status, message, run_id),
        )
    print(f"Napi futás #{run_id} ({status})\n{message}")
    return 0 if status != "error" else 1


def cmd_data_update(args: argparse.Namespace) -> int:
    from evolab.data import binance_bulk

    cfg = load_config()
    rep = binance_bulk.update(cfg, symbol_list=args.symbols or None, force_rebuild=args.rebuild)
    print(rep.summary())
    for e in rep.errors[:20]:
        print(f"  HIBA {e}")
    return 1 if rep.errors else 0


def cmd_data_check(args: argparse.Namespace) -> int:
    from evolab.data.check import run_all

    res = run_all(load_config(), recorder=not args.no_recorder)
    print("\n".join(res.lines))
    if res.failures:
        print(f"== {len(res.failures)} HIBA ==")
        return 1
    print("== adat: minden ellenőrzés OK ==")
    return 0


def cmd_data_gaps(args: argparse.Namespace) -> int:
    from evolab.data import gaps

    cfg = load_config()
    df = gaps.gap_report(cfg)
    path = gaps.write_report(cfg, df)
    print(gaps.summarize(df).to_string(index=False) if not df.empty else "Nincs hiányzó gyertya.")
    print(f"Részletes riport: {path}")
    return 1 if (not df.empty and (df["kind"] != "outage").any()) else 0


def cmd_regime(args: argparse.Namespace) -> int:
    from evolab.features import regime

    cfg = load_config()
    if args.compare:
        from evolab.features import regime_hmm

        c = regime_hmm.compare(cfg)
        if c.empty:
            print("Nincs összevethető ítélet (evolab population seed, evolab regime + HMM).")
            return 1
        g = cfg.judge["L1_backtest"]["regimes_positive_min"]
        print("Rezsimcímkéző-variánsok (a legutolsó L1-ítéletek kötései újracímkézve):")
        print(f"  {'':<34}{'szabályalapú':>14}{'HMM':>8}")
        print(f"  {'átlagos pozitív kombináció':<34}{c['pos_rule'].mean():>14.2f}{c['pos_hmm'].mean():>8.2f}")
        print(f"  {'rezsim-kapun átmenő variáns':<34}{int((c['pos_rule'] >= g).sum()):>14}{int((c['pos_hmm'] >= g).sum()):>8}")
        print(f"  {'EV-szórás (elkülönítő erő)':<34}{c['ev_spread_rule'].mean():>14.2f}{c['ev_spread_hmm'].mean():>8.2f}")
        return 0
    df = regime.compute(cfg)
    n = regime.write(cfg, df)
    print(f"regime_daily: {n} sor ({df['symbol'].nunique() if n else 0} coin)")
    if n:
        last = df.sort_values("date").groupby("symbol").tail(1)
        print(last.to_string(index=False))
    return 0 if n else 1


def cmd_backtest(args: argparse.Namespace) -> int:
    from evolab import backtest
    from evolab.strategy import registry

    cfg = load_config()
    if args.list or not args.strategy:
        for sid, path in registry.discover().items():
            print(f"{sid}  ({path.relative_to(registry.FAMILIES_DIR)})")
        return 0
    bt = backtest.run(cfg, args.strategy, cost_mult=args.cost_mult)
    s = bt.result.summary()
    print(f"Visszateszt: {bt.strategy_id} | trial {bt.trial_id} | holdout-ablak {bt.holdout_start:%Y-%m-%d}-tól kizárva")
    for k, v in s.items():
        print(f"  {k:<17}: {v}")
    print(f"  {'trades_hash':<17}: {bt.result.trades_hash()[:16]}")
    print(f"Kimenet: {bt.out_dir}")
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    from evolab.judge import holdout
    from evolab.judge.evaluate import evaluate_l1

    cfg = load_config()
    if args.holdout:
        try:
            out = holdout.run_holdout(cfg, args.strategy)
        except holdout.HoldoutRefused as e:
            print(f"Holdout elutasítva: {e}")
            return 1
        print(f"Holdout {args.strategy}: {'ÁTMENT' if out['passed'] else 'BUKOTT'} | {out['window_start']} – "
              f"{out['window_end']} | kötés {out['trades']}, PF {out['profit_factor']:.2f}")
        return 0 if out["passed"] else 1
    ev = evaluate_l1(cfg, args.strategy)
    m, wf, d, p = ev["metrics"], ev["walkforward"], ev["dsr"], ev["pbo"]
    print(f"L1 ítélet: {args.strategy} -> {ev['gate_result'].upper()} | trial {ev['trial_id']} | {ev['elapsed_s']} mp")
    print(f"  adat: holdout-ablak {ev['holdout_start']}-tól kizárva, {m['years']:.1f} év")
    print(f"  kötés {m['trades']}, PF 1x/2x/3x {ev['pf_1x']:.2f}/{ev['pf_2x']:.2f}/{ev['pf_3x']:.2f}, "
          f"max DD {100 * m['max_dd']:.1f}%, Sharpe {m['sharpe']:.2f}, Sortino {m['sortino']:.2f}, "
          f"Calmar {m['calmar']:.2f}")
    print(f"  walk-forward: {wf['windows']} ablak, OOS/IS {wf['oos_is_ratio']:.2f}")
    print(f"  DSR {d['dsr']:.3f} (SR {d['sr']:.4f} vs SR0 {d['sr0']:.4f}, kísérlet {d['n_trials']}, "
          f"hatékony {d['n_eff']:.1f})")
    print(f"  PBO {'n/a' if p['pbo'] is None else format(p['pbo'], '.2f')} ({p['variants']} variáns)")
    pos = sorted(k for k, v in m["regime_ev"].items() if v["ev"] > 0)
    print(f"  pozitív rezsimek ({len(pos)}): {', '.join(pos) or '-'}")
    print(f"  paraméter-stabilitás: {ev['param_stability']['results']}")
    for f in ev["gate_failures"]:
        print(f"  BUKOTT KAPU: {f}")
    return 0


def cmd_population(args: argparse.Namespace) -> int:
    from evolab.evolve import population

    cfg = load_config()
    if args.action == "seed":
        population.seed(cfg, log=lambda m: print(m, flush=True))
    table, fam = population.report(cfg)
    if table.empty:
        print("Nincs még L1-ítélet a ledgerben (evolab population seed).")
        return 1
    path = population.write_report(cfg, table, fam)
    print("L1 családonként:")
    print(fam.to_string(index=False))
    print(f"Összesen: {int(fam['passed'].sum())}/{int(fam['variants'].sum())} variáns ment át L1-en.")
    cols = ["strategy_id", "result", "judge_version", "trades", "pf_2x", "max_dd_pct", "oos_is", "dsr", "pbo",
            "regimes_pos", "regimes_pos_any"]
    print(table[cols].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print(f"Riport: {path}")
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    from evolab.live import paper_runner as pr

    cfg = load_config()
    if args.action == "run":
        out = pr.run(cfg, sync=not args.no_sync, log=lambda m: print(m, flush=True))
        return 1 if any("error" in v for v in out.values()) else 0
    if args.action == "roster":
        roster = pr.ensure_roster(cfg, reselect_shadow=args.reselect)
        for sid, info in sorted(roster["strategies"].items()):
            start = pd_ts(info["start_ms"])
            print(f"  {sid:<34} {info['mode']:<6} kezdet {start}")
        return 0
    # status: paper-állapot + egyezés a visszateszttel + mért slippage
    roster = pr.read_roster(cfg)
    if not roster["strategies"]:
        print("A paper-névsor üres (evolab paper run).")
        return 1
    cache: dict = {}
    print("Paper (Hyperliquid) vs. visszateszt (Binance), ugyanarra az időszakra:")
    for sid, info in sorted(roster["strategies"].items()):
        s = pr.read_summary(cfg, sid) or {}
        c = pr.compare(cfg, sid, cache)
        diff = "-" if c["diff_pct"] is None else f"{c['diff_pct']:.2f}%"
        verdict = "-" if c["ok"] is None else ("OK" if c["ok"] else "ELTÉR")
        print(f"  {sid:<34} {info['mode']:<6} {c['days']:>5.1f} nap, kötés {s.get('trades', 0):>3}, "
              f"hozam {s.get('return_pct', 0.0):+6.2f}%, eltérés {diff:>7} {verdict}"
              f"{' (végleges)' if c.get('final_check') else ''}")
    print("Slippage: mért (Hyperliquid impact, 7 nap medián) vs. modell (4h):")
    for r in pr.measured_slippage(cfg).itertuples():
        m = "-" if r.measured_pct is None or r.measured_pct != r.measured_pct else f"{r.measured_pct:.4f}%"
        print(f"  {r.symbol:<9} mért {m:>9}  modell {r.model_pct:.4f}%  ({r.samples} minta)")
    return 0


def pd_ts(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def cmd_report(args: argparse.Namespace) -> int:
    cfg = load_config()
    print(step_report(cfg))
    print(f"Dashboard: {cfg.path('reports') / 'index.html'}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    from evolab.evolve import ladder

    cfg = load_config()
    try:
        if args.action == "approve":
            print(ladder.approve(cfg, args.strategy))
        else:
            print(ladder.reject(cfg, args.strategy, " ".join(args.reason)))
    except ladder.LadderError as e:
        print(f"Hiba: {e}")
        return 1
    return 0


def cmd_telegram_poll(args: argparse.Namespace) -> int:
    from evolab.notify import commands

    cfg = load_config()
    try:
        done = commands.poll(cfg)
    except telegram.TelegramNotConfigured as e:
        print(f"Telegram kihagyva: {e}")
        return 0
    for cmd, reply in done:
        print(f"{cmd} -> {reply}")
    return 0


def cmd_watchdog(args: argparse.Namespace) -> int:
    from evolab.notify import watchdog

    cfg = load_config()
    if args.dry_run:
        probs = watchdog.problems(cfg)
        print("\n".join(f"HIBA {k}: {v}" for k, v in probs.items()) or "Minden rendben.")
        return 1 if probs else 0
    try:
        sent = watchdog.run(cfg)
    except telegram.TelegramNotConfigured as e:
        print(f"Telegram kihagyva: {e}")
        return 0
    print("\n".join(sent) or "Nincs új riasztás.")
    return 0


def cmd_dashboard_serve(args: argparse.Namespace) -> int:
    from evolab.report.serve import serve

    cfg = load_config()
    page = cfg.path("reports") / "index.html"
    print(f"Dashboard: http://127.0.0.1:{args.port}/ ({page})", flush=True)
    serve(page, "127.0.0.1", args.port)
    return 0


def cmd_recorder(args: argparse.Namespace) -> int:
    from evolab.live import recorder

    cfg = load_config()
    if args.once:
        hl = recorder.HLInfo(cfg.lab["sources"]["hyperliquid_info"], min_interval=3.0)
        n = recorder.record_ticks(cfg, hl)
        m = recorder.compact(cfg)
        recorder.sync_candles(cfg, hl)
        print(f"Rögzítve: {n} coin pillanatképe, {m} puffer-sor tömörítve, gyertyák/funding szinkronizálva.")
        return 0
    recorder.run(cfg, log=lambda m: print(m, flush=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="evolab", description="EvolutionTrader labor")
    p.add_argument("--version", action="version", version=f"evolab {__version__}")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("init-db", help="adatbázis létrehozása/frissítése").set_defaults(func=cmd_init_db)
    sub.add_parser("status", help="állapot összefoglaló").set_defaults(func=cmd_status)

    sp = sub.add_parser("telegram-ping", help="tesztüzenet küldése Telegramra")
    sp.add_argument("--text", default=None)
    sp.set_defaults(func=cmd_telegram_ping)

    sub.add_parser("telegram-chatid", help="chat-azonosító kiderítése").set_defaults(
        func=cmd_telegram_chatid
    )

    dp = sub.add_parser("data", help="történelmi adat (Binance) kezelése").add_subparsers(dest="data_cmd")
    sp = dp.add_parser("update", help="Binance letöltés/frissítés (csak a hiányzót tölti le)")
    sp.add_argument("symbols", nargs="*", help="csak ezek a coinok (alapból mind)")
    sp.add_argument("--rebuild", action="store_true", help="parquet újraépítése akkor is, ha nincs új zip")
    sp.set_defaults(func=cmd_data_update)
    sp = dp.add_parser("check", help="adatminőség-ellenőrzés (make verify-1)")
    sp.add_argument("--no-recorder", action="store_true", help="a rögzítő 24 órás ellenőrzése nélkül")
    sp.set_defaults(func=cmd_data_check)
    sp = dp.add_parser("gaps", help="hiányzó gyertyák riportja -> reports/data_gaps.csv")
    sp.set_defaults(func=cmd_data_gaps)

    sp = sub.add_parser("regime", help="rezsimcímkék számolása -> regime_daily (--compare: HMM-variánssal összevetve)")
    sp.add_argument("--compare", action="store_true", help="szabályalapú vs. HMM címkéző összevetése")
    sp.set_defaults(func=cmd_regime)

    sp = sub.add_parser("recorder", help="Hyperliquid élő rögzítő (launchd tartja életben)")
    sp.add_argument("--once", action="store_true", help="egyetlen pillanatkép + gyertya-szinkron")
    sp.set_defaults(func=cmd_recorder)

    sp = sub.add_parser("backtest", help="visszateszt egy stratégiára (a holdout-ablak mindig kizárva)")
    sp.add_argument("--strategy", help="stratégia-azonosító, pl. trend-ema-cross-4h-01")
    sp.add_argument("--no-holdout", action="store_true",
                    help="a holdout-ablak kizárása (ez az alapértelmezés; a holdout a bíró kapujánál fut)")
    sp.add_argument("--cost-mult", type=float, default=1.0, help="díj- és slippage-szorzó (1, 2, 3)")
    sp.add_argument("--list", action="store_true", help="regisztrált stratégiák listája")
    sp.set_defaults(func=cmd_backtest)

    sp = sub.add_parser("judge", help="L1 bírói ítélet egy stratégiára (vagy --holdout: egyszeri holdout-futás)")
    sp.add_argument("--strategy", required=True)
    sp.add_argument("--holdout", action="store_true", help="a holdout-ablak egyszeri futtatása (burn-szabállyal)")
    sp.set_defaults(func=cmd_judge)

    sp = sub.add_parser("population", help="induló populáció: L1-ítélet minden variánsra (seed) vagy riport")
    sp.add_argument("action", choices=["seed", "report"])
    sp.set_defaults(func=cmd_population)

    sp = sub.add_parser("paper", help="élő paper Hyperliquid-adaton: run (launchd óránként), status, roster")
    sp.add_argument("action", choices=["run", "status", "roster"])
    sp.add_argument("--no-sync", action="store_true", help="run: a Hyperliquid-gyertyák szinkronja nélkül")
    sp.add_argument("--reselect", action="store_true", help="roster: új árnyék-lista választása")
    sp.set_defaults(func=cmd_paper)

    sub.add_parser("report", help="napi riport + dashboard (reports/)").set_defaults(func=cmd_report)

    sp = sub.add_parser("approve", help="jóváhagyás: egy szinttel feljebb (L1 -> L2 paper)")
    sp.add_argument("strategy")
    sp.set_defaults(func=cmd_approve, action="approve", reason=[])
    sp = sub.add_parser("reject", help="várólistás (L1) stratégia elutasítása")
    sp.add_argument("strategy")
    sp.add_argument("reason", nargs="*")
    sp.set_defaults(func=cmd_approve, action="reject")
    sub.add_parser("telegram-poll", help="Telegram-parancsok feldolgozása (/approve, /reject, /waiting)").set_defaults(
        func=cmd_telegram_poll)

    sp = sub.add_parser("watchdog", help="folyamat-őr: rögzítő, paper, napi futás, lemez (óránként, Telegram)")
    sp.add_argument("--dry-run", action="store_true", help="csak kiírja a hibákat, nem küld üzenetet")
    sp.set_defaults(func=cmd_watchdog)

    sp = sub.add_parser("dashboard-serve", help="a dashboard helyi kiszolgálása (csak 127.0.0.1, a tunnel mögé)")
    sp.add_argument("--port", type=int, default=8790)
    sp.set_defaults(func=cmd_dashboard_serve)

    sp = sub.add_parser("daily", help="napi futás (launchd hívja 02:00-kor)")
    sp.add_argument("--step", choices=DAILY_STEPS, default=None, help="csak egy lépés futtatása")
    sp.set_defaults(func=cmd_daily)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):  # pl. `evolab data` alparancs nélkül
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except telegram.TelegramNotConfigured as e:
        print(f"Hiba: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
