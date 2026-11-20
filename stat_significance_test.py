#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2-Year Real Binance Statistical Significance Test (stat_significance_test.py)
=============================================================================
Run on DigitalOcean Singapore Droplet inside ~/btc_bot/:
  ~/btc_bot/venv/bin/python ~/btc_bot/stat_significance_test.py --days 730

Tests whether DaLiuRen 2D Quadrants, Element Tomb, True QiMen (MenPo/PalaceBoost/WuBuYuShi),
and HuangJi Jingshi (Yang/Yin & 6-Yao) have statistically significant predictive power
(direction, win rate, or volatility) on 100% REAL 2-year Binance BTC/USDT & ETH/USDT data.

Zero extra packages required (uses standard library math.erfc + existing ccxt).
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from daliuren_engine import cast_daily_tsmc_chart
from btc_strategy import (
    ASSET_PROFILES,
    calc_true_qimen_9palace,
    calc_pure_daliuren_2d,
    get_huangji_lichun_soft_profile,
)

EXCHANGE_SOURCES = [
    ("binance", {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 1000),
    ("bybit",   {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 1000),
    ("gate",    {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 1000),
    ("okx",     {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}, 300),
]


def norm_p_two_sided(z: float) -> float:
    """Two-sided p-value from normal/large-sample t statistic."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def summarize(vals: List[float]) -> Tuple[int, float, float, float]:
    """Return (n, mean, std, up_rate_pct)."""
    n = len(vals)
    if n == 0:
        return 0, 0.0, 0.0, 0.0
    m = sum(vals) / n
    var = sum((x - m) ** 2 for x in vals) / max(1, n - 1)
    up = sum(1 for x in vals if x > 0) / n * 100.0
    return n, m, math.sqrt(var), up


def welch_test(a: List[float], b: List[float]) -> Tuple[float, float, float]:
    """Return (diff_mean, t_stat, p_val) comparing group a vs group b."""
    na, ma, sa, _ = summarize(a)
    nb, mb, sb, _ = summarize(b)
    if na < 5 or nb < 5:
        return ma - mb, 0.0, 1.0
    se = math.sqrt((sa * sa) / na + (sb * sb) / nb)
    if se <= 1e-12:
        return ma - mb, 0.0, 1.0
    t = (ma - mb) / se
    return ma - mb, t, norm_p_two_sided(t)


def mean_vs_baseline_test(sub: List[float], base_mean: float) -> Tuple[float, float]:
    """One-sample t-test of subgroup mean vs overall market baseline mean."""
    n, m, s, _ = summarize(sub)
    if n < 5 or s <= 1e-12:
        return 0.0, 1.0
    t = (m - base_mean) / (s / math.sqrt(n))
    return t, norm_p_two_sided(t)


def fetch_real_2h_ohlcv(asset: str, days: int, refresh: bool = False) -> Tuple[str, List[List[float]]]:
    cache_path = os.path.join(SCRIPT_DIR, f"cache_stat_{asset}_{days}d_2h.json")
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
    step_ms = 2 * 3600 * 1000
    target_bars = days * 12

    for ex_id, sym_map, limit in EXCHANGE_SOURCES:
        sym = sym_map[asset]
        try:
            ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
            all_bars: List[List[float]] = []
            cursor = since_ms
            stalls = 0
            print(f"[FETCH] Downloading {days}d real 2h {sym} from {ex_id}...", flush=True)
            while cursor < now_ms - step_ms and len(all_bars) < target_bars + 200:
                batch = ex.fetch_ohlcv(sym, timeframe="2h", since=cursor, limit=limit)
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
            print(f"[WARN] {ex_id} returned only {len(bars)} 2h bars for {sym}; trying next...", flush=True)
        except Exception as e:
            print(f"[WARN] {ex_id} fetch failed for {sym}: {e}", flush=True)

    raise RuntimeError(f"Failed to fetch 2h OHLCV for {asset}")


def generate_selftest_2h(asset: str, days: int = 120) -> Tuple[str, List[List[float]]]:
    n = days * 12
    start_dt = datetime.datetime(2025, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
    p = 90000.0 if asset == "BTC" else 3000.0
    rng = 42 if asset == "BTC" else 99
    bars = []
    for i in range(n):
        ts = int((start_dt + datetime.timedelta(hours=2 * i)).timestamp() * 1000)
        rng = (rng * 1664525 + 1013904223) % 4294967296
        u = (rng / 4294967296.0) - 0.5
        o = p
        c = max(10.0, o * (1.0 + u * 0.018))
        bars.append([ts, o, max(o, c) * 1.003, min(o, c) * 0.997, c, 100.0])
        p = c
    return "self-test-random", bars


def sig_tag(p: float) -> str:
    if p < 0.01:
        return "**p<0.01"
    if p < 0.05:
        return "*p<0.05"
    return "noise"


def print_group_table(title: str, groups: Dict[str, List[Tuple[float, float, float]]], base_2h: float, base_4h: float, order: List[str]):
    print(f"\n  [{title}]")
    print(f"  {'Group':<20} | {'N':>5} | {'Up2H%':>6} | {'Avg2H%':>8} | {'p(2H)':>7} | {'Avg4H%':>8} | {'p(4H)':>7} | {'AvgVol2H%':>9} | {'Verdict'}")
    print("  " + "-" * 102)
    for k in order:
        rows = groups.get(k, [])
        if not rows:
            continue
        r2 = [x[0] for x in rows]
        r4 = [x[1] for x in rows]
        v2 = [x[2] for x in rows]
        n, m2, _, up2 = summarize(r2)
        _, m4, _, _ = summarize(r4)
        _, mv, _, _ = summarize(v2)
        _, p2 = mean_vs_baseline_test(r2, base_2h)
        _, p4 = mean_vs_baseline_test(r4, base_4h)
        verdict = sig_tag(min(p2, p4))
        print(f"  {k:<20} | {n:>5d} | {up2:>5.1f}% | {m2:>+7.4f}% | {p2:>7.4f} | {m4:>+7.4f}% | {p4:>7.4f} | {mv:>8.4f}% | {verdict}")


def analyze_asset(asset: str, src: str, bars: List[List[float]]):
    prof = ASSET_PROFILES[asset]
    tz_tw = datetime.timezone(datetime.timedelta(hours=8))
    n = len(bars)

    t0 = datetime.datetime.fromtimestamp(bars[0][0] / 1000.0, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
    t1 = datetime.datetime.fromtimestamp(bars[-1][0] / 1000.0, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
    bh = (bars[-1][4] / bars[0][4] - 1.0) * 100.0

    # Collect forward returns for each 2h Shichen bar
    all_2h, all_4h = [], []
    quad_g = defaultdict(list)
    tomb_g = defaultdict(list)
    qm_g = defaultdict(list)
    menpo_g = defaultdict(list)
    wubu_g = defaultdict(list)

    # Non-overlapping daily buckets for HuangJi (avoid 12x autocorrelation inflation)
    hj_yinyang_d = defaultdict(list)
    hj_proper_d = defaultdict(list)
    hj_yao_d = defaultdict(list)

    seen_days = set()

    for i in range(n - 12):
        ts_ms = int(bars[i][0])
        dt_tw = datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=tz_tw).replace(tzinfo=None)
        c0 = float(bars[i][4])
        c1 = float(bars[i + 1][4])
        c2 = float(bars[i + 2][4])
        c12 = float(bars[i + 12][4])
        if c0 <= 0:
            continue

        ret_2h = (c1 / c0 - 1.0) * 100.0
        ret_4h = (c2 / c0 - 1.0) * 100.0
        vol_2h = abs(ret_2h)
        all_2h.append(ret_2h)
        all_4h.append(ret_4h)
        tup = (ret_2h, ret_4h, vol_2h)

        chart = cast_daily_tsmc_chart(dt_tw)
        spec = calc_pure_daliuren_2d(chart, 0, el=prof["el"], palace=prof["palace"], tomb=prof["tomb"])
        q_true = calc_true_qimen_9palace(dt_tw, chart)

        quad_g[spec["quadrant"]].append(tup)
        has_tomb = any("Tomb(" in b for b in spec["blockers"])
        tomb_g["Tomb_Hit" if has_tomb else "Non_Tomb"].append(tup)

        qm_g[q_true["qm_regime"]].append(tup)
        menpo_g[q_true["rel_tag"]].append(tup)
        wubu_g["WuBuYuShi" if q_true["wubuyushi"] else "Normal_Hour"].append(tup)

        day_key = (dt_tw.year, dt_tw.month, dt_tw.day)
        if day_key not in seen_days:
            seen_days.add(day_key)
            ret_24h = (c12 / c0 - 1.0) * 100.0
            hj = get_huangji_lichun_soft_profile(dt_tw)
            hj_yinyang_d["Yang9" if hj["is_yang"] else "Yin6"].append(ret_24h)
            hj_proper_d["Proper(DangWei)" if hj["is_proper"] else "Unproper"].append(ret_24h)
            hj_yao_d[f"Yao{hj['yao_idx']+1}"].append(ret_24h)

    _, base_2h, _, base_up2 = summarize(all_2h)
    _, base_4h, _, _ = summarize(all_4h)

    print("\n" + "=" * 106)
    print(f">>> {prof['name_en']} | Source: {src} | {len(all_2h)} Shichen (2H) Bars ({t0} -> {t1}) | B&H: {bh:+.2f}%")
    print(f"    Market Baseline: Up2H = {base_up2:.2f}% | Avg2H = {base_2h:+.4f}% | Avg4H = {base_4h:+.4f}%")
    print("=" * 106)

    print_group_table(
        "1. DaLiuRen 2D Spectrum Quadrants",
        quad_g, base_2h, base_4h,
        ["Q1_CLEAR_RUNWAY", "Q2_FRICTION_RUSH", "Q3_MILD_DRIFT", "Q4_TRAP_QUAGMIRE"],
    )
    diff_q, t_q, p_q = welch_test([x[0] for x in quad_g["Q1_CLEAR_RUNWAY"]], [x[0] for x in quad_g["Q4_TRAP_QUAGMIRE"]])
    print(f"    -> Welch Test Q1 vs Q4 (2H): diff={diff_q:+.4f}%, t={t_q:+.2f}, p={p_q:.4f} [{sig_tag(p_q)}]")

    print_group_table(
        f"2. Element Tomb ({prof['tomb']}) vs Non-Tomb",
        tomb_g, base_2h, base_4h,
        ["Tomb_Hit", "Non_Tomb"],
    )

    print_group_table(
        "3. True QiMen 9-Palace Regimes",
        qm_g, base_2h, base_4h,
        ["QM_FAVORABLE_BOOST", "QM_FAVORABLE", "QM_NEUTRAL", "QM_MENPO_OR_FIRE", "QM_HOSTILE_BEAR"],
    )
    diff_qm, t_qm, p_qm = welch_test(
        [x[0] for x in qm_g["QM_FAVORABLE_BOOST"]] + [x[0] for x in qm_g["QM_FAVORABLE"]],
        [x[0] for x in qm_g["QM_HOSTILE_BEAR"]],
    )
    print(f"    -> Welch Test Favorable vs Hostile (2H): diff={diff_qm:+.4f}%, t={t_qm:+.2f}, p={p_qm:.4f} [{sig_tag(p_qm)}]")

    print_group_table(
        "4. QiMen Door-Palace Relation (MenPo vs PalaceBoost)",
        menpo_g, base_2h, base_4h,
        ["PalaceBoost", "Neutral", "PalaceCtrl", "MenPo(Clash)"],
    )
    print_group_table(
        "5. WuBuYuShi vs Normal Hour",
        wubu_g, base_2h, base_4h,
        ["Normal_Hour", "WuBuYuShi"],
    )

    # HuangJi 24H Daily Test
    all_d = hj_yinyang_d["Yang9"] + hj_yinyang_d["Yin6"]
    _, base_d, _, up_d = summarize(all_d)
    print(f"\n  [6. HuangJi Jingshi LiChun (Non-Overlapping Daily 24H Returns | N={len(all_d)} days | Base Up={up_d:.1f}%, Avg={base_d:+.3f}%)]")
    print(f"  {'Group':<20} | {'Days':>5} | {'Up24H%':>7} | {'Avg24H%':>9} | {'p(vs Base)':>10} | {'Verdict'}")
    print("  " + "-" * 72)
    for k in ("Yang9", "Yin6"):
        n_d, m_d, _, u_d = summarize(hj_yinyang_d[k])
        _, p_d = mean_vs_baseline_test(hj_yinyang_d[k], base_d)
        print(f"  {k:<20} | {n_d:>5d} | {u_d:>6.1f}% | {m_d:>+8.4f}% | {p_d:>10.4f} | {sig_tag(p_d)}")
    d_yy, t_yy, p_yy = welch_test(hj_yinyang_d["Yang9"], hj_yinyang_d["Yin6"])
    print(f"    -> Welch Test Yang9 vs Yin6 (24H): diff={d_yy:+.4f}%, t={t_yy:+.2f}, p={p_yy:.4f} [{sig_tag(p_yy)}]")

    for k in ("Proper(DangWei)", "Unproper"):
        n_d, m_d, _, u_d = summarize(hj_proper_d[k])
        _, p_d = mean_vs_baseline_test(hj_proper_d[k], base_d)
        print(f"  {k:<20} | {n_d:>5d} | {u_d:>6.1f}% | {m_d:>+8.4f}% | {p_d:>10.4f} | {sig_tag(p_d)}")

    for idx in range(1, 7):
        k = f"Yao{idx}"
        if hj_yao_d[k]:
            n_d, m_d, _, u_d = summarize(hj_yao_d[k])
            _, p_d = mean_vs_baseline_test(hj_yao_d[k], base_d)
            print(f"  {k:<20} | {n_d:>5d} | {u_d:>6.1f}% | {m_d:>+8.4f}% | {p_d:>10.4f} | {sig_tag(p_d)}")


def main():
    parser = argparse.ArgumentParser(description="2-Year Real Market Statistical Significance Test")
    parser.add_argument("--days", type=int, default=730, help="Days of real 2h candles to test (default: 730 = 2 years)")
    parser.add_argument("--refresh", action="store_true", help="Ignore local cache and re-download")
    parser.add_argument("--self-test", action="store_true", help="Offline smoke test")
    args = parser.parse_args()

    print("=" * 106)
    print(f"  [TRI-SYSTEM STATISTICAL SIGNIFICANCE AUDIT | {args.days} DAYS REAL 2H/DAILY DATA]")
    print("  Criteria: p < 0.01 (**strong) & consistent across BOTH BTC and ETH -> Genuine Edge;")
    print("            p >= 0.05 (noise) -> Indistinguishable from random chance.")
    print("=" * 106)

    for asset in ("BTC", "ETH"):
        if args.self_test:
            src, bars = generate_selftest_2h(asset, days=120)
        else:
            src, bars = fetch_real_2h_ohlcv(asset, days=args.days, refresh=args.refresh)
        analyze_asset(asset, src, bars)


if __name__ == "__main__":
    main()