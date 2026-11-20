#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
multi_asset_real_audit_v2.py
Run:
  ~/btc_bot/venv/bin/python ~/btc_bot/multi_asset_real_audit_v2.py --years 5 --mode o2c
  ~/btc_bot/venv/bin/python ~/btc_bot/multi_asset_real_audit_v2.py --years 5 --mode c2c
"""

import argparse
import datetime
import os
import sys
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from daliuren_engine import cast_daily_tsmc_chart
from metaphysics_v2 import calc_true_qimen_v2, calc_pure_daliuren_2d_v2, get_huangji_astro_profile
from audit_stats import welch_t_test, mann_whitney_u_test, block_permutation_p, bh_fdr

# (Name, Ticker, Element, RenPalace, Tomb, OpenHrTW, QmPalaceForSchemeB)
ASSETS = [
    ("Gold (GC=F)",      "GC=F",    "金", "酉", "丑", 9,  7),
    ("TSMC (2330.TW)",   "2330.TW", "火", "午", "戌", 9,  9),
    ("TAIEX (^TWII)",    "^TWII",   "木", "卯", "未", 9,  3),
    ("S&P 500 (^GSPC)",  "^GSPC",   "金", "申", "丑", 21, 6),
    ("NASDAQ (^IXIC)",   "^IXIC",   "火", "巳", "戌", 21, 9),
    ("USD/JPY (JPY=X)",  "JPY=X",   "水", "子", "辰", 9,  1),
    ("SOL (SOL-USD)",    "SOL-USD", "火", "巳", "戌", 9,  9),
]


def fetch_yahoo_daily(ticker: str, years: int = 5) -> List[Dict[str, Any]]:
    import requests

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    resp = requests.get(url, params={"range": f"{years}y", "interval": "1d"}, headers=headers, timeout=15)
    resp.raise_for_status()
    res = resp.json()["chart"]["result"][0]

    gmtoffset = int(res.get("meta", {}).get("gmtoffset", 0))
    tz_local = datetime.timezone(datetime.timedelta(seconds=gmtoffset))
    ts_list = res["timestamp"]
    q0 = res["indicators"]["quote"][0]
    opens = q0.get("open", [])
    closes = q0.get("close", [])
    adj_list = res["indicators"].get("adjclose", [{}])[0].get("adjclose", closes)

    out = []
    for ts, o, c, adj in zip(ts_list, opens, closes, adj_list):
        if o is None or c is None or adj is None or o <= 0 or c <= 0 or adj <= 0:
            continue
        d_local = datetime.datetime.fromtimestamp(ts, tz=tz_local).date()
        out.append({"date": d_local, "open": float(o), "close": float(c), "adj": float(adj)})
    return out


def audit_asset(
    name: str, bars: List[Dict[str, Any]], el: str, pal: str, tomb: str, open_hr_tw: int, qm_pal: int, mode: str, n_perm: int
) -> List[Dict[str, Any]]:
    rets: List[float] = []
    dates: List[datetime.date] = []
    if mode == "o2c":
        for b in bars:
            dates.append(b["date"])
            rets.append((b["close"] / b["open"] - 1.0) * 100.0)
    else:
        # c2c: 昨收(還原) -> 今收(還原)，精準對齊「今日(bars[i])」的開盤排盤
        for i in range(1, len(bars)):
            dates.append(bars[i]["date"])
            rets.append((bars[i]["adj"] / bars[i - 1]["adj"] - 1.0) * 100.0)

    labels_map: Dict[str, List[int]] = {
        "Ren_Q1-Q4": [],
        "NonTomb-Tomb": [],
        "QMA_Fav-Host": [],
        "QMA_Boost-MenPo": [],
        "QMB_Fav-Host": [],
        "QMB_Boost-MenPo": [],
        "QMC_HostGuest": [],
        "HJ_Yang9-Yin6": [],
    }

    for d in dates:
        dt_tw = datetime.datetime(d.year, d.month, d.day, open_hr_tw, 30)
        chart = cast_daily_tsmc_chart(dt_tw, include_intraday=False)
        spec = calc_pure_daliuren_2d_v2(chart, 0, el=el, palace=pal, tomb=tomb)
        qm = calc_true_qimen_v2(chart, asset_qm_palace=qm_pal)
        hj = get_huangji_astro_profile(dt_tw, sun_lon=chart.pillars["sun_longitude"])
        sa, sb, sc = qm["scheme_a"], qm["scheme_b"], qm["scheme_c"]

        labels_map["Ren_Q1-Q4"].append(1 if spec["quadrant"] == "Q1_CLEAR_RUNWAY" else (-1 if spec["quadrant"] == "Q4_TRAP_QUAGMIRE" else 0))
        labels_map["NonTomb-Tomb"].append(-1 if spec["has_tomb"] else 1)
        labels_map["QMA_Fav-Host"].append(1 if sa["qm_regime"] in ("QM_FAVORABLE_BOOST", "QM_FAVORABLE") else (-1 if sa["qm_regime"] == "QM_HOSTILE_BEAR" else 0))
        labels_map["QMA_Boost-MenPo"].append(1 if sa["rel_tag"] == "PalaceBoost" else (-1 if sa["rel_tag"] == "MenPo(Clash)" else 0))
        labels_map["QMB_Fav-Host"].append(1 if sb["qm_regime"] in ("QM_FAVORABLE_BOOST", "QM_FAVORABLE") else (-1 if sb["qm_regime"] == "QM_HOSTILE_BEAR" else 0))
        labels_map["QMB_Boost-MenPo"].append(1 if sb["rel_tag"] == "PalaceBoost" else (-1 if sb["rel_tag"] == "MenPo(Clash)" else 0))
        labels_map["QMC_HostGuest"].append(1 if sc["hg_pure_group"] == "HG_FAV_PURE" else -1)
        labels_map["HJ_Yang9-Yin6"].append(1 if hj["is_yang"] else -1)

    rows = []
    for fname, lbls in labels_map.items():
        a = [rets[i] for i, v in enumerate(lbls) if v == 1]
        b = [rets[i] for i, v in enumerate(lbls) if v == -1]
        diff, _, p_w = welch_t_test(a, b)
        p_mw = mann_whitney_u_test(a, b)
        p_perm = block_permutation_p(rets, lbls, block_size=5, n_perm=n_perm)
        rows.append({
            "asset": name, "factor": fname, "n_days": len(rets), "na": len(a), "nb": len(b),
            "diff": diff, "p_w": p_w, "p_mw": p_mw, "p_perm": p_perm,
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description="5-Year Cross-Asset Daily Audit v2")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--mode", choices=["o2c", "c2c"], default="o2c", help="o2c=Open->Close same day, c2c=AdjClose prev->curr")
    parser.add_argument("--perms", type=int, default=300)
    args = parser.parse_args()

    all_rows: List[Dict[str, Any]] = []
    for name, ticker, el, pal, tomb, hr, qm_pal in ASSETS:
        try:
            bars = fetch_yahoo_daily(ticker, years=args.years)
            if len(bars) < 100:
                print(f"[SKIP] {name}: too few bars ({len(bars)})")
                continue
            all_rows.extend(audit_asset(name, bars, el, pal, tomb, hr, qm_pal, args.mode, args.perms))
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

    fdr_perm = bh_fdr({f"{r['asset']}|{r['factor']}": r["p_perm"] for r in all_rows})
    print("=" * 124)
    print(f"  [CROSS-ASSET DAILY AUDIT V2 | {args.years}Y | MODE={args.mode.upper()} | GLOBAL BH-FDR OVER {len(all_rows)} TESTS]")
    print("=" * 124)
    print(f"{'Asset':<16} | {'Factor':<17} | {'N(+/-)':<10} | {'Diff%':>8} | {'Welch_p':>7} | {'MW-U_p':>7} | {'Perm_p':>7} | {'FDR(P)':>7} | {'Verdict'}")
    print("-" * 124)

    factor_hits: Dict[str, List[str]] = {}
    for r in all_rows:
        q = fdr_perm[f"{r['asset']}|{r['factor']}"]
        if r["diff"] > 0 and r["p_mw"] < 0.05 and r["p_perm"] < 0.05 and q < 0.10:
            v = "CANDIDATE"
            factor_hits.setdefault(r["factor"], []).append(r["asset"])
        elif r["diff"] < 0 and r["p_mw"] < 0.05 and r["p_perm"] < 0.05 and q < 0.10:
            v = "INVERSE!"
        elif min(r["p_w"], r["p_mw"], r["p_perm"]) < 0.05:
            v = "WEAK/FAIL_FDR"
        else:
            v = "NOISE"
        print(
            f"{r['asset']:<16} | {r['factor']:<17} | {r['na']:>4d}/{r['nb']:<5d} | "
            f"{r['diff']:>+7.3f}% | {r['p_w']:>7.4f} | {r['p_mw']:>7.4f} | {r['p_perm']:>7.4f} | {q:>7.4f} | {v}"
        )

    print("=" * 124)
    print("  [FACTORS PASSING GLOBAL BH-FDR (<0.10) & DIRECTION]")
    if not factor_hits:
        print("  -> None (No daily factor survived multiple-testing correction across assets).")
    else:
        for f, hit_assets in factor_hits.items():
            print(f"  -> {f:<18}: {len(hit_assets)}/{len(ASSETS)} assets ({', '.join(hit_assets)})")
    print("=" * 124)


if __name__ == "__main__":
    main()