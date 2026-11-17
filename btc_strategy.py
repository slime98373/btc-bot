#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比特幣 (BTC/USD) 大六壬 v12.0「盤面動態應期（每時辰 0～6 次・動態分鐘觸發）」策略模組 (btc_strategy.py)
====================================================================================================
核心機制：
  1. 依當下時辰大六壬四課三傳、空亡、驛馬、天地盤反吟與奇門局，自動排定該時辰（0–119 分鐘）之：
     - 休囚閉塞課 (DORMANT_0)：0 次進場評估（全時辰觀望，避開洗盤）
     - 緩發順行課 (SLOW_1_2) ：1～2 次精準評估（僅在實支應期分鐘啟動）
     - 常規三傳課 (DYNAMIC_3)：3 次動態應期分鐘評估（依傳支天盤位移＋太玄數定分鐘，避開整點插針）
     - 驛馬交戰課 (INTENSE_4_6)：4～6 次高頻密集評估（納入四課動爻與時支六沖分刻，捕捉急拉與V轉）
  2. 每 5 分鐘巡檢一次：
     - 持倉中：每 5 分鐘即時監控停利(+1.5%)、停損(-0.9%)、末傳空亡提前鎖利(>=+0.35%)、中傳空亡緊縮停損(<=-0.55%)
     - 空手中：僅在時辰內命中「應期分鐘 (eval_minutes)」時才啟動開倉評估！
