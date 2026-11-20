#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-Year Real Binance 4H Pure Quantitative Trend Backtester (quant_4h_backtest.py)
================================================================================
Run directly on DigitalOcean Singapore Droplet inside ~/btc_bot/:
  ~/btc_bot/venv/bin/python ~/btc_bot/quant_4h_backtest.py --days 1095

Tests 3 classic low-frequency quantitative trend-following strategies (each in
Long-Only and Long+Short modes) on 100% REAL Binance 4H BTC/USDT & ETH/USDT data:
  1. Donchian Breakout (Turtle 20/10 + 2.5x ATR trailing stop + EMA200 regime)
  2. Dual EMA Trend    (EMA20/EMA60 crossover + 3.0x ATR trailing stop)
  3. Volatility Break  (EMA20 + 2.0x ATR Keltner breakout + 2.5x ATR trailing stop)

Execution rules (strict, zero lookahead):
  - Signals evaluated ONLY on closed 4H candles; entries fill at next bar open.
  - Intra-bar High/Low trailing stop checked conservatively on every 4H bar.
  - Bilateral fee + slippage deducted on every trade: BTC 0.12% RT, ETH 0.14% RT.
  - Reports 3-Year Total AND Year-by-Year / First-2Y vs Last-1Y consistency!
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

EXCHANGE_SOURCES = [
    ("binance", {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 1000),
    ("bybit",   {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 1000),
    ("gate",    {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 1000),
    ("okx",     {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 300),
]


def fetch_real_4h_ohlcv(asset: str, days: int, refresh: bool = False) -> Tuple[str, List[List[float]]]:
    cache_path = os.path.join(SCRIPT_DIR, f"cache_quant_{asset}_{days}d_4h.json")
    if (not refresh) and os.path.exists(cache_path):
        age_h = (time.time() - os.path.getmtime(cache_path)) / 3600.0
        if age_h < 24.0:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if len(cached.get("bars", [])) >= 300:
                return cached["source"] + " (cached)", cached["bars"]

    import ccxt

    now_ms = int(time.time() * 1000)
    since_ms = now_ms - days * 86400 * 1000
    step_ms = 4 * 3600 * 1000
    target_bars = days * 6

    for ex_id, sym_map, limit in EXCHANGE_SOURCES:
        sym = sym_map[asset]
        try:
            ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
            all_bars: List[List[float]] = []
            cursor = since_ms
            stalls = 0
            print(f"[FETCH] Downloading {days}d real 4h {sym} from {ex_id}...", flush=True)
            while cursor < now_ms - step_ms and len(all_bars) < target_bars + 200:
                batch = ex.fetch_ohlcv(sym, timeframe="4h", since=cursor, limit=limit)
                if not batch:
                    break
                last_ts = int(batch[-1][0])
                if all_bars and last_ts <= int(all_bars[-1][0]):
                    stalls += 1
                    if stalls >= 2:
                        break
                    cursor += limit * step_ms
                    continue
                all_bars.extend(batch)
                cursor = last_ts + step_ms
                if len(batch) < max(30, limit // 4):
                    break

            dedup = {int(b[0]): b for b in all_bars}
            bars = [dedup[k] for k in sorted(dedup.keys())]
            if len(bars) >= max(300, int(target_bars * 0.6)):
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"source": ex_id, "bars": bars}, f)
                return ex_id, bars
            print(f"[WARN] {ex_id} returned only {len(bars)} 4h bars for {sym}; trying next...", flush=True)
        except Exception as e:
            print(f"[WARN] {ex_id} fetch failed for {sym}: {e}", flush=True)

    raise RuntimeError(f"Failed to fetch 4h OHLCV for {asset}")


def generate_selftest_4h(asset: str, days: int = 365) -> Tuple[str, List[List[float]]]:
    n = days * 6
    start_dt = datetime.datetime(2025, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
    p = 60000.0 if asset == "BTC" else 2500.0
    rng = 77 if asset == "BTC" else 133
    bars = []
    for i in range(n):
        ts = int((start_dt + datetime.timedelta(hours=4 * i)).timestamp() * 1000)
        rng = (rng * 1664525 + 1013904223) % 4294967296
        u = (rng / 4294967296.0) - 0.5
        regime = 0.0018 if (i // 180) % 2 == 0 else -0.0012
        o = p
        c = max(10.0, o * (1.0 + regime + u * 0.028))
        h = max(o, c) * (1.0 + abs(u) * 0.012)
        l = min(o, c) * (1.0 - abs(u) * 0.012)
        bars.append([ts, o, h, l, c, 1000.0])
        p = c
    return "self-test-synthetic", bars


def calc_ema(vals: List[float], period: int) -> List[float]:
    out = [0.0] * len(vals)
    k = 2.0 / (period + 1.0)
    out[0] = vals[0]
    for i in range(1, len(vals)):
        out[i] = vals[i] * k + out[i - 1] * (1.0 - k)
    return out


def calc_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    n = len(closes)
    tr = [0.0] * n
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    atr = [0.0] * n
    atr[0] = tr[0]
    alpha = 1.0 / period
    for i in range(1, n):
        atr[i] = alpha * tr[i] + (1.0 - alpha) * atr[i - 1]
    return atr


def run_strategy(
    bars: List[List[float]],
    strat_type: str,
    allow_short: bool,
    fee_rt: float,
    risk_alloc: float = 0.95,
) -> Dict[str, Any]:
    """
    Zero-lookahead 4H simulation:
      - Indicators computed up to bar i-1 (closed bar).
      - Entries/exits execute at bar i open, or intra-bar trailing stop on bar i High/Low.
    """
    n = len(bars)
    opens = [float(b[1]) for b in bars]
    highs = [float(b[2]) for b in bars]
    lows = [float(b[3]) for b in bars]
    closes = [float(b[4]) for b in bars]

    ema20 = calc_ema(closes, 20)
    ema60 = calc_ema(closes, 60)
    ema100 = calc_ema(closes, 100)
    ema200 = calc_ema(closes, 200)
    atr14 = calc_atr(highs, lows, closes, 14)

    start_i = 205
    split_i = start_i + int((n - start_i) * 0.67)  # First ~2Y vs Last ~1Y

    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    eq_curve = [1.0] * n
    pos = None  # dict: side, entry, stop, open_i
    trades = []

    for i in range(start_i, n):
        # Closed bar index = i - 1
        p_idx = i - 1
        o_p, h_p, l_p, c_p = opens[i], highs[i], lows[i], closes[i]
        prev_c = closes[p_idx]
        prev_atr = atr14[p_idx]

        # Precompute Donchian channels strictly from [p_idx-20 : p_idx] (excluding p_idx itself)
        hh20 = max(highs[p_idx - 20 : p_idx])
        ll20 = min(lows[p_idx - 20 : p_idx])
        hh10 = max(highs[p_idx - 10 : p_idx])
        ll10 = min(lows[p_idx - 10 : p_idx])

        # Determine closed-bar signals
        long_entry = False
        short_entry = False
        long_exit_sig = False
        short_exit_sig = False
        trail_mult = 2.5

        if strat_type == "donchian":
            long_entry = (prev_c > hh20) and (prev_c > ema200[p_idx])
            short_entry = allow_short and (prev_c < ll20) and (prev_c < ema200[p_idx])
            long_exit_sig = (prev_c < ll10)
            short_exit_sig = (prev_c > hh10)
            trail_mult = 2.5
        elif strat_type == "ema":
            ema60_up = ema60[p_idx] > ema60[p_idx - 6]
            ema60_dn = ema60[p_idx] < ema60[p_idx - 6]
            long_entry = (ema20[p_idx] > ema60[p_idx]) and ema60_up and (prev_c > ema200[p_idx])
            short_entry = allow_short and (ema20[p_idx] < ema60[p_idx]) and ema60_dn and (prev_c < ema200[p_idx])
            long_exit_sig = (ema20[p_idx] < ema60[p_idx])
            short_exit_sig = (ema20[p_idx] > ema60[p_idx])
            trail_mult = 3.0
        elif strat_type == "vol_break":
            upper_k = ema20[p_idx] + 2.0 * prev_atr
            lower_k = ema20[p_idx] - 2.0 * prev_atr
            long_entry = (prev_c > upper_k) and (ema20[p_idx] > ema100[p_idx])
            short_entry = allow_short and (prev_c < lower_k) and (ema20[p_idx] < ema100[p_idx])
            long_exit_sig = (prev_c < ema20[p_idx])
            short_exit_sig = (prev_c > ema20[p_idx])
            trail_mult = 2.5

        # 1. Manage open position
        if pos is not None:
            side = pos["side"]
            ep = pos["entry"]
            exit_p = None

            # Check signal exit at open first
            if (side == "LONG" and long_exit_sig) or (side == "SHORT" and short_exit_sig):
                exit_p = o_p
            else:
                # Update trailing stop from previous closed bar, then check intra-bar stop hit
                if side == "LONG":
                    pos["stop"] = max(pos["stop"], prev_c - trail_mult * prev_atr)
                    if l_p <= pos["stop"]:
                        exit_p = min(o_p, pos["stop"])
                else:
                    pos["stop"] = min(pos["stop"], prev_c + trail_mult * prev_atr)
                    if h_p >= pos["stop"]:
                        exit_p = max(o_p, pos["stop"])

            if exit_p is not None:
                raw_r = (exit_p - ep) / ep if side == "LONG" else (ep - exit_p) / ep
                net_r = (raw_r - fee_rt) * risk_alloc
                eq = max(0.01, eq * (1.0 + net_r))
                trades.append({"side": side, "net_r": net_r, "win": net_r > 0, "idx": i})
                pos = None

        # 2. Check new entry at bar i open
        if pos is None:
            if long_entry:
                pos = {"side": "LONG", "entry": o_p, "stop": o_p - trail_mult * prev_atr, "open_i": i}
            elif short_entry:
                pos = {"side": "SHORT", "entry": o_p, "stop": o_p + trail_mult * prev_atr, "open_i": i}

        # Mark-to-market equity
        mtm = eq
        if pos is not None:
            raw_u = (c_p - pos["entry"]) / pos["entry"] if pos["side"] == "LONG" else (pos["entry"] - c_p) / pos["entry"]
            mtm = max(0.01, eq * (1.0 + raw_u * risk_alloc))
        eq_curve[i] = mtm
        if mtm > peak:
            peak = mtm
        dd = (peak - mtm) / peak
        if dd > max_dd:
            max_dd = dd

    # Close any open position at last bar close for clean accounting
    if pos is not None:
        raw_r = (closes[-1] - pos["entry"]) / pos["entry"] if pos["side"] == "LONG" else (pos["entry"] - closes[-1]) / pos["entry"]
        net_r = (raw_r - fee_rt) * risk_alloc
        eq = max(0.01, eq * (1.0 + net_r))
        trades.append({"side": pos["side"], "net_r": net_r, "win": net_r > 0, "idx": n - 1})
        eq_curve[-1] = eq

    n_tr = len(trades)
    wins = sum(1 for t in trades if t["win"])
    gp = sum(t["net_r"] for t in trades if t["net_r"] > 0)
    gl = abs(sum(t["net_r"] for t in trades if t["net_r"] < 0))
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)

    total_ret = (eq_curve[-1] / eq_curve[start_i] - 1.0) * 100.0
    first_2y_ret = (eq_curve[split_i] / eq_curve[start_i] - 1.0) * 100.0
    last_1y_ret = (eq_curve[-1] / eq_curve[split_i] - 1.0) * 100.0

    years_span = max(0.2, (n - start_i) / (6.0 * 365.0))
    cagr = ((eq_curve[-1] / eq_curve[start_i]) ** (1.0 / years_span) - 1.0) * 100.0
    calmar = (cagr / (max_dd * 100.0)) if max_dd > 0 else 0.0

    return {
        "n_trades": n_tr,
        "wr": (wins / n_tr * 100.0) if n_tr else 0.0,
        "ret_pct": total_ret,
        "cagr_pct": cagr,
        "mdd_pct": max_dd * 100.0,
        "calmar": calmar,
        "pf": pf,
        "first_2y": first_2y_ret,
        "last_1y": last_1y_ret,
        "eq_curve": eq_curve,
        "start_i": start_i,
    }


def main():
    parser = argparse.ArgumentParser(description="3-Year Real Binance 4H Quantitative Trend Backtest")
    parser.add_argument("--days", type=int, default=1095, help="Days of real 4h candles (default: 1095 = 3 years)")
    parser.add_argument("--refresh", action="store_true", help="Ignore local cache and re-download")
    parser.add_argument("--self-test", action="store_true", help="Offline smoke test")
    args = parser.parse_args()

    strategies = [
        ("1a. Donchian (Long-Only)",  "donchian",  False),
        ("1b. Donchian (Long+Short)", "donchian",  True),
        ("2a. Dual-EMA (Long-Only)",  "ema",       False),
        ("2b. Dual-EMA (Long+Short)", "ema",       True),
        ("3a. VolBreak (Long-Only)",  "vol_break", False),
        ("3b. VolBreak (Long+Short)", "vol_break", True),
    ]

    datasets = {}
    for asset in ("BTC", "ETH"):
        if args.self_test:
            src, bars = generate_selftest_4h(asset, days=min(args.days, 365))
        else:
            src, bars = fetch_real_4h_ohlcv(asset, days=args.days, refresh=args.refresh)
        datasets[asset] = (src, bars)

    print("\n" + "=" * 116)
    print(f"  [PURE QUANTITATIVE 4H TREND BACKTEST | REAL BINANCE DATA | WINDOW: {args.days} DAYS]")
    print("  Zero Lookahead (Next-Bar Open Fill) | Conservative Intra-Bar ATR Trailing Stop | Fees: BTC 0.12% / ETH 0.14%")
    print("=" * 116)

    res_map: Dict[str, Dict[str, Dict[str, Any]]] = {s[0]: {} for s in strategies}

    for asset, fee in (("BTC", 0.0012), ("ETH", 0.0014)):
        src, bars = datasets[asset]
        st_i = 205
        t0 = datetime.datetime.fromtimestamp(bars[st_i][0] / 1000.0, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        t1 = datetime.datetime.fromtimestamp(bars[-1][0] / 1000.0, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        bh = (bars[-1][4] / bars[st_i][4] - 1.0) * 100.0
        # B&H MaxDD
        pk, bh_mdd = bars[st_i][4], 0.0
        for b in bars[st_i:]:
            if b[4] > pk: pk = b[4]
            bh_mdd = max(bh_mdd, (pk - b[4]) / pk * 100.0)

        print(f"\n>>> {asset}/USDT | Source: {src} | Eval Window: {t0} -> {t1} ({len(bars)-st_i} 4H bars)")
        print(f"    Buy & Hold Benchmark: {bh:+.2f}% | B&H MaxDD: {bh_mdd:.2f}%")
        print(f"{'Strategy':<27} | {'Trades':>6} | {'WR%':>6} | {'NetRet':>9} | {'CAGR':>7} | {'MaxDD':>6} | {'Calmar':>6} | {'PF':>5} | {'1st-2Y':>8} | {'Last-1Y':>8}")
        print("-" * 116)
        for s_name, s_type, allow_s in strategies:
            r = run_strategy(bars, s_type, allow_s, fee_rt=fee)
            res_map[s_name][asset] = r
            print(
                f"{s_name:<27} | {r['n_trades']:>6d} | {r['wr']:>5.1f}% | {r['ret_pct']:>+8.2f}% | "
                f"{r['cagr_pct']:>+6.1f}% | {r['mdd_pct']:>5.1f}% | {r['calmar']:>6.2f} | {r['pf']:>5.2f} | "
                f"{r['first_2y']:>+7.1f}% | {r['last_1y']:>+7.1f}%"
            )

    print("\n" + "-" * 116)
    print("  [Combined 60% BTC / 40% ETH Portfolio Summary (1x Unleveraged, Real 4H Data)]")
    print(f"  {'Strategy':<27} | {'TotTrades':>9} | {'60/40 NetRet':>12} | {'60/40 MaxDD':>11} | {'60/40 Calmar':>12} | {'Verdict'}")
    print("  " + "-" * 96)
    for s_name, _, _ in strategies:
        rb = res_map[s_name]["BTC"]
        re = res_map[s_name]["ETH"]
        st_i = rb["start_i"]
        L = min(len(rb["eq_curve"]), len(re["eq_curve"]))
        pk, pmdd = 1.0, 0.0
        for idx in range(st_i, L):
            pv = 0.60 * rb["eq_curve"][idx] + 0.40 * re["eq_curve"][idx]
            if pv > pk: pk = pv
            pmdd = max(pmdd, (pk - pv) / pk * 100.0)
        p_end = 0.60 * rb["eq_curve"][L - 1] + 0.40 * re["eq_curve"][L - 1]
        p_ret = (p_end - 1.0) * 100.0
        yrs = max(0.2, (L - st_i) / (6.0 * 365.0))
        p_cagr = (p_end ** (1.0 / yrs) - 1.0) * 100.0
        p_calmar = p_cagr / pmdd if pmdd > 0 else 0.0
        tot_tr = rb["n_trades"] + re["n_trades"]
        verdict = "STRONG EDGE" if (rb["pf"] >= 1.25 and re["pf"] >= 1.15 and p_ret > 20) else ("POSITIVE" if p_ret > 0 else "NEGATIVE")
        print(f"  {s_name:<27} | {tot_tr:>9d} | {p_ret:>+11.2f}% | {pmdd:>10.2f}% | {p_calmar:>12.2f} | {verdict}")
    print("=" * 116)


if __name__ == "__main__":
    main()