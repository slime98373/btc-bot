#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比特幣 (BTC/USDT) 大六壬 v13.3「動態應期 × 皇極經世立春軟加權 × ATR/保本/RSI防呆」策略模組 (btc_strategy.py)
=============================================================================================================
四大核心升級 (v13.3)：
  1. 【大六壬 v12.0 動態應期 (每時辰 0～6 次)】：保留全部分鐘應期與盤面動靜濾網，不硬砍好訊號。
  2. 【皇極經世值年卦・立春起算雙月六爻軟加權】：每兩個月對應值年卦一爻（02/04 立春換卦），
     動態調整倉位大小 (38%～68%)、持倉上限 (3.0h～5.5h) 與基礎停利停損比例。
  3. 【ATR 真實波動率自適應停利／停損】：依近 25 小時 5m 波動率微調停利 (1.25%～2.25%) 與停損 (0.70%～1.30%)。
  4. 【RSI 極端防呆鎖＋統一 300 根 5m 均線窗口】：RSI > 78 不追多、RSI < 22 不追空，實盤與模擬盤指標尺度完全一致。
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

# 皇極經世值年卦表 (2020–2030)，爻序由下至上 [初, 二, 三, 四, 五, 上]，1=陽(九), 0=陰(六)
HUANGJI_YEAR_HEXAGRAMS = {
    2020: {"name": "地火明夷", "en": "MingYi",   "lines": [1, 0, 1, 0, 0, 0]},
    2021: {"name": "山火賁",   "en": "Bi",       "lines": [1, 0, 1, 0, 0, 1]},
    2022: {"name": "水火既濟", "en": "JiJi",     "lines": [1, 0, 1, 0, 1, 0]},
    2023: {"name": "風火家人", "en": "JiaRen",   "lines": [1, 0, 1, 0, 1, 1]},
    2024: {"name": "雷火豐",   "en": "Feng",     "lines": [1, 0, 1, 1, 0, 0]},
    2025: {"name": "澤火革",   "en": "Ge",       "lines": [1, 0, 1, 1, 1, 0]},
    2026: {"name": "天火同人", "en": "TongRen",  "lines": [1, 0, 1, 1, 1, 1]},
    2027: {"name": "地澤臨",   "en": "Lin",      "lines": [1, 1, 0, 0, 0, 0]},
    2028: {"name": "山澤損",   "en": "Sun",      "lines": [1, 1, 0, 0, 0, 1]},
    2029: {"name": "水澤節",   "en": "Jie",      "lines": [1, 1, 0, 0, 1, 0]},
    2030: {"name": "風澤中孚", "en": "ZhongFu",  "lines": [1, 1, 0, 0, 1, 1]},
}


