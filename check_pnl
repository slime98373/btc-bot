#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Asset v15.1 PnL & Risk Dashboard (check_pnl.py)
Default allocation: BTC 60% ($6,000) / ETH 40% ($4,000) = $10,000
Override via env vars (BTC_CAPITAL_USD, ETH_CAPITAL_USD) or CLI (--btc-cap 600 --eth-cap 400).
"""
import json
import os
import sys


def _get_arg_float(flag: str, env_key: str, default_val: float) -> float:
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            try:
                return float(sys.argv[i + 1])
            except ValueError:
                pass
    try:
        return float(os.environ.get(env_key, str(default_val)))
    except ValueError:
        return default_val


BTC_CAP = _get_arg_float("--btc-cap", "BTC_CAPITAL_USD", 6000.0)
ETH_CAP = _get_arg_float("--eth-cap", "ETH_CAPITAL_USD", 4000.0)
TOTAL_CAP = BTC_CAP + ETH_CAP
BTC_W = (BTC_CAP / TOTAL_CAP) if TOTAL_CAP > 0 else 0.60
ETH_W = (ETH_CAP / TOTAL_CAP) if TOTAL_CAP > 0 else 0.40

ASSETS = [
    ("BTC", "BTC (Fire / Wu-Palace)",  os.path.expanduser("~/btc_bot/btc_bot_state.json"), BTC_CAP, BTC_W),
    ("ETH", "ETH (Wood / Mao-Palace)", os.path.expanduser("~/btc_bot/eth_bot_state.json"), ETH_CAP, ETH_W),
]


def calc_stats(hist, init_cap: float, lev: int = 1):
    eq, peak, mdd = init_cap, init_cap, 0.0
    for t in hist:
        r = (float(t.get("pnl_pct", 0.0)) / 100.0) * lev
        eq = max(0.0, eq * (1.0 + r))
        peak = max(peak, eq)
        if peak > 0:
            mdd = max(mdd, (peak - eq) / peak * 100.0)
    ret_pct = ((eq / init_cap) - 1.0) * 100.0 if init_cap > 0 else 0.0
    return eq, ret_pct, mdd


print("=" * 82)
print(f"  [v15.1 Tri-System Multi-Asset Dashboard | Weight: BTC {BTC_W*100:.0f}% / ETH {ETH_W*100:.0f}%]")
print(f"  Allocated Capital: BTC ${BTC_CAP:,.2f} + ETH ${ETH_CAP:,.2f} = ${TOTAL_CAP:,.2f} USDT")
print("=" * 82)

combined_eq = {1: 0.0, 2: 0.0, 3: 0.0}
eq5050 = {1: 0.0, 2: 0.0, 3: 0.0}
active_count = 0
all_recent = []

for code, title, path, cap, w in ASSETS:
    if not os.path.exists(path):
        print(f"\n>>> {title} (Cap: ${cap:,.2f} | {w*100:.0f}%): No state file yet (waiting for first run)")
        continue
    active_count += 1
    with open(path, "r", encoding="utf-8") as f:
        s = json.load(f)
    hist = s.get("trade_history", [])
    wins = sum(1 for t in hist if float(t.get("pnl_pct", 0.0)) > 0)
    wr = (wins / len(hist) * 100.0) if hist else 0.0
    all_recent.extend(hist)

    print(
        f"\n>>> {title} [Cap: ${cap:,.2f} ({w*100:.0f}%)] | Trades: {len(hist)} | "
        f"WinRate: {wr:.1f}% ({wins}W/{len(hist)-wins}L) | Today 1x: {s.get('daily_pnl_pct', 0):+.3f}%"
    )
    for lev in (1, 2, 3):
        eq, ret, mdd = calc_stats(hist, cap, lev)
        combined_eq[lev] += eq
        eq_half, _, _ = calc_stats(hist, TOTAL_CAP * 0.5, lev)
        eq5050[lev] += eq_half
        print(f"    {lev}x Leverage : ${eq:>10,.2f} ({ret:>+7.2f}%) | MaxDD: {mdd:>5.2f}%")

    if s.get("position"):
        print(
            f"    Active Pos  : {s['position']} ({int(s.get('pos_pct', 0.5)*100)}%) @ "
            f"${s['entry_price']:,.2f} | TP=${s['tp_price']:,.2f} / SL=${s['sl_price']:,.2f}"
        )
    else:
        print("    Active Pos  : NONE (100% USDT Cash)")

    for t in hist[-3:]:
        print(
            f"      - [{t['time_utc'][:16]}] {t['side']:<5} "
            f"${t['entry']:,.1f}->${t['exit']:,.1f} | 1x:{t['pnl_pct']:+.2f}% ({t['reason']})"
        )

if active_count == 2 and TOTAL_CAP > 0:
    print("\n" + "-" * 82)
    print(f"  [Combined Portfolio ({BTC_W*100:.0f}% BTC / {ETH_W*100:.0f}% ETH) | Initial: ${TOTAL_CAP:,.2f}]")
    for lev in (1, 2, 3):
        ret = (combined_eq[lev] / TOTAL_CAP - 1.0) * 100.0
        ret50 = (eq5050[lev] / TOTAL_CAP - 1.0) * 100.0
        print(f"    Combined {lev}x : ${combined_eq[lev]:>10,.2f} ({ret:>+7.2f}%)  | 50/50 Ref: {ret50:>+7.2f}%")

    # Live Health Check (Last 30 combined trades)
    all_recent.sort(key=lambda x: x.get("time_utc", ""))
    last30 = all_recent[-30:]
    if len(last30) >= 10:
        w30 = sum(1 for t in last30 if float(t.get("pnl_pct", 0.0)) > 0)
        wr30 = w30 / len(last30) * 100.0
        status = "OK" if wr30 >= 50.0 else "ALERT: WR < 50% (Consider 1x / Review)"
        print(f"    HealthCheck : Last {len(last30)} Trades WR = {wr30:.1f}% ({w30}W/{len(last30)-w30}L) [{status}]")

print("=" * 82)