"""

import datetime
from typing import Dict, Any, List
from daliuren_engine import cast_daily_tsmc_chart, STEMS, BRANCHES, STEM_WUXING, BRANCH_WUXING, wuxing_generates, wuxing_controls

TAIXUAN_NUM = {
    "子": 9, "午": 9, "丑": 8, "未": 8, "寅": 7, "申": 7,
    "卯": 6, "酉": 6, "辰": 5, "戌": 5, "巳": 4, "亥": 4,
}

SIX_CLASH = {
    "子": "午", "午": "子", "丑": "未", "未": "丑", "寅": "申", "申": "寅",
    "卯": "酉", "酉": "卯", "辰": "戌", "戌": "辰", "巳": "亥", "亥": "巳",
}


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


def compute_dynamic_shichen_schedule(chart, qimen: Dict[str, Any], el_score: float) -> Dict[str, Any]:
    """
    計算當前時辰（0–119 分鐘）之動態應期評估分鐘列表 (對齊 5 分鐘刻度：0, 5, 10, ..., 115)
    """
    tt = chart.three_transmissions
    sike = chart.four_lessons
    hour_b = chart.pillars["hour_branch"]
    hour_idx = BRANCHES.index(hour_b)

    lqs = [t["liuqin"] for t in tt]
    gens = [t["general"] for t in tt]
    kws = [t["kongwang"] == "空亡" for t in tt]
    branches = [t["branch"] for t in tt]

    void_count = sum(1 for k in kws if k)
    has_horse = any(b in ("寅", "申", "巳", "亥") for b in branches)
    is_fanyin = (SIX_CLASH.get(chart.heaven_plate[hour_b]) == hour_b)
    fierce_generals = sum(1 for g in gens if g in ("白虎", "螣蛇", "玄武"))
    active_wealth_ghost = ("妻財" in lqs and "官鬼" in lqs) or (abs(el_score) >= 8.0 and abs(qimen["q_score"]) >= 20)

    if void_count >= 2 or (kws[0] and qimen["door"] in ("杜門", "傷門") and abs(el_score) <= 4.0):
        return {
            "mode_en": "DORMANT_0 (0 checks - Chop Filter)",
            "eval_count": 0,
            "eval_minutes": [],
            "slot_meta": {},
        }

    base_minutes = []
    slot_meta = {}
    for i, t in enumerate(tt):
        if kws[i]:
            continue
        b = t["branch"]
        b_idx = BRANCHES.index(b)
        offset_branch = (b_idx - hour_idx) % 12
        tx = TAIXUAN_NUM[b]
        within_40 = ((offset_branch * 3 + tx) % 7) * 5 + 5
        minute_mark = min(115, i * 40 + within_40)
        base_minutes.append(minute_mark)
        slot_meta[minute_mark] = {
            "source": f"{['1st','2nd','3rd'][i]}({b})",
            "liuqin": t["liuqin"],
            "general": t["general"],
            "kongwang": False,
            "is_main_chuan": True,
        }

    if is_fanyin or (has_horse and active_wealth_ghost) or (fierce_generals >= 2 and abs(el_score) >= 6.0):
        extra_branches = [sike[0]["top"], sike[2]["top"], SIX_CLASH[hour_b]]
        day_wx = STEM_WUXING[chart.pillars["day_stem"]]
        for eb in extra_branches:
            eb_idx = BRANCHES.index(eb)
            m_mark = min(115, eb_idx * 10)
            if m_mark not in slot_meta:
                eb_wx = BRANCH_WUXING[eb]
                if eb_wx == day_wx:
                    eb_lq = "兄弟"
                elif wuxing_generates(day_wx, eb_wx):
                    eb_lq = "子孫"
                elif wuxing_generates(eb_wx, day_wx):
                    eb_lq = "父母"
                elif wuxing_controls(day_wx, eb_wx):
                    eb_lq = "妻財"
                else:
                    eb_lq = "官鬼"
                eb_gen = chart.generals_plate[eb]
                eb_kw = eb in chart.pillars["kongwang"]
                if not eb_kw:
                    base_minutes.append(m_mark)
                    slot_meta[m_mark] = {
                        "source": f"SiKe/Clash({eb})",
                        "liuqin": eb_lq,
                        "general": eb_gen,
                        "kongwang": False,
                        "is_main_chuan": False,
                    }
        eval_mins = sorted(set(base_minutes))[:6]
        return {
            "mode_en": f"INTENSE_{len(eval_mins)} ({len(eval_mins)} checks - High Volatility)",
            "eval_count": len(eval_mins),
            "eval_minutes": eval_mins,
            "slot_meta": slot_meta,
        }

    if len(base_minutes) <= 2 or (qimen["deity"] in ("九地", "太陰") and not has_horse):
        eval_mins = sorted(set(base_minutes))[:2]
        return {
            "mode_en": f"SLOW_{len(eval_mins)} ({len(eval_mins)} checks - Steady)",
            "eval_count": len(eval_mins),
            "eval_minutes": eval_mins,
            "slot_meta": slot_meta,
        }

    eval_mins = sorted(set(base_minutes))
    return {
        "mode_en": f"DYNAMIC_{len(eval_mins)} ({len(eval_mins)} checks - Standard YingQi)",
        "eval_count": len(eval_mins),
        "eval_minutes": eval_mins,
        "slot_meta": slot_meta,
    }


def evaluate_btc_signal(closes_5m: List[float], dt_tw: datetime.datetime = None, force_eval: bool = False) -> Dict[str, Any]:
    """
    輸入 5 分鐘 K 線序列（建議至少 480 根 = 20 個時辰），回傳 v12.0 動態應期排程與當下訊號
    """
    if dt_tw is None:
        dt_tw = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)

    curr_p = closes_5m[-1]
    ma_len = min(480, len(closes_5m))
    ma20_sc = sum(closes_5m[-ma_len:]) / float(ma_len)
    ma_prev = sum(closes_5m[-ma_len - 20:-20]) / float(ma_len) if len(closes_5m) >= (ma_len + 20) else ma20_sc
    slope = (ma20_sc - ma_prev) / ma_prev * 100.0
    mom_15m = (curr_p - closes_5m[-4]) / closes_5m[-4] * 100.0 if len(closes_5m) >= 4 else 0.0

    gains, losses = [], []
    for j in range(max(1, len(closes_5m) - 12), len(closes_5m)):
        d = closes_5m[j] - closes_5m[j - 1]
        if d > 0:
            gains.append(d)
        else:
            losses.append(-d)
    rsi = 100.0 if sum(losses) == 0 else 100.0 - (100.0 / (1.0 + (sum(gains) / 12.0) / (sum(losses) / 12.0)))

    chart = cast_daily_tsmc_chart(dt_tw)
    q = calc_shichen_qimen(chart)
    res_el = calc_btc_fire_resonance(chart)
    el_score = res_el["el_score"]
    sched = compute_dynamic_shichen_schedule(chart, q, el_score)

    raw_mins = dt_tw.minute if (dt_tw.hour % 2 == 1) else (60 + dt_tw.minute)
    slot_5m = (raw_mins // 5) * 5
    phase_idx = min(2, raw_mins // 40)

    tt = chart.three_transmissions
    lqs = [t["liuqin"] for t in tt]
    gens = [t["general"] for t in tt]
    kws = [t["kongwang"] == "空亡" for t in tt]

    is_eval_minute = (slot_5m in sched["eval_minutes"]) or force_eval
    active_lq = lqs[phase_idx]
    active_gen = gens[phase_idx]
    active_kw = kws[phase_idx]
    trigger_source = f"{['1st','2nd','3rd'][phase_idx]}({tt[phase_idx]['branch']})"

    if slot_5m in sched["slot_meta"]:
        meta = sched["slot_meta"][slot_5m]
        trigger_source = meta["source"]
        if meta.get("is_main_chuan", True):
            active_lq = meta["liuqin"]
            active_gen = meta["general"]
            active_kw = meta["kongwang"]
        elif active_kw and not kws[0]:
            active_lq, active_gen, active_kw = lqs[0], gens[0], kws[0]

    bull_trap = (active_lq == "妻財" and active_kw) or (active_lq == "父母" and active_gen in ("螣蛇", "玄武"))
    long_sig = is_eval_minute and (not bull_trap) and (not q["wubuyushi"]) and q["good_door"] and (q["q_score"] >= 15) and (el_score >= -3.0) and (
        active_lq in ("妻財", "子孫", "父母") and not active_kw
    ) and (curr_p >= ma20_sc * 0.996) and (mom_15m >= -0.05)

    short_sig = is_eval_minute and (not long_sig) and (slope < 0.25) and (el_score <= 5.0) and (
        (q["door"] in ("死門", "驚門") or q["wubuyushi"]) and (active_lq in ("官鬼", "兄弟") or active_gen in ("白虎", "玄武"))
    ) and (curr_p < ma20_sc * 1.002) and (mom_15m <= 0.05)

    if phase_idx == 2 and active_kw:
        long_sig = False
        short_sig = False

    signal = "LONG" if long_sig else ("SHORT" if short_sig else "HOLD")
    tp_pct = 0.015
    sl_pct = 0.009

    if signal == "LONG":
        tp_price = round(curr_p * (1.0 + tp_pct), 2)
        sl_price = round(curr_p * (1.0 - sl_pct), 2)
        rec_size = 0.55 if (sched["eval_count"] >= 4) else 0.50
    elif signal == "SHORT":
        tp_price = round(curr_p * (1.0 - tp_pct), 2)
        sl_price = round(curr_p * (1.0 + sl_pct), 2)
        rec_size = 0.55 if (sched["eval_count"] >= 4) else 0.50
    else:
        tp_price, sl_price, rec_size = 0.0, 0.0, 0.0

    next_mins = [m for m in sched["eval_minutes"] if m > slot_5m]
    scale_long_ok = is_eval_minute and (active_lq in ("妻財", "子孫", "父母") and not active_kw)
    scale_short_ok = is_eval_minute and (active_lq in ("官鬼", "兄弟") and not active_kw)

    return {
        "signal": signal,
        "is_eval_minute": is_eval_minute,
        "raw_mins": raw_mins,
        "slot_5m": slot_5m,
        "sched_mode_en": sched["mode_en"],
        "eval_minutes": sched["eval_minutes"],
        "next_minutes": next_mins,
        "trigger_source": trigger_source,
        "shichen": f"{chart.pillars['hour_ganzhi']}（{q['hour_branch']}時）",
        "phase_idx": phase_idx,
        "active_chuan": f"{trigger_source}:{active_lq}/{active_gen}/{'Void' if active_kw else 'Solid'}",
        "recommended_size_pct": rec_size,
        "scale_long_ok": scale_long_ok,
        "scale_short_ok": scale_short_ok,
        "kw_lock_profit": (phase_idx == 2 and kws[2]),
        "tight_stop_middle": (phase_idx == 1 and kws[1]),
        "price": round(curr_p, 2),
        "ma20": round(ma20_sc, 2),
        "mom_15m_pct": round(mom_15m, 3),
        "rsi5": round(rsi, 1),
        "tp_price": tp_price,
        "sl_price": sl_price,
        "el_score": el_score,
        "el_note": res_el["el_note"],
        "qimen": f"{q['door']}・{q['star']}・{q['deity']}（評分 {q['q_score']:+d}{'・五不遇時' if q['wubuyushi'] else ''}）",
        "sanchuan": f"初傳{tt[0]['branch']}({lqs[0]}) → 中傳{tt[1]['branch']}({lqs[1]}) → 末傳{tt[2]['branch']}({lqs[2]})",
    }
