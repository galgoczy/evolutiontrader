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

# A napi futás lépései (docs/02-specifikacio.md 6.1). Az 1. fázistól a `data` valódi, a többi csonk.
DAILY_STEPS = ["data", "judge", "report", "researcher", "developer", "ladder"]


def step_data(cfg) -> str:
    """Binance pótlás + rezsimcímkék frissítése. (A Hyperliquid rögzítő külön folyamat.)"""
    from evolab.data import binance_bulk
    from evolab.features import regime

    rep = binance_bulk.update(cfg, log=lambda *_: None)
    n = regime.update(cfg)
    if rep.errors:
        raise RuntimeError(f"{rep.summary()}; első hiba: {rep.errors[0]}")
    return f"{rep.summary()}; rezsimcímkék: {n} sor"


STEP_FUNCS = {"data": step_data}


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
    df = regime.compute(cfg)
    n = regime.write(cfg, df)
    print(f"regime_daily: {n} sor ({df['symbol'].nunique() if n else 0} coin)")
    if n:
        last = df.sort_values("date").groupby("symbol").tail(1)
        print(last.to_string(index=False))
    return 0 if n else 1


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

    sub.add_parser("regime", help="rezsimcímkék számolása -> regime_daily").set_defaults(func=cmd_regime)

    sp = sub.add_parser("recorder", help="Hyperliquid élő rögzítő (launchd tartja életben)")
    sp.add_argument("--once", action="store_true", help="egyetlen pillanatkép + gyertya-szinkron")
    sp.set_defaults(func=cmd_recorder)

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
