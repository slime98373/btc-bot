#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Historical 5m K-Line Backtester & MA120 Slope Guard A/B Tester (real_kline_backtest.py)
============================================================================================
Run directly on DigitalOcean Singapore Droplet inside ~/btc_bot/:
  ~/btc_bot/venv/bin/python ~/btc_bot/real_kline_backtest.py --days 90

What it does:
  1. Downloads 100% REAL 5m OHLCV candles for BTC/USDT and ETH/USDT via free public CCXT APIs
     (binance -> bybit -> okx -> gate automatic fallback) and caches locally to JSON.
  2. Runs realistic intra-bar High/Low TP/SL execution (conservative: if both hit in same 5m bar,
     assumes SL hit first) + bilateral fee/slippage (BTC 0.12%, ETH 0.14%).
  3. Compares 4 variants side-by-side on the exact same real market data:
       [A] v15.1 Baseline      : Current live logic
       [B] +SlopeGuard(-0.05)  : Blocks LONG when MA120 10H slope < -0.05% (anti falling-knife)
       [C] +Slope(-0.05)+BE0.2 : Adds SlopeGuard + raises Breakeven lock from +0.10% to +0.20%
       [D] StrictTrend(0.00)   : LONG requires slope >= 0.00%, SHORT requires slope <= 0.00%
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
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from daliuren_engine import cast_daily_tsmc_chart
from btc_strategy import (
    ASSET_PROFILES,
    calc_shichen_qimen,
    calc_true_qimen_9palace,
    calc_btc_fire_resonance,
    calc_pure_daliuren_2d,
    compute_dynamic_shichen_schedule,
    get_huangji_lichun_soft_profile,
)

