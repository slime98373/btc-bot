#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strategy_ablation_audit.py
5m Realistic High/Low Ablation Backtest:
  Compare TECH_ONLY (Control) vs LEGACY_V15 vs V2_QM_A / V2_QM_B / V2_QM_C.

Run:
  ~/btc_bot/venv/bin/python ~/btc_bot/strategy_ablation_audit.py --days 60 --assets BTC,ETH
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from daliuren_engine import cast_daily_tsmc_chart
from btc_strategy import ASSET_PROFILES, evaluate_btc_signal
from metaphysics_v2 import calc_true_qimen_v2, calc_pure_daliuren_2d_v2, get_huangji_astro_profile
from audit_stats import mann_whitney_u_test, welch_t_test

EXCHANGES = [("binance", 1000), ("bybit", 1000), ("gate", 1000), ("okx", 300)]
QM_PALACE_MAP = {"BTC": 9, "ETH": 3, "SOL": 9}


def fetch_5m_ohlcv(asset: str, days: int, refresh: bool = False) -> Tuple[str, List[List[float]]]:
    cache_path = os.path.join(SCRIPT_DIR, f"cache_ablation_{asset}_{days}d_5m.json")
    if (not refresh) and os.path.exists(cache_path):
        if (time.time() - os.path.getmtime(cache_path)) / 3600.0 < 24.0:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if len(cached.get("bars", [])) >= 1000:
                return cached["source"] + " (cached)", cached["bars"]

    import ccxt

    sym = f"{asset}/USDT"
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - days * 86400 * 1000
    step_ms = 300 * 1000
    target = days * 288

    for ex_id, limit in EXCHANGES:
        try:
            ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
            all_bars: List[List[float]] = []
            cursor = since_ms
            stalls = 0
            print(f"[FETCH] Downloading {days}d 5m {sym} from {ex_id}...", flush=True)
            while cursor < now_ms - step_ms and len(all_bars) < target + 200:
                batch = ex.fetch_ohlcv(sym, timeframe="5m", since=cursor, limit=limit)
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
            if len(bars) >= max(1000, int(target * 0.6)):
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"source": ex_id, "bars": bars}, f)
                return ex_id, bars
        except Exception as e:
            print(f"[WARN] {ex_id} 5m fetch failed: {e}", flush=True)
    raise RuntimeError(f"Failed to fetch 5m OHLCV for {asset}")


def compute_tech_features(closes: List[float], idx: int) -> Tuple[float, float, float, float]:
    curr_p = closes[idx]
    ma_macro = sum(closes[idx - 119:idx + 1]) / 120.0
    ma_prev = sum(closes[idx - 130:idx - 10]) / 120.0
    slope = (ma_macro - ma_prev) / ma_prev * 100.0
    mom_15m = (curr_p - closes[idx - 3]) / closes[idx - 3] * 100.0
    return curr_p, ma_macro, slope, mom_15m


