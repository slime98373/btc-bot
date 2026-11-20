#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5-Year Cross-Asset Real Data Statistical Audit (multi_asset_real_audit.py)
==========================================================================
Run on DigitalOcean Singapore Droplet inside ~/btc_bot/:
  ~/btc_bot/venv/bin/python ~/btc_bot/multi_asset_real_audit.py

Fetches 5 years of 100% REAL daily market data (via Yahoo Finance public chart API + Binance)
for 7 diverse investment assets and runs Welch t-tests / p-value audits for:
  - DaLiuRen 2D Spectrum (Q1 vs Q4)
  - Element Tomb (Tomb vs Non-Tomb)
  - True QiMen 9-Palace (Favorable vs Hostile, PalaceBoost vs MenPo)
  - HuangJi Jingshi LiChun (Yang9 vs Yin6)

Assets tested (5Y Daily):
  1. Gold Futures / Spot Proxy (GC=F, Metal/You-Palace/Tomb Chou)
  2. TSMC Taiwan (2330.TW, Fire/Wu-Palace/Tomb Xu)
  3. Taiwan TAIEX (^TWII, Wood/Mao-Palace/Tomb Wei)
  4. S&P 500 (^GSPC, Metal/Shen-Palace/Tomb Chou)
  5. NASDAQ (^IXIC, Fire/Si-Palace/Tomb Xu)
  6. USD/JPY (JPY=X, Water/Zi-Palace/Tomb Chen)
  7. Solana (SOL-USD, Fire/Si-Palace/Tomb Xu)
