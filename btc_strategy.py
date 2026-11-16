#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比特幣 (BTC/USD) 專屬大六壬十二時辰 × 奇門遁甲 × 離火本命共振策略模組 (btc_strategy.py)
專為 24/7 永續合約／現貨自動化交易設計：
  - 標的五行歸類：BTC 屬【火】（離火算力・數位火金），本命地盤宮位在【午宮】
  - 每 2 小時換時辰（子丑寅卯辰巳午未申酉戌亥）即時起盤
  - 訊號輸出：LONG（做多）、SHORT（做空）、HOLD（觀望）
"""

import datetime
from typing import Dict, Any, List
from daliuren_engine import cast_daily_tsmc_chart, STEMS, BRANCHES, BRANCH_WUXING, wuxing_generates, wuxing_controls


def calc_shichen_qimen(chart) -> Dict[str, Any]:
    p = chart.pillars
    day_idx = STEMS.index(p["day_stem"])
    hour_gan_idx = STEMS.index(p["hour_stem"])
    hour_zhi_idx = BRANCHES.index(p["hour_branch"])
    wubuyushi = ((hour_gan_idx - day_idx) % 10 == 6) and ((hour_gan_idx % 2) == (day_idx % 2))
    doors = ["休門", "生門", "傷門", "杜門", "景門", "死門", "驚門", "開門"]
    stars = ["天蓬", "天任", "天沖", "天輔", "天英", "天芮", "天柱", "天心"]
    deities = ["值符", "螣蛇", "太陰", "六合", "白虎", "玄武", "九地", "九天"]
    door_idx = (day_idx + hour_zhi_idx + BRANCHES.index(p["yuejiang"])) % 8
    star_idx = (day_idx * 3 + hour_zhi_idx) % 8
    deity_idx = (hour_gan_idx + BRANCHES.index(chart.three_transmissions[0]["branch"])) % 8
    door, star, deity = doors[door_idx], stars[star_idx], deities[deity_idx]
    q_score = 0
    if door in ("生門", "開門", "休門"):
        q_score += 15
    elif door in ("死門", "驚門", "傷門"):
        q_score -= 15
    if star in ("天任", "天輔", "天心"):
        q_score += 10
    elif star in ("天蓬", "天芮", "天柱"):
        q_score -= 10
    if deity in ("值符", "九天", "太陰", "六合"):
        q_score += 8
    elif deity in ("白虎", "玄武", "螣蛇"):
        q_score -= 10
    if wubuyushi:
        q_score -= 25
    return {
        "hour_gan": p["hour_stem"],
        "hour_branch": p["hour_branch"],
        "wubuyushi": wubuyushi,
        "door": door,
        "star": star,
        "deity": deity,
        "q_score": q_score,
        "good_door": door in ("生門", "開門", "休門"),
    }


def calc_btc_fire_resonance(chart) -> Dict[str, Any]:
    """計算當前時辰盤面對比特幣【離火本命・午宮】的專屬五行共振分數"""
    el, palace = "火", "午"
    m_wx = BRANCH_WUXING[chart.pillars["month_branch"]]
    score = 0.0
    notes = []

    if m_wx == el or wuxing_generates(m_wx, el):
        score += 8.0
        notes.append(f"月令{chart.pillars['month_branch']}({m_wx})生旺離火(+8)")
    elif wuxing_controls(m_wx, el):
        score -= 8.0
        notes.append(f"月令{chart.pillars['month_branch']}({m_wx})水克離火(-8)")
    else:
        notes.append(f"月令{chart.pillars['month_branch']}({m_wx})平性(0)")

    weights = [0.5, 0.3, 0.2]
    for i, t in enumerate(chart.three_transmissions):
        t_wx = t["wuxing"]
        mult = 0.4 if (t["kongwang"] == "空亡") else 1.0
        if t_wx == el or wuxing_generates(t_wx, el):
            pts = round(12.0 * weights[i] * mult, 1)
            score += pts
            notes.append(f"{t['branch']}({t_wx})生火+{pts}")
        elif wuxing_controls(t_wx, el):
            pts = round(12.0 * weights[i] * mult, 1)
            score -= pts
            notes.append(f"{t['branch']}({t_wx})克火-{pts}")

    top_b = chart.heaven_plate[palace]
    top_gen = chart.generals_plate[top_b]
    is_kw = top_b in chart.pillars["kongwang"]
    if top_gen in ("青龍", "貴人", "六合", "太常", "太陰") and not is_kw:
        score += 6.0
        notes.append(f"午宮{top_b}乘{top_gen}(+6)")
    elif top_gen in ("白虎", "螣蛇", "玄武", "天空") or is_kw:
        score -= 6.0
        notes.append(f"午宮{top_b}乘{top_gen}{'空亡' if is_kw else ''}(-6)")

    return {"el_score": round(score, 1), "el_note": "｜".join(notes)}


def evaluate_btc_signal(closes_2h: List[float], dt_tw: datetime.datetime = None) -> Dict[str, Any]:
    """輸入至少 25 根 2H 收盤價，回傳當前時辰 BTC 交易訊號 (LONG / SHORT / HOLD)"""
    if dt_tw is None:
        dt_tw = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)

    curr_p = closes_2h[-1]
    ma20 = sum(closes_2h[-20:]) / 20.0
    ma20_prev = sum(closes_2h[-25:-5]) / 20.0 if len(closes_2h) >= 25 else ma20
    slope = (ma20 - ma20_prev) / ma20_prev * 100.0

    gains, losses = [], []
    for j in range(len(closes_2h) - 5, len(closes_2h)):
        d = closes_2h[j] - closes_2h[j - 1]
        if d > 0:
            gains.append(d)
        else:
            losses.append(-d)
    rsi5 = 100.0 if sum(losses) == 0 else 100.0 - (100.0 / (1.0 + (sum(gains) / 5.0) / (sum(losses) / 5.0)))

    chart = cast_daily_tsmc_chart(dt_tw)
    q = calc_shichen_qimen(chart)
    res_el = calc_btc_fire_resonance(chart)
    el_score = res_el["el_score"]

    tt = chart.three_transmissions
    lqs = [t["liuqin"] for t in tt]
    gens = [t["general"] for t in tt]
    kws = [t["kongwang"] == "空亡" for t in tt]
    wealth_solid = sum(1 for k in range(3) if lqs[k] == "妻財" and not kws[k])
    bull_trap = (lqs[0] == "妻財" and kws[0]) or (lqs[0] == "父母" and gens[0] in ("螣蛇", "玄武"))

    long_sig = (not bull_trap) and (not q["wubuyushi"]) and q["good_door"] and (q["q_score"] >= 15) and (el_score >= -3.0) and (
        (lqs[0] in ("妻財", "子孫", "父母") and not kws[0]) or wealth_solid >= 2
    ) and (curr_p >= ma20 * 0.996 or rsi5 <= 30.0)

    short_sig = (not long_sig) and (slope < 0.25) and (el_score <= 5.0) and (
        (q["door"] in ("死門", "驚門") or q["wubuyushi"]) and (lqs[0] in ("官鬼", "兄弟") or lqs[2] in ("兄弟", "官鬼"))
    ) and (curr_p < ma20 * 1.002) and (rsi5 >= 28.0)

    signal = "LONG" if long_sig else ("SHORT" if short_sig else "HOLD")
    tp_pct = 0.016   # +1.6% 停利
    sl_pct = 0.010   # -1.0% 停損

    if signal == "LONG":
        tp_price = round(curr_p * (1.0 + tp_pct), 2)
        sl_price = round(curr_p * (1.0 - sl_pct), 2)
    elif signal == "SHORT":
        tp_price = round(curr_p * (1.0 - tp_pct), 2)
        sl_price = round(curr_p * (1.0 + sl_pct), 2)
    else:
        tp_price, sl_price = 0.0, 0.0

    return {
        "signal": signal,
        "shichen": f"{chart.pillars['hour_ganzhi']}（{q['hour_branch']}時）",
        "price": round(curr_p, 2),
        "ma20": round(ma20, 2),
        "ma20_slope_pct": round(slope, 3),
        "rsi5": round(rsi5, 1),
        "tp_price": tp_price,
        "sl_price": sl_price,
        "el_score": el_score,
        "el_note": res_el["el_note"],
        "qimen": f"{q['door']}・{q['star']}・{q['deity']}（評分 {q['q_score']:+d}{'・五不遇時' if q['wubuyushi'] else ''}）",
        "sanchuan": f"初傳{tt[0]['branch']}({lqs[0]}) → 中傳{tt[1]['branch']}({lqs[1]}) → 末傳{tt[2]['branch']}({lqs[2]})",
    }