def simulate_variant(
    variant: str,
    asset: str,
    bars: List[List[float]],
    closes: List[float],
    meta_cache: Dict[Tuple[int, int, int, int], Dict[str, Any]],
    round_trip_cost: float = 0.0010,
) -> Dict[str, Any]:
    prof = ASSET_PROFILES[asset]
    tp_pct, sl_pct = prof["tp"], prof["sl"]
    tz_tw = datetime.timezone(datetime.timedelta(hours=8))

    pos: Optional[Dict[str, Any]] = None
    trades_pnl: List[float] = []
    eq, peak, mdd = 1.0, 1.0, 0.0

    for i in range(135, len(bars)):
        ts, o, h, l, c, _ = bars[i]
        prev_ts = bars[i - 1][0]
        if int(ts) - int(prev_ts) != 300_000:
            # 遇資料缺口強制平倉重置，不跨缺口持倉
            if pos is not None:
                exit_p = closes[i - 1]
                raw = (exit_p - pos["ep"]) / pos["ep"] if pos["side"] == "LONG" else (pos["ep"] - exit_p) / pos["ep"]
                net = (raw - round_trip_cost) * pos["size"]
                trades_pnl.append(net * 100.0)
                eq *= (1.0 + net)
                peak = max(peak, eq)
                mdd = max(mdd, (peak - eq) / peak * 100.0)
                pos = None
            continue

        dt_tw = datetime.datetime.fromtimestamp(ts / 1000.0, tz=tz_tw).replace(tzinfo=None)
        raw_mins = dt_tw.minute if (dt_tw.hour % 2 == 1) else (60 + dt_tw.minute)
        slot_5m = (raw_mins // 5) * 5

        # 1. 嚴格盤中 High/Low 出場檢查（同根同時觸及 TP 與 SL 一律保守判 SL）
        if pos is not None:
            held_h = (ts - pos["entry_ts"]) / 3_600_000.0
            exit_p: Optional[float] = None
            if pos["side"] == "LONG":
                hit_sl = l <= pos["sl"]
                hit_tp = h >= pos["tp"]
                if hit_sl:
                    exit_p = min(o, pos["sl"])
                elif hit_tp:
                    exit_p = max(o, pos["tp"])
                elif held_h >= 4.0:
                    exit_p = c
            else:
                hit_sl = h >= pos["sl"]
                hit_tp = l <= pos["tp"]
                if hit_sl:
                    exit_p = max(o, pos["sl"])
                elif hit_tp:
                    exit_p = min(o, pos["tp"])
                elif held_h >= 4.0:
                    exit_p = c

            if exit_p is not None:
                raw = (exit_p - pos["ep"]) / pos["ep"] if pos["side"] == "LONG" else (pos["ep"] - exit_p) / pos["ep"]
                net = (raw - round_trip_cost) * pos["size"]
                trades_pnl.append(net * 100.0)
                eq *= (1.0 + net)
                peak = max(peak, eq)
                mdd = max(mdd, (peak - eq) / peak * 100.0)
                pos = None
                continue

            # 收盤後檢查是否啟動保本移動停損（避免單根 K 線偷看未來）
            if not pos["be_armed"]:
                raw_close = (c - pos["ep"]) / pos["ep"] if pos["side"] == "LONG" else (pos["ep"] - c) / pos["ep"]
                if raw_close >= pos["be_trig"]:
                    pos["be_armed"] = True
                    pos["sl"] = pos["ep"] * (1.0010 if pos["side"] == "LONG" else 0.9990)
            continue

        # 2. 進場評估（僅在指定時間點觸發）
        curr_p, ma_macro, slope, mom_15m = compute_tech_features(closes, i)
        sig = "HOLD"
        size = 0.50
        be_trig = 0.0100

        if variant == "TECH_ONLY":
            if slot_5m not in (15, 55, 95):
                continue
            if curr_p >= ma_macro * 0.996 and mom_15m >= -0.05:
                sig = "LONG"
            elif slope < 0.25 and curr_p < ma_macro * 1.002 and mom_15m <= 0.05:
                sig = "SHORT"

        elif variant == "LEGACY_V15":
            res = evaluate_btc_signal(closes[i - 134:i + 1], dt_tw=dt_tw, force_eval=False, asset_code=asset)
            if res["signal"] in ("LONG", "SHORT"):
                sig = res["signal"]
                size = res["recommended_size_pct"]
                be_trig = res["be_trigger_pct"]

        else:
            if slot_5m not in (15, 55, 95):
                continue
            shichen_hour = dt_tw.hour if (dt_tw.hour % 2 == 1) else (dt_tw.hour - 1) % 24
            sc_key = (dt_tw.year, dt_tw.month, dt_tw.day, shichen_hour)
            mc = meta_cache[sc_key]
            spec, qm, hj = mc["spec"], mc["qm"], mc["hj"]
            quad = spec["quadrant"]

            if variant == "V2_QM_A":
                q_obj = qm["scheme_a"]
                qm_long_ok = q_obj["qm_regime"] in ("QM_FAVORABLE_BOOST", "QM_FAVORABLE")
                qm_short_ok = q_obj["qm_regime"] == "QM_HOSTILE_BEAR"
                tight_be = q_obj["qm_regime"] in ("QM_MENPO_OR_FIRE", "QM_HOSTILE_BEAR")
            elif variant == "V2_QM_B":
                q_obj = qm["scheme_b"]
                qm_long_ok = q_obj["qm_regime"] in ("QM_FAVORABLE_BOOST", "QM_FAVORABLE")
                qm_short_ok = q_obj["qm_regime"] == "QM_HOSTILE_BEAR"
                tight_be = q_obj["qm_regime"] in ("QM_MENPO_OR_FIRE", "QM_HOSTILE_BEAR")
            else:  # V2_QM_C
                q_obj = qm["scheme_c"]
                qm_long_ok = q_obj["qm_regime"] in ("HG_FAVORABLE_BOOST", "HG_FAVORABLE")
                qm_short_ok = q_obj["qm_regime"] == "HG_HOSTILE"
                tight_be = q_obj["qm_regime"] in ("HG_WEAK_DRAIN", "HG_HOSTILE")

            tech_long = (curr_p >= ma_macro * 0.996) and (mom_15m >= -0.05)
            tech_short = (slope < 0.25) and (curr_p < ma_macro * 1.002) and (mom_15m <= 0.05)

            if tech_long and (quad in ("Q1_CLEAR_RUNWAY", "Q3_MILD_DRIFT")) and qm_long_ok and (not qm["wubuyushi"]):
                sig = "LONG"
                size = min(0.75, max(0.40, 0.50 * hj["long_size_mult"] * (1.10 if quad == "Q1_CLEAR_RUNWAY" else 1.0)))
                if tight_be:
                    be_trig = round(tp_pct * 0.45, 4)
            elif tech_short and (quad in ("Q4_TRAP_QUAGMIRE", "Q2_FRICTION_RUSH")) and qm_short_ok:
                sig = "SHORT"
                size = min(0.75, max(0.40, 0.50 * hj["short_size_mult"] * (1.10 if quad == "Q4_TRAP_QUAGMIRE" else 1.0)))

        if sig in ("LONG", "SHORT"):
            pos = {
                "side": sig,
                "ep": c,
                "tp": c * (1.0 + tp_pct) if sig == "LONG" else c * (1.0 - tp_pct),
                "sl": c * (1.0 - sl_pct) if sig == "LONG" else c * (1.0 + sl_pct),
                "size": size,
                "be_trig": be_trig,
                "be_armed": False,
                "entry_ts": ts,
            }

    n_tr = len(trades_pnl)
    wins = [x for x in trades_pnl if x > 0]
    losses = [x for x in trades_pnl if x <= 0]
    wr = (len(wins) / n_tr * 100.0) if n_tr else 0.0
    avg_tr = (sum(trades_pnl) / n_tr) if n_tr else 0.0
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) < 0 else (99.0 if wins else 0.0)
    return {
        "variant": variant,
        "trades": n_tr,
        "wr": wr,
        "tot_ret": (eq - 1.0) * 100.0,
        "avg_tr": avg_tr,
        "pf": pf,
        "mdd": mdd,
        "pnl_list": trades_pnl,
    }