"""

import argparse
import datetime
import math
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from daliuren_engine import cast_daily_tsmc_chart
from btc_strategy import (
    calc_true_qimen_9palace,
    calc_pure_daliuren_2d,
    get_huangji_lichun_soft_profile,
)

ASSETS = [
    ("Gold (GC=F)",      "GC=F",    "金", "酉", "丑", 9),
    ("TSMC (2330.TW)",   "2330.TW", "火", "午", "戌", 9),
    ("TAIEX (^TWII)",    "^TWII",   "木", "卯", "未", 9),
    ("S&P 500 (^GSPC)",  "^GSPC",   "金", "申", "丑", 21),
    ("NASDAQ (^IXIC)",   "^IXIC",   "火", "巳", "戌", 21),
    ("USD/JPY (JPY=X)",  "JPY=X",   "水", "子", "辰", 9),
    ("SOL (SOL-USD)",    "SOL-USD", "火", "巳", "戌", 9),
]


def norm_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def summarize(vals: List[float]) -> Tuple[int, float, float]:
    n = len(vals)
    if n == 0:
        return 0, 0.0, 0.0
    m = sum(vals) / n
    var = sum((x - m) ** 2 for x in vals) / max(1, n - 1)
    return n, m, math.sqrt(var)


def welch(a: List[float], b: List[float]) -> Tuple[float, float]:
    """Return (diff_pct, p_val)."""
    na, ma, sa = summarize(a)
    nb, mb, sb = summarize(b)
    if na < 10 or nb < 10:
        return ma - mb, 1.0
    se = math.sqrt((sa * sa) / na + (sb * sb) / nb)
    if se <= 1e-12:
        return ma - mb, 1.0
    return ma - mb, norm_p((ma - mb) / se)


def fetch_yahoo_5y_daily(ticker: str, years: int = 5) -> List[Tuple[datetime.date, float]]:
    import requests

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": f"{years}y", "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    res = data["chart"]["result"][0]
    ts_list = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out = []
    for ts, c in zip(ts_list, closes):
        if c is None or c <= 0:
            continue
        d = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).date()
        out.append((d, float(c)))
    return out


def generate_selftest_daily(seed_val: int, days: int = 1200) -> List[Tuple[datetime.date, float]]:
    start = datetime.date(2022, 1, 1)
    p = 100.0
    rng = seed_val
    out = []
    for i in range(days):
        rng = (rng * 1664525 + 1013904223) % 4294967296
        u = (rng / 4294967296.0) - 0.5
        p = max(1.0, p * (1.0 + u * 0.025))
        out.append((start + datetime.timedelta(days=i), p))
    return out


def tag(diff: float, p: float) -> str:
    star = "**" if p < 0.01 else ("*" if p < 0.05 else " ")
    return f"{diff:+.3f}% (p={p:.3f}){star}"


def audit_one(name: str, series: List[Tuple[datetime.date, float]], el: str, palace: str, tomb: str, open_hr_tw: int):
    q_groups = defaultdict(list)
    tomb_g = defaultdict(list)
    qm_g = defaultdict(list)
    rel_g = defaultdict(list)
    hj_g = defaultdict(list)

    for i in range(len(series) - 1):
        d0, c0 = series[i]
        _, c1 = series[i + 1]
        ret = (c1 / c0 - 1.0) * 100.0
        dt_tw = datetime.datetime(d0.year, d0.month, d0.day, open_hr_tw, 30)

        chart = cast_daily_tsmc_chart(dt_tw)
        spec = calc_pure_daliuren_2d(chart, 0, el=el, palace=palace, tomb=tomb)
        q_true = calc_true_qimen_9palace(dt_tw, chart)
        hj = get_huangji_lichun_soft_profile(dt_tw)

        q_groups[spec["quadrant"]].append(ret)
        has_tomb = any("Tomb(" in b for b in spec["blockers"])
        tomb_g["Tomb" if has_tomb else "NonTomb"].append(ret)
        qm_g[q_true["qm_regime"]].append(ret)
        rel_g[q_true["rel_tag"]].append(ret)
        hj_g["Yang9" if hj["is_yang"] else "Yin6"].append(ret)

    d_q, p_q = welch(q_groups["Q1_CLEAR_RUNWAY"], q_groups["Q4_TRAP_QUAGMIRE"])
    d_t, p_t = welch(tomb_g["NonTomb"], tomb_g["Tomb"])
    d_qm, p_qm = welch(qm_g["QM_FAVORABLE_BOOST"] + qm_g["QM_FAVORABLE"], qm_g["QM_HOSTILE_BEAR"])
    d_mp, p_mp = welch(rel_g["PalaceBoost"], rel_g["MenPo(Clash)"])
    d_hj, p_hj = welch(hj_g["Yang9"], hj_g["Yin6"])

    bh = (series[-1][1] / series[0][1] - 1.0) * 100.0
    n_days = len(series) - 1
    p_min = min(p_q, p_t, p_qm, p_mp, p_hj)
    verdict = "CHECK(p<0.01)" if p_min < 0.01 else ("MARGINAL" if p_min < 0.05 else "ALL NOISE")

    print(
        f"{name:<16} | {n_days:>4d} | {bh:>+7.1f}% | "
        f"{tag(d_q, p_q):<18} | {tag(d_t, p_t):<18} | {tag(d_qm, p_qm):<18} | {tag(d_hj, p_hj):<18} | {verdict}"
    )


def main():
    parser = argparse.ArgumentParser(description="5-Year Cross-Asset Real Data Statistical Audit")
    parser.add_argument("--years", type=int, default=5, help="Years of daily data (default: 5)")
    parser.add_argument("--self-test", action="store_true", help="Offline smoke test")
    args = parser.parse_args()

    print("=" * 134)
    print(f"  [5-YEAR CROSS-ASSET STATISTICAL AUDIT | REAL DAILY MARKET DATA | {args.years}Y]")
    print("  Columns show Welch diff (Expected Bullish Group - Expected Bearish Group) & two-sided p-value.")
    print("  * = p<0.05 (weak/possible chance) | ** = p<0.01 (strong) | Positive diff = matches theory, Negative = opposite.")
    print("=" * 134)
    print(
        f"{'Asset':<16} | {'Days':>4} | {'B&H%':>8} | "
        f"{'Ren Q1-Q4':<18} | {'NonTomb-Tomb':<18} | {'QM Fav-Hostile':<18} | {'HJ Yang9-Yin6':<18} | {'Summary'}"
    )
    print("-" * 134)

    for idx, (name, ticker, el, pal, tomb, hr) in enumerate(ASSETS):
        try:
            if args.self_test:
                series = generate_selftest_daily(100 + idx * 37)
            else:
                series = fetch_yahoo_5y_daily(ticker, years=args.years)
            if len(series) < 100:
                print(f"{name:<16} | [SKIP] Too few bars ({len(series)})")
                continue
            audit_one(name, series, el, pal, tomb, hr)
        except Exception as e:
            print(f"{name:<16} | [ERROR] {e}")

    print("=" * 134)


if __name__ == "__main__":
    main()