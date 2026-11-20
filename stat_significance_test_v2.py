#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stat_significance_test_v2.py
Run:
  ~/btc_bot/venv/bin/python ~/btc_bot/stat_significance_test_v2.py --days 730
  ~/btc_bot/venv/bin/python ~/btc_bot/stat_significance_test_v2.py --days 730 --assets BTC,ETH,SOL
"""

import argparse
import datetime
import json
import os
import sys
import time
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from daliuren_engine import cast_daily_tsmc_chart
from metaphysics_v2 import calc_true_qimen_v2, calc_pure_daliuren_2d_v2, get_huangji_astro_profile
from audit_stats import (
    summarize,
    welch_t_test,
    mann_whitney_u_test,
    proportion_z_test,
    block_permutation_p,
    bh_fdr,
)

ASSET_META = {
    "BTC": {"sym": "BTC/USDT", "el": "火", "palace": "午", "tomb": "戌", "qm_palace": 9},
    "ETH": {"sym": "ETH/USDT", "el": "木", "palace": "卯", "tomb": "未", "qm_palace": 3},
    "SOL": {"sym": "SOL/USDT", "el": "火", "palace": "巳", "tomb": "戌", "qm_palace": 9},
}
EXCHANGES = [("binance", 1000), ("bybit", 1000), ("gate", 1000), ("okx", 300)]


def fetch_real_1h_ohlcv(asset: str, days: int, refresh: bool = False) -> Tuple[str, List[List[float]]]:
    cache_path = os.path.join(SCRIPT_DIR, f"cache_v2_{asset}_{days}d_1h.json")
    if (not refresh) and os.path.exists(cache_path):
        if (time.time() - os.path.getmtime(cache_path)) / 3600.0 < 24.0:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if len(cached.get("bars", [])) >= 500:
                return cached["source"] + " (cached)", cached["bars"]

    import ccxt

    sym = ASSET_META[asset]["sym"]
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - days * 86400 * 1000
    step_ms = 3600 * 1000
    target = days * 24

    for ex_id, limit in EXCHANGES:
        try:
            ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
            all_bars: List[List[float]] = []
            cursor = since_ms
            stalls = 0
            print(f"[FETCH] Downloading {days}d 1h {sym} from {ex_id}...", flush=True)
            while cursor < now_ms - step_ms and len(all_bars) < target + 200:
                batch = ex.fetch_ohlcv(sym, timeframe="1h", since=cursor, limit=limit)
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
            if len(bars) >= max(500, int(target * 0.6)):
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"source": ex_id, "bars": bars}, f)
                return ex_id, bars
        except Exception as e:
            print(f"[WARN] {ex_id} failed for {sym}: {e}", flush=True)
    raise RuntimeError(f"Failed to fetch 1h OHLCV for {asset}")


def build_true_shichen_bars(bars_1h: List[List[float]]) -> Tuple[List[Dict[str, Any]], int]:
    """將 1H K 線依 UTC+8 奇數整點（23, 01, 03...）精準合成真實時辰 K 線，並過濾漏根。"""
    tz_tw = datetime.timezone(datetime.timedelta(hours=8))
    shichen_bars: List[Dict[str, Any]] = []
    skipped_gaps = 0
    for i in range(len(bars_1h) - 1):
        ts1, o1, h1, l1, _c1, _ = bars_1h[i]
        ts2, _o2, h2, l2, c2, _ = bars_1h[i + 1]
        dt_tw = datetime.datetime.fromtimestamp(ts1 / 1000.0, tz=tz_tw).replace(tzinfo=None)
        if dt_tw.hour % 2 != 1 or dt_tw.minute != 0:
            continue
        if int(ts2) - int(ts1) != 3600_000 or o1 <= 0 or min(l1, l2) <= 0:
            skipped_gaps += 1
            continue
        hi, lo = max(h1, h2), min(l1, l2)
        shichen_bars.append({
            "dt_tw": dt_tw,
            "ret": (c2 / o1 - 1.0) * 100.0,
            "range_vol": (hi / lo - 1.0) * 100.0,
        })
    return shichen_bars, skipped_gaps


def build_non_overlapping_daily(bars_1h: List[List[float]]) -> List[Dict[str, Any]]:
    """合成不重疊的 UTC+8 完整 24H 日線（檢查 24 根連續無缺口）。"""
    tz_tw = datetime.timezone(datetime.timedelta(hours=8))
    daily: List[Dict[str, Any]] = []
    for i in range(len(bars_1h) - 23):
        ts0 = int(bars_1h[i][0])
        dt_tw = datetime.datetime.fromtimestamp(ts0 / 1000.0, tz=tz_tw).replace(tzinfo=None)
        if dt_tw.hour != 0 or dt_tw.minute != 0:
            continue
        ts_end = int(bars_1h[i + 23][0])
        if ts_end - ts0 != 23 * 3600_000:
            continue
        o0, c23 = float(bars_1h[i][1]), float(bars_1h[i + 23][4])
        if o0 <= 0:
            continue
        hi = max(float(b[2]) for b in bars_1h[i:i + 24])
        lo = min(float(b[3]) for b in bars_1h[i:i + 24])
        daily.append({
            "dt_tw": dt_tw,
            "ret": (c23 / o0 - 1.0) * 100.0,
            "range_vol": (hi / lo - 1.0) * 100.0 if lo > 0 else 0.0,
        })
    return daily


def run_asset_audit(asset: str, src: str, bars_1h: List[List[float]], n_perm: int) -> List[Dict[str, Any]]:
    meta = ASSET_META[asset]
    sc_bars, gaps = build_true_shichen_bars(bars_1h)
    day_bars = build_non_overlapping_daily(bars_1h)

    sc_rets = [b["ret"] for b in sc_bars]
    sc_vols = [b["range_vol"] for b in sc_bars]
    d_rets = [b["ret"] for b in day_bars]
    d_vols = [b["range_vol"] for b in day_bars]

    # 定義所有待測二元對比（預期多方=+1, 預期空方=-1, 其餘=0）
    tests_sc: Dict[str, List[int]] = {
        "Ren_Q1_vs_Q4": [],
        "Ren_NonTomb_vs_Tomb": [],
        "QMA_ZhiShi_Fav_vs_Host": [],
        "QMA_ZhiShi_Boost_vs_MenPo": [],
        "QMB_AssetPal_Fav_vs_Host": [],
        "QMB_AssetPal_Boost_vs_MenPo": [],
        "QMC_HostGuest_PureFav_vs_Host": [],
        "QMC_HostGuest_RegimeFav_vs_Host": [],
        "QM_Normal_vs_WuBuYuShi": [],
    }

    for b in sc_bars:
        chart = cast_daily_tsmc_chart(b["dt_tw"], include_intraday=False)
        spec = calc_pure_daliuren_2d_v2(chart, 0, el=meta["el"], palace=meta["palace"], tomb=meta["tomb"])
        qm = calc_true_qimen_v2(chart, asset_qm_palace=meta["qm_palace"])
        sa, sb, sc = qm["scheme_a"], qm["scheme_b"], qm["scheme_c"]

        tests_sc["Ren_Q1_vs_Q4"].append(1 if spec["quadrant"] == "Q1_CLEAR_RUNWAY" else (-1 if spec["quadrant"] == "Q4_TRAP_QUAGMIRE" else 0))
        tests_sc["Ren_NonTomb_vs_Tomb"].append(-1 if spec["has_tomb"] else 1)

        tests_sc["QMA_ZhiShi_Fav_vs_Host"].append(1 if sa["qm_regime"] in ("QM_FAVORABLE_BOOST", "QM_FAVORABLE") else (-1 if sa["qm_regime"] == "QM_HOSTILE_BEAR" else 0))
        tests_sc["QMA_ZhiShi_Boost_vs_MenPo"].append(1 if sa["rel_tag"] == "PalaceBoost" else (-1 if sa["rel_tag"] == "MenPo(Clash)" else 0))

        tests_sc["QMB_AssetPal_Fav_vs_Host"].append(1 if sb["qm_regime"] in ("QM_FAVORABLE_BOOST", "QM_FAVORABLE") else (-1 if sb["qm_regime"] == "QM_HOSTILE_BEAR" else 0))
        tests_sc["QMB_AssetPal_Boost_vs_MenPo"].append(1 if sb["rel_tag"] == "PalaceBoost" else (-1 if sb["rel_tag"] == "MenPo(Clash)" else 0))

        tests_sc["QMC_HostGuest_PureFav_vs_Host"].append(1 if sc["hg_pure_group"] == "HG_FAV_PURE" else -1)
        tests_sc["QMC_HostGuest_RegimeFav_vs_Host"].append(1 if sc["qm_regime"] in ("HG_FAVORABLE_BOOST", "HG_FAVORABLE") else (-1 if sc["qm_regime"] == "HG_HOSTILE" else 0))
        tests_sc["QM_Normal_vs_WuBuYuShi"].append(-1 if qm["wubuyushi"] else 1)

    tests_day: Dict[str, List[int]] = {
        "HJ_Yang9_vs_Yin6(24H)": [],
        "HJ_Proper_vs_Unproper(24H)": [],
    }
    for b in day_bars:
        hj = get_huangji_astro_profile(b["dt_tw"])
        tests_day["HJ_Yang9_vs_Yin6(24H)"].append(1 if hj["is_yang"] else -1)
        tests_day["HJ_Proper_vs_Unproper(24H)"].append(1 if hj["is_proper"] else -1)

    results: List[Dict[str, Any]] = []
    for name, labels in tests_sc.items():
        a = [sc_rets[i] for i, lbl in enumerate(labels) if lbl == 1]
        b_grp = [sc_rets[i] for i, lbl in enumerate(labels) if lbl == -1]
        va = [sc_vols[i] for i, lbl in enumerate(labels) if lbl == 1]
        vb = [sc_vols[i] for i, lbl in enumerate(labels) if lbl == -1]

        diff, t_st, p_w = welch_t_test(a, b_grp)
        p_mw = mann_whitney_u_test(a, b_grp)
        p_perm = block_permutation_p(sc_rets, labels, block_size=12, n_perm=n_perm)
        up_diff, p_up = proportion_z_test(a, b_grp)
        v_diff, _, p_vol = welch_t_test(va, vb)
        results.append({
            "asset": asset, "test": name, "na": len(a), "nb": len(b_grp),
            "diff": diff, "p_welch": p_w, "p_mw": p_mw, "p_perm": p_perm,
            "up_diff": up_diff, "p_up": p_up, "vol_diff": v_diff, "p_vol": p_vol,
        })

    for name, labels in tests_day.items():
        a = [d_rets[i] for i, lbl in enumerate(labels) if lbl == 1]
        b_grp = [d_rets[i] for i, lbl in enumerate(labels) if lbl == -1]
        va = [d_vols[i] for i, lbl in enumerate(labels) if lbl == 1]
        vb = [d_vols[i] for i, lbl in enumerate(labels) if lbl == -1]

        diff, t_st, p_w = welch_t_test(a, b_grp)
        p_mw = mann_whitney_u_test(a, b_grp)
        p_perm = block_permutation_p(d_rets, labels, block_size=7, n_perm=n_perm)
        up_diff, p_up = proportion_z_test(a, b_grp)
        v_diff, _, p_vol = welch_t_test(va, vb)
        results.append({
            "asset": asset, "test": name, "na": len(a), "nb": len(b_grp),
            "diff": diff, "p_welch": p_w, "p_mw": p_mw, "p_perm": p_perm,
            "up_diff": up_diff, "p_up": p_up, "vol_diff": v_diff, "p_vol": p_vol,
        })

    _, m_base, _, up_base = summarize(sc_rets)
    t0 = sc_bars[0]["dt_tw"].strftime("%Y-%m-%d")
    t1 = sc_bars[-1]["dt_tw"].strftime("%Y-%m-%d")
    print(f"\n>>> {asset} | Source: {src} | True Shichen Bars: {len(sc_bars)} (skipped gaps: {gaps}) | Daily: {len(day_bars)} | {t0} -> {t1}")
    print(f"    Baseline 2H Shichen: Avg={m_base:+.4f}% | UpRate={up_base:.2f}%")
    return results


def main():
    parser = argparse.ArgumentParser(description="Corrected Shichen Statistical Significance Audit v2")
    parser.add_argument("--days", type=int, default=730, help="Days of 1h data (default: 730)")
    parser.add_argument("--assets", type=str, default="BTC,ETH", help="Comma-separated assets (BTC,ETH,SOL)")
    parser.add_argument("--perms", type=int, default=400, help="Block permutations (default: 400)")
    parser.add_argument("--refresh", action="store_true", help="Re-download ignoring cache")
    args = parser.parse_args()

    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip().upper() in ASSET_META]
    all_rows: List[Dict[str, Any]] = []
    for asset in assets:
        src, bars_1h = fetch_real_1h_ohlcv(asset, args.days, refresh=args.refresh)
        all_rows.extend(run_asset_audit(asset, src, bars_1h, n_perm=args.perms))

    # 全域 BH-FDR 多重檢定校正（針對 Welch、MW-U 與 Perm 皆分別校正，並以最嚴謹的 Perm/MW-U 為主）
    fdr_welch = bh_fdr({f"{r['asset']}:{r['test']}": r["p_welch"] for r in all_rows})
    fdr_mw = bh_fdr({f"{r['asset']}:{r['test']}": r["p_mw"] for r in all_rows})
    fdr_perm = bh_fdr({f"{r['asset']}:{r['test']}": r["p_perm"] for r in all_rows})

    print("\n" + "=" * 144)
    print(f"  [V2 RIGOROUS SHICHEN AUDIT | TRUE ODD-HOUR SHICHEN | BH-FDR ACROSS ALL {len(all_rows)} TESTS]")
    print("  Positive Diff = Matches Theory | Negative Diff = Opposite | PASS requires: Diff>0, MW-p<0.05, Perm-p<0.05, FDR(Perm)<0.10")
    print("=" * 144)
    print(
        f"{'Asset':<5} | {'Test Factor':<31} | {'N(+/-)':<11} | {'RetDiff%':>8} | "
        f"{'Welch_p':>7} | {'MW-U_p':>7} | {'Perm_p':>7} | {'FDR(P)':>7} | {'UpDiff(p)':<14} | {'VolDiff(p)':<14} | {'Verdict'}"
    )
    print("-" * 144)

    by_test: Dict[str, List[Dict[str, Any]]] = {}
    for r in all_rows:
        key = f"{r['asset']}:{r['test']}"
        q_perm = fdr_perm[key]
        q_mw = fdr_mw[key]
        r["q_perm"] = q_perm
        r["q_mw"] = q_mw

        if r["diff"] > 0 and r["p_mw"] < 0.05 and r["p_perm"] < 0.05 and q_perm < 0.10:
            verdict = "CANDIDATE"
        elif r["diff"] < 0 and r["p_mw"] < 0.05 and r["p_perm"] < 0.05 and q_perm < 0.10:
            verdict = "INVERSE!"
        elif min(r["p_welch"], r["p_mw"], r["p_perm"]) < 0.05:
            verdict = "WEAK/FAIL_FDR"
        else:
            verdict = "NOISE"
        r["verdict"] = verdict
        by_test.setdefault(r["test"], []).append(r)

        up_s = f"{r['up_diff']:+.2f}%({r['p_up']:.2f})"
        vol_s = f"{r['vol_diff']:+.3f}%({r['p_vol']:.2f})"
        print(
            f"{r['asset']:<5} | {r['test']:<31} | {r['na']:>4d}/{r['nb']:<6d} | {r['diff']:>+7.4f}% | "
            f"{r['p_welch']:>7.4f} | {r['p_mw']:>7.4f} | {r['p_perm']:>7.4f} | {q_perm:>7.4f} | "
            f"{up_s:<14} | {vol_s:<14} | {verdict}"
        )

    print("=" * 144)
    print("  [CROSS-ASSET CONSISTENCY SUMMARY]")
    for tname, rows in by_test.items():
        all_pos = all(r["diff"] > 0 for r in rows)
        all_neg = all(r["diff"] < 0 for r in rows)
        cands = [r["asset"] for r in rows if r["verdict"] == "CANDIDATE"]
        if len(cands) == len(rows):
            status = "STRONG EDGE (All assets passed FDR & direction)"
        elif cands:
            status = f"SINGLE-ASSET ONLY ({','.join(cands)})"
        elif all_pos and all(r["p_perm"] < 0.10 for r in rows):
            status = "MILD POSITIVE CONSISTENCY (Below FDR threshold)"
        elif all_neg and all(r["p_perm"] < 0.10 for r in rows):
            status = "CONSISTENTLY INVERSE (Theory opposite)"
        else:
            status = "NOISE / INCONSISTENT"
        print(f"  - {tname:<32}: {status}")
    print("=" * 144)


if __name__ == "__main__":
    main()