def main():
    parser = argparse.ArgumentParser(description="5m Strategy Ablation Audit (Tech Control vs Metaphysics v2)")
    parser.add_argument("--days", type=int, default=60, help="Days of 5m candles (default: 60)")
    parser.add_argument("--assets", type=str, default="BTC,ETH")
    parser.add_argument("--cost-bps", type=float, default=10.0, help="Round-trip fee+slippage in bps (default: 10 = 0.10%%)")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip().upper() in ASSET_PROFILES]
    variants = ["TECH_ONLY", "LEGACY_V15", "V2_QM_A", "V2_QM_B", "V2_QM_C"]
    tz_tw = datetime.timezone(datetime.timedelta(hours=8))

    for asset in assets:
        src, bars = fetch_5m_ohlcv(asset, args.days, refresh=args.refresh)
        closes = [float(b[4]) for b in bars]
        prof = ASSET_PROFILES[asset]

        # 預先快取每個時辰的玄學盤面（避免 5m 迴圈重複排盤）
        meta_cache: Dict[Tuple[int, int, int, int], Dict[str, Any]] = {}
        for b in bars[135:]:
            dt_tw = datetime.datetime.fromtimestamp(b[0] / 1000.0, tz=tz_tw).replace(tzinfo=None)
            shichen_hour = dt_tw.hour if (dt_tw.hour % 2 == 1) else (dt_tw.hour - 1) % 24
            sc_key = (dt_tw.year, dt_tw.month, dt_tw.day, shichen_hour)
            if sc_key not in meta_cache:
                dt_cast = datetime.datetime(dt_tw.year, dt_tw.month, dt_tw.day, shichen_hour, 0)
                chart = cast_daily_tsmc_chart(dt_cast, include_intraday=False)
                meta_cache[sc_key] = {
                    "spec": calc_pure_daliuren_2d_v2(chart, 0, el=prof["el"], palace=prof["palace"], tomb=prof["tomb"]),
                    "qm": calc_true_qimen_v2(chart, asset_qm_palace=QM_PALACE_MAP[asset]),
                    "hj": get_huangji_astro_profile(dt_cast, sun_lon=chart.pillars["sun_longitude"]),
                }

        bh = (closes[-1] / closes[135] - 1.0) * 100.0
        print("\n" + "=" * 108)
        print(f"  [ABLATION AUDIT: {asset} | {args.days}D 5m ({src}) | B&H: {bh:+.2f}% | Cost: {args.cost_bps:.0f}bps | Conservative High/Low]")
        print("=" * 108)
        print(f"  {'Variant':<14} | {'Trades':>6} | {'WinRate':>7} | {'TotRet%':>8} | {'AvgTrd%':>8} | {'PF':>5} | {'MaxDD%':>7} | {'vs TECH_ONLY (MW-U p)'}")
        print("  " + "-" * 102)

        res_list = [simulate_variant(v, asset, bars, closes, meta_cache, args.cost_bps / 10000.0) for v in variants]
        ctrl = res_list[0]
        for r in res_list:
            if r["variant"] == "TECH_ONLY":
                cmp_str = "(Control Baseline)"
            else:
                diff, _, _ = welch_t_test(r["pnl_list"], ctrl["pnl_list"], min_n=5)
                p_mw = mann_whitney_u_test(r["pnl_list"], ctrl["pnl_list"], min_n=5)
                cmp_str = f"diff={diff:+.3f}% (p={p_mw:.4f})"
            print(
                f"  {r['variant']:<14} | {r['trades']:>6d} | {r['wr']:>6.1f}% | {r['tot_ret']:>+7.2f}% | "
                f"{r['avg_tr']:>+7.3f}% | {r['pf']:>5.2f} | {r['mdd']:>6.2f}% | {cmp_str}"
            )
        print("=" * 108)


if __name__ == "__main__":
    main()