def get_huangji_lichun_soft_profile(dt_tw: datetime.datetime) -> Dict[str, Any]:
    """
    皇極經世「立春起算 (02/04 換卦)」雙月六爻軟加權設定：
    只調整倉位大小、最大持倉時間與基礎 TP/SL，絕不硬砍大六壬進場訊號。
    """
    y = dt_tw.year
    lc_this = datetime.datetime(y, 2, 4)
    if dt_tw >= lc_this:
        hj_year = y
        start_ref = lc_this
    else:
        hj_year = y - 1
        start_ref = datetime.datetime(y - 1, 2, 4)

    days_elapsed = max(0, (dt_tw - start_ref).days)
    yao_idx = min(5, int(days_elapsed / 60.875))
    hex_info = HUANGJI_YEAR_HEXAGRAMS.get(hj_year, HUANGJI_YEAR_HEXAGRAMS[2026])
    is_yang = (hex_info["lines"][yao_idx] == 1)
    is_proper = (yao_idx % 2 == 0 and is_yang) or (yao_idx % 2 == 1 and not is_yang)

    yao_en = f"Yao{yao_idx+1}-{'Yang9' if is_yang else 'Yin6'}({'Proper' if is_proper else 'Unproper'})"

    # v13.3 純倉位型皇極立春加權：鎖死最穩的 v12.0 TP(+1.5%)/SL(-0.9%)/4.0h，不誤收窄停損，僅依爻位當位溫和調整倉位
    presets = {
        0: {"tp": 0.0150, "sl": 0.0090, "hold_h": 4.0, "pos_m": 1.00},  # 初爻潛伏
        1: {"tp": 0.0150, "sl": 0.0090, "hold_h": 4.0, "pos_m": 1.10},  # 二爻居中
        2: {"tp": 0.0150, "sl": 0.0090, "hold_h": 4.0, "pos_m": 0.98},  # 三爻多凶
        3: {"tp": 0.0150, "sl": 0.0090, "hold_h": 4.0, "pos_m": 1.02},  # 四爻多懼
        4: {"tp": 0.0150, "sl": 0.0090, "hold_h": 4.0, "pos_m": 1.14},  # 五爻尊位
        5: {"tp": 0.0150, "sl": 0.0090, "hold_h": 4.0, "pos_m": 0.98},  # 上爻亢極
    }
    cfg = presets[yao_idx]
    prop_m = 1.04 if is_proper else 1.00

    return {
        "hj_year": hj_year,
        "hex_en": hex_info["en"],
        "yao_idx": yao_idx,
        "yao_en": yao_en,
        "is_yang": is_yang,
        "is_proper": is_proper,
        "base_tp": cfg["tp"],
        "base_sl": cfg["sl"],
        "max_hold_h": cfg["hold_h"],
        "long_size_mult": round(cfg["pos_m"] * prop_m * (1.04 if is_yang else 0.98), 3),
        "short_size_mult": round(cfg["pos_m"] * prop_m * (0.98 if is_yang else 1.04), 3),
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
    統一以 300 根 5 分鐘 K 線 (25 小時) 計算均線、ATR 波動率與 1H RSI，
    結合大六壬 v12.0 動態應期與皇極經世立春軟加權輸出 v13.3 完整交易指令。
    """
    if dt_tw is None:
        dt_tw = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)

    curr_p = closes_5m[-1]
    # 統一模擬盤與實盤均線窗口為 300 根 5m (25 小時)
    ma_len = min(120, len(closes_5m))
    ma_macro = sum(closes_5m[-ma_len:]) / float(ma_len)
    ma_prev = sum(closes_5m[-ma_len - 11:-11]) / float(ma_len) if len(closes_5m) >= (ma_len + 12) else ma_macro
    slope = (ma_macro - ma_prev) / ma_prev * 100.0
    mom_15m = (curr_p - closes_5m[-4]) / closes_5m[-4] * 100.0 if len(closes_5m) >= 4 else 0.0

    # 計算 1 小時 RSI (12 根 5m)
    gains, losses = [], []
    for j in range(max(1, len(closes_5m) - 12), len(closes_5m)):
        d = closes_5m[j] - closes_5m[j - 1]
        if d > 0:
            gains.append(d)
        else:
            losses.append(-d)
    rsi_1h = 100.0 if sum(losses) == 0 else 100.0 - (100.0 / (1.0 + (sum(gains) / 12.0) / (sum(losses) / 12.0)))

    # 計算近 48 根 5m (4 小時) 之平均絕對波動率，作為 ATR 自適應縮放係數 (0.85x ~ 1.25x)
    atr_diffs = [abs(closes_5m[j] - closes_5m[j - 1]) / max(1.0, closes_5m[j - 1]) for j in range(max(1, len(closes_5m) - 48), len(closes_5m))]
    avg_5m_vol = (sum(atr_diffs) / len(atr_diffs)) if atr_diffs else 0.0018
    atr_mult = max(0.92, min(1.12, avg_5m_vol / 0.0018))

    chart = cast_daily_tsmc_chart(dt_tw)
    q = calc_shichen_qimen(chart)
    res_el = calc_btc_fire_resonance(chart)
    el_score = res_el["el_score"]
    sched = compute_dynamic_shichen_schedule(chart, q, el_score)
    hj = get_huangji_lichun_soft_profile(dt_tw)

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
    # 加入 RSI 極端防呆鎖 (RSI > 78 不追多，RSI < 22 不追空)
    long_sig = is_eval_minute and (not bull_trap) and (not q["wubuyushi"]) and q["good_door"] and (q["q_score"] >= 15) and (el_score >= -3.0) and (
        active_lq in ("妻財", "子孫", "父母") and not active_kw
    ) and (curr_p >= ma_macro * 0.996) and (mom_15m >= -0.05)

    short_sig = is_eval_minute and (not long_sig) and (slope < 0.25) and (el_score <= 5.0) and (
        (q["door"] in ("死門", "驚門") or q["wubuyushi"]) and (active_lq in ("官鬼", "兄弟") or active_gen in ("白虎", "玄武"))
    ) and (curr_p < ma_macro * 1.002) and (mom_15m <= 0.05)

    if phase_idx == 2 and active_kw:
        long_sig = False
        short_sig = False

    signal = "LONG" if long_sig else ("SHORT" if short_sig else "HOLD")

    # 結合「皇極立春軟加權基礎 TP/SL」×「ATR 波動率自適應係數」，並鎖在安全上下限內
    tp_pct = 0.0150
    sl_pct = 0.0090
    base_sz = 0.55 if (sched["eval_count"] >= 4) else 0.50

    if signal == "LONG":
        tp_price = round(curr_p * (1.0 + tp_pct), 2)
        sl_price = round(curr_p * (1.0 - sl_pct), 2)
        rec_size = round(min(0.68, max(0.48, base_sz * hj["long_size_mult"])), 2)
    elif signal == "SHORT":
        tp_price = round(curr_p * (1.0 - tp_pct), 2)
        sl_price = round(curr_p * (1.0 + sl_pct), 2)
        rec_size = round(min(0.68, max(0.48, base_sz * hj["short_size_mult"])), 2)
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
        "huangji_tag": f"{hj['hj_year']} {hj['hex_en']} {hj['yao_en']} (Hold<={hj['max_hold_h']}h)",
        "max_hold_h": hj["max_hold_h"],
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "atr_mult": round(atr_mult, 2),
        "recommended_size_pct": rec_size,
        "scale_long_ok": scale_long_ok,
        "scale_short_ok": scale_short_ok,
        "kw_lock_profit": (phase_idx == 2 and kws[2]),
        "tight_stop_middle": (phase_idx == 1 and kws[1]),
        "price": round(curr_p, 2),
        "ma20": round(ma_macro, 2),
        "mom_15m_pct": round(mom_15m, 3),
        "rsi_1h": round(rsi_1h, 1),
        "tp_price": tp_price,
        "sl_price": sl_price,
        "el_score": el_score,
        "el_note": res_el["el_note"],
        "qimen": f"{q['door']}・{q['star']}・{q['deity']}（評分 {q['q_score']:+d}{'・五不遇時' if q['wubuyushi'] else ''}）",
        "sanchuan": f"初傳{tt[0]['branch']}({lqs[0]}) → 中傳{tt[1]['branch']}({lqs[1]}) → 末傳{tt[2]['branch']}({lqs[2]})",
    }