EXCHANGE_SOURCES = [
    ("binance", {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 1000),
    ("bybit",   {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 1000),
    ("gate",    {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 1000),
    ("okx",     {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 300),
]

CHART_CACHE: Dict[Tuple[int, int, int, int], Dict[str, Any]] = {}


def get_chart_bundle(dt_tw: datetime.datetime) -> Dict[str, Any]:
    """Cache DaLiuRen + True QiMen + HuangJi calculations per 2-hour Shichen block."""
    # Taiwan Shichen blocks: 23:00-00:59 (Zi), 01:00-02:59 (Chou), ...
    shifted = dt_tw + datetime.timedelta(hours=1)
    key = (shifted.year, shifted.month, shifted.day, shifted.hour // 2)
    if key not in CHART_CACHE:
        c = cast_daily_tsmc_chart(dt_tw)
        q_base = calc_shichen_qimen(c)
        q_true = calc_true_qimen_9palace(dt_tw, c)
        hj = get_huangji_lichun_soft_profile(dt_tw)
        res_btc = calc_btc_fire_resonance(c, el="火", palace="午")["el_score"]
        res_eth = calc_btc_fire_resonance(c, el="木", palace="卯")["el_score"]
        sched_btc = compute_dynamic_shichen_schedule(c, q_base, res_btc)
        sched_eth = compute_dynamic_shichen_schedule(c, q_base, res_eth)
        spec_btc = [calc_pure_daliuren_2d(c, ph, el="火", palace="午", tomb="戌") for ph in range(3)]
        spec_eth = [calc_pure_daliuren_2d(c, ph, el="木", palace="卯", tomb="未") for ph in range(3)]
        CHART_CACHE[key] = {
            "chart": c, "q_base": q_base, "q_true": q_true, "hj": hj,
            "BTC": {"el": res_btc, "sched": sched_btc, "spec": spec_btc},
            "ETH": {"el": res_eth, "sched": sched_eth, "spec": spec_eth},
        }
    return CHART_CACHE[key]


def fetch_real_5m_ohlcv(asset: str, days: int, refresh: bool = False) -> Tuple[str, List[List[float]]]:
    cache_path = os.path.join(SCRIPT_DIR, f"cache_{asset}_{days}d_5m.json")
    if (not refresh) and os.path.exists(cache_path):
        age_h = (time.time() - os.path.getmtime(cache_path)) / 3600.0
        if age_h < 24.0:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if len(cached.get("bars", [])) >= 500:
                return cached["source"] + " (cached)", cached["bars"]

    import ccxt

    now_ms = int(time.time() * 1000)
    since_ms = now_ms - days * 86400 * 1000
    target_bars = days * 288

    for ex_id, sym_map, limit in EXCHANGE_SOURCES:
        sym = sym_map[asset]
        try:
            ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
            all_bars: List[List[float]] = []
            cursor = since_ms
            stalls = 0
            print(f"[FETCH] Downloading {days}d real 5m {sym} from {ex_id}...", flush=True)
            while cursor < now_ms - 300_000 and len(all_bars) < target_bars + 500:
                batch = ex.fetch_ohlcv(sym, timeframe="5m", since=cursor, limit=limit)
                if not batch:
                    break
                last_ts = int(batch[-1][0])
                if all_bars and last_ts <= int(all_bars[-1][0]):
                    stalls += 1
                    if stalls >= 2:
                        break
                    cursor += limit * 300_000
                    continue
                all_bars.extend(batch)
                cursor = last_ts + 300_000
                if len(batch) < max(50, limit // 4):
                    break

            # Deduplicate & sort by timestamp
            dedup = {int(b[0]): b for b in all_bars}
            bars = [dedup[k] for k in sorted(dedup.keys())]
            if len(bars) >= max(500, int(target_bars * 0.5)):
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"source": ex_id, "bars": bars}, f)
                return ex_id, bars
            print(f"[WARN] {ex_id} returned only {len(bars)} bars for {sym}; trying next source...", flush=True)
        except Exception as e:
            print(f"[WARN] {ex_id} fetch failed for {sym}: {e}", flush=True)

    raise RuntimeError(f"Could not fetch sufficient real 5m OHLCV data for {asset} from any exchange.")


def generate_selftest_ohlcv(asset: str, days: int = 14) -> Tuple[str, List[List[float]]]:
    """Offline synthetic smoke-test generator (ONLY used with --self-test)."""
    n = days * 288
    start_dt = datetime.datetime(2026, 11, 1, 0, 0, tzinfo=datetime.timezone.utc)
    p = 64000.0 if asset == "BTC" else 1850.0
    vol = 0.0020 if asset == "BTC" else 0.0026
    bars = []
    rng = 12345 if asset == "BTC" else 67890
    for i in range(n):
        ts = int((start_dt + datetime.timedelta(minutes=5 * i)).timestamp() * 1000)
        rng = (rng * 1664525 + 1013904223) % 4294967296
        u = (rng / 4294967296.0) - 0.5
        drift = -0.00005 if (i % 600) < 250 else 0.00004
        o = p
        c = max(10.0, o * (1.0 + drift + u * vol * 2.2))
        h = max(o, c) * (1.0 + abs(u) * vol * 0.9)
        l = min(o, c) * (1.0 - abs(u) * vol * 0.9)
        bars.append([ts, round(o, 2), round(h, 2), round(l, 2), round(c, 2), 100.0])
        p = c
    return "self-test-synthetic", bars


def run_variant_backtest(
    bars: List[List[float]],
    asset_code: str,
    fee_rt: float,
    long_min_slope: float = -999.0,
    short_max_slope: float = 0.25,
    be_lock_pct: float = 0.0010,
) -> Dict[str, Any]:
    prof = ASSET_PROFILES[asset_code]
    tp_pct, sl_pct = prof["tp"], prof["sl"]

    n = len(bars)
    closes = [float(b[4]) for b in bars]
    highs = [float(b[2]) for b in bars]
    lows = [float(b[3]) for b in bars]

    # Prefix sum for fast O(1) MA120
    ps = [0.0] * (n + 1)
    for i in range(n):
        ps[i + 1] = ps[i] + closes[i]

    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    pos = None
    trades = []
    tz_tw = datetime.timezone(datetime.timedelta(hours=8))

    for i in range(132, n):
        ts_ms = int(bars[i][0])
        dt_tw = datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=tz_tw).replace(tzinfo=None)

        curr_p = closes[i]
        hi_p = highs[i]
        lo_p = lows[i]

        ma_macro = (ps[i + 1] - ps[i + 1 - 120]) / 120.0
        ma_prev = (ps[i + 1 - 11] - ps[i + 1 - 131]) / 120.0
        slope = (ma_macro - ma_prev) / ma_prev * 100.0 if ma_prev > 0 else 0.0
        mom_15m = (curr_p - closes[i - 3]) / closes[i - 3] * 100.0 if closes[i - 3] > 0 else 0.0

        bundle = get_chart_bundle(dt_tw)
        c = bundle["chart"]
        q_base = bundle["q_base"]
        q_true = bundle["q_true"]
        hj = bundle["hj"]
        ab = bundle[asset_code]
        el_score = ab["el"]
        sched = ab["sched"]

        raw_mins = dt_tw.minute if (dt_tw.hour % 2 == 1) else (60 + dt_tw.minute)
        slot_5m = (raw_mins // 5) * 5
        phase_idx = min(2, raw_mins // 40)
        spec = ab["spec"][phase_idx]
        quad = spec["quadrant"]

        tt = c.three_transmissions
        lqs = [t["liuqin"] for t in tt]
        gens = [t["general"] for t in tt]
        kws = [t["kongwang"] == "空亡" for t in tt]

        is_eval = (slot_5m in sched["eval_minutes"])
        active_lq, active_gen, active_kw = lqs[phase_idx], gens[phase_idx], kws[phase_idx]
        if slot_5m in sched["slot_meta"]:
            meta = sched["slot_meta"][slot_5m]
            if meta.get("is_main_chuan", True):
                active_lq, active_gen, active_kw = meta["liuqin"], meta["general"], meta["kongwang"]
            elif active_kw and not kws[0]:
                active_lq, active_gen, active_kw = lqs[0], gens[0], kws[0]

        # Compute signal (needed for reversal check & new entries)
        bull_trap = (active_lq == "妻財" and active_kw) or (active_lq == "父母" and active_gen in ("螣蛇", "玄武"))
        ren_long = (
            is_eval
            and (not bull_trap)
            and (slope >= long_min_slope)
            and (el_score >= -3.0)
            and (active_lq in ("妻財", "子孫", "父母") and not active_kw)
            and (curr_p >= ma_macro * 0.996)
            and (mom_15m >= -0.05)
        )
        qm_long = (not q_base["wubuyushi"]) and (
            (q_base["good_door"] and q_base["q_score"] >= 15)
            or (quad == "Q1_CLEAR_RUNWAY" and q_true["qm_regime"] in ("QM_FAVORABLE_BOOST", "QM_FAVORABLE"))
        )
        long_sig = ren_long and qm_long

        ren_short = (
            is_eval
            and (not long_sig)
            and (slope <= short_max_slope)
            and (el_score <= 5.0)
            and (active_lq in ("官鬼", "兄弟") or active_gen in ("白虎", "玄武"))
            and (curr_p < ma_macro * 1.002)
            and (mom_15m <= 0.05)
        )
        qm_short = (q_base["door"] in ("死門", "驚門") or q_base["wubuyushi"]) or (
            quad == "Q4_TRAP_QUAGMIRE" and q_true["qm_regime"] == "QM_HOSTILE_BEAR"
        )
        short_sig = ren_short and qm_short

        if phase_idx == 2 and active_kw:
            long_sig = short_sig = False
        sig_dir = "LONG" if long_sig else ("SHORT" if short_sig else "HOLD")

        # 1. Manage existing position with realistic intra-bar High/Low checking
        if pos is not None:
            ep = pos["entry"]
            side = pos["side"]
            hold_h = (i - pos["open_idx"]) * 5.0 / 60.0

            if side == "LONG":
                best_raw = (hi_p - ep) / ep
                worst_raw = (lo_p - ep) / ep
                close_raw = (curr_p - ep) / ep
            else:
                best_raw = (ep - lo_p) / ep
                worst_raw = (ep - hi_p) / ep
                close_raw = (ep - curr_p) / ep

            # Conservative intra-bar check: check existing SL before arming BE, then TP
            eff_sl = be_lock_pct if pos["be_active"] else -sl_pct
            hit_sl = (worst_raw <= eff_sl)
            hit_tp = (best_raw >= tp_pct)

            if (not hit_sl) and (not pos["be_active"]) and best_raw >= pos["be_trig"]:
                pos["be_active"] = True
                eff_sl = be_lock_pct

            exit_raw = None
            exit_reason = None
            if hit_sl:
                exit_raw = eff_sl
                exit_reason = "BE" if pos["be_active"] else "SL"
            elif hit_tp:
                exit_raw = tp_pct
                exit_reason = "TP"
            elif (phase_idx == 2 and kws[2]) and close_raw >= 0.0035:
                exit_raw = close_raw
                exit_reason = "KW_LOCK"
            elif (not pos["be_active"]) and (phase_idx == 1 and kws[1]) and close_raw <= -0.0055:
                exit_raw = close_raw
                exit_reason = "TIGHT_SL"
            elif is_eval and ((side == "LONG" and sig_dir == "SHORT") or (side == "SHORT" and sig_dir == "LONG")):
                exit_raw = close_raw
                exit_reason = "REV"
            elif hold_h >= 3.95:
                exit_raw = close_raw
                exit_reason = "TIME"

            if exit_reason is not None:
                net_r = (exit_raw - fee_rt) * pos["size"]
                eq *= (1.0 + net_r)
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd
                trades.append({
                    "side": side,
                    "net_r": net_r,
                    "reason": exit_reason,
                    "win": net_r > 0,
                })
                pos = None
            else:
                # Scale-up check
                scale_long_ok = is_eval and (quad == "Q1_CLEAR_RUNWAY") and (not q_true["menpo"]) and (active_lq in ("妻財", "子孫", "父母") and not active_kw)
                scale_short_ok = is_eval and (quad in ("Q3_MILD_DRIFT", "Q4_TRAP_QUAGMIRE")) and (active_lq in ("官鬼", "兄弟") and not active_kw)
                cap = 0.80 if q_true["palace_helps"] else 0.78
                if (not pos["scaled"]) and close_raw > 0.0015:
                    if side == "LONG" and scale_long_ok:
                        pos["size"] = min(cap, round(pos["size"] * 1.28, 2))
                        pos["scaled"] = True
                    elif side == "SHORT" and scale_short_ok:
                        pos["size"] = min(0.78, round(pos["size"] * 1.25, 2))
                        pos["scaled"] = True

        # 2. Check new entry
        if pos is None and sig_dir in ("LONG", "SHORT"):
            base_sz = 0.55 if sched["eval_count"] >= 4 else 0.50
            if q_true["qm_regime"] == "QM_FAVORABLE_BOOST": qm_ml, qm_ms, qm_be = 1.10, 0.92, False
            elif q_true["qm_regime"] == "QM_FAVORABLE": qm_ml, qm_ms, qm_be = 1.04, 0.96, False
            elif q_true["qm_regime"] == "QM_MENPO_OR_FIRE": qm_ml, qm_ms, qm_be = 0.92, 1.00, True
            elif q_true["qm_regime"] == "QM_HOSTILE_BEAR": qm_ml, qm_ms, qm_be = 0.88, 1.12, True
            else: qm_ml, qm_ms, qm_be = 1.00, 1.00, False

            spec_m, be_trig = 1.0, 0.0100
            if sig_dir == "LONG":
                if quad == "Q1_CLEAR_RUNWAY": spec_m = 1.10
                elif quad == "Q2_FRICTION_RUSH": spec_m, be_trig = 0.94, round(tp_pct * 0.45, 4)
                elif quad == "Q4_TRAP_QUAGMIRE": spec_m, be_trig = 0.88, round(tp_pct * 0.45, 4)
                if qm_be: be_trig = min(be_trig, round(tp_pct * 0.43, 4))
                sz = round(min(0.75, max(0.40, base_sz * hj["long_size_mult"] * spec_m * qm_ml)), 2)
            else:
                if quad == "Q4_TRAP_QUAGMIRE": spec_m = 1.12
                elif quad == "Q2_FRICTION_RUSH": spec_m = 1.04
                elif quad == "Q1_CLEAR_RUNWAY": spec_m, be_trig = 0.92, round(tp_pct * 0.48, 4)
                sz = round(min(0.75, max(0.40, base_sz * hj["short_size_mult"] * spec_m * qm_ms)), 2)

            pos = {
                "side": sig_dir, "entry": curr_p, "size": sz, "open_idx": i,
                "be_trig": be_trig, "be_active": False, "scaled": False,
            }

    n_tr = len(trades)
    wins = sum(1 for t in trades if t["win"])
    gp = sum(t["net_r"] for t in trades if t["net_r"] > 0)
    gl = abs(sum(t["net_r"] for t in trades if t["net_r"] < 0))
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)

    longs = [t for t in trades if t["side"] == "LONG"]
    shorts = [t for t in trades if t["side"] == "SHORT"]
    l_wr = (sum(1 for t in longs if t["win"]) / len(longs) * 100.0) if longs else 0.0
    s_wr = (sum(1 for t in shorts if t["win"]) / len(shorts) * 100.0) if shorts else 0.0
    l_sum = sum(t["net_r"] for t in longs) * 100.0
    s_sum = sum(t["net_r"] for t in shorts) * 100.0
    bh = (closes[-1] / closes[132] - 1.0) * 100.0

    return {
        "n_trades": n_tr,
        "wr": (wins / n_tr * 100.0) if n_tr else 0.0,
        "ret_pct": (eq - 1.0) * 100.0,
        "mdd_pct": max_dd * 100.0,
        "pf": pf,
        "bh_pct": bh,
        "l_n": len(longs), "l_wr": l_wr, "l_sum": l_sum,
        "s_n": len(shorts), "s_wr": s_wr, "s_sum": s_sum,
    }


def main():
    parser = argparse.ArgumentParser(description="Real 5m K-Line Backtest for v15.1 BTC & ETH")
    parser.add_argument("--days", type=int, default=90, help="Days of real 5m K-lines to fetch (default: 90)")
    parser.add_argument("--refresh", action="store_true", help="Ignore local cache and re-download")
    parser.add_argument("--self-test", action="store_true", help="Offline syntax/logic smoke test")
    args = parser.parse_args()

    variants = [
        ("A. v15.1 Baseline",     -999.0, 0.25, 0.0010),
        ("B. +SlopeGuard(-0.05)", -0.05,  0.25, 0.0010),
        ("C. +Slope+BE(+0.20%)",  -0.05,  0.25, 0.0020),
        ("D. StrictTrend(0.00)",   0.00,  0.00, 0.0020),
    ]

    datasets = {}
    for asset in ("BTC", "ETH"):
        if args.self_test:
            src, bars = generate_selftest_ohlcv(asset, days=min(args.days, 14))
        else:
            src, bars = fetch_real_5m_ohlcv(asset, days=args.days, refresh=args.refresh)
        t0 = datetime.datetime.fromtimestamp(bars[0][0] / 1000.0, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        t1 = datetime.datetime.fromtimestamp(bars[-1][0] / 1000.0, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        datasets[asset] = (src, bars, t0, t1)

    print("\n" + "=" * 96)
    print(f"  [REAL 5m K-LINE BACKTEST & MA120 SLOPE GUARD A/B TEST | Window: {args.days} Days]")
    print("  Execution: Intra-bar High/Low Conservative TP/SL | Fees: BTC 0.12% / ETH 0.14% RT")
    print("=" * 96)

    results = {v[0]: {} for v in variants}

    for asset, fee in (("BTC", 0.0012), ("ETH", 0.0014)):
        src, bars, t0, t1 = datasets[asset]
        bh = (bars[-1][4] / bars[132][4] - 1.0) * 100.0
        print(f"\n>>> {ASSET_PROFILES[asset]['name_en']} | Source: {src} | Bars: {len(bars)} ({t0} -> {t1}) | B&H: {bh:+.2f}%")
        print(f"{'Variant':<24} | {'Trades':>6} | {'WinRate':>7} | {'Net 1x':>8} | {'MaxDD':>6} | {'PF':>5} | {'LONG (N/WR/Sum)':<21} | {'SHORT (N/WR/Sum)'}")
        print("-" * 108)
        for v_name, l_min, s_max, be_lk in variants:
            r = run_variant_backtest(bars, asset, fee_rt=fee, long_min_slope=l_min, short_max_slope=s_max, be_lock_pct=be_lk)
            results[v_name][asset] = r
            l_str = f"{r['l_n']:>3d}/{r['l_wr']:>4.1f}%/{r['l_sum']:>+6.1f}%"
            s_str = f"{r['s_n']:>3d}/{r['s_wr']:>4.1f}%/{r['s_sum']:>+6.1f}%"
            print(f"{v_name:<24} | {r['n_trades']:>6d} | {r['wr']:>6.1f}% | {r['ret_pct']:>+7.2f}% | {r['mdd_pct']:>5.2f}% | {r['pf']:>5.2f} | {l_str:<21} | {s_str}")

    print("\n" + "-" * 96)
    print("  [Combined Portfolio Summary: 60% BTC / 40% ETH (1x Unleveraged, Real 5m Data)]")
    for v_name, _, _, _ in variants:
        rb = results[v_name]["BTC"]
        re = results[v_name]["ETH"]
        c60 = 0.60 * rb["ret_pct"] + 0.40 * re["ret_pct"]
        c50 = 0.50 * rb["ret_pct"] + 0.50 * re["ret_pct"]
        tot_tr = rb["n_trades"] + re["n_trades"]
        print(f"    {v_name:<24} | Total Trades: {tot_tr:>4d} | 60/40 Net 1x: {c60:>+7.2f}% | 50/50 Ref: {c50:>+7.2f}%")
    print("=" * 96)


if __name__ == "__main__":
    main()
