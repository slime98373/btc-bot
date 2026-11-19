#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比特幣 (BTC/USDT) 三式合參 v15.0「真陰陽遁奇門九宮門迫 × 純大六壬 2D 光譜動態應期 × 皇極立春倉位加權」策略模組 (btc_strategy.py)
========================================================================================================================================
三式分工（徹底消除特徵雙重計算）：
  1. 【皇極經世（立春起算・雙月六爻）】＝ 宏觀大氣候 -> 專管資金倉位底盤 (48%~68%)。
  2. 【大六壬（純 2D 多維度光譜＋動態應期 0~6 次）】＝ 交易主帥 -> 100% 純粹以四課三傳、空亡、火墓戌土與凶神評分，絕不混入奇門分數。
  3. 【真時家奇門（陰陽遁轉盤九宮＋門迫／宮生門檢測）】＝ 戰場地利 -> 與大六壬構成「壬奇共振矩陣」：
     - 雙吉共振（壬 Q1 ＋ 奇門宮生門無門迫）：最高火力 1.10x，順勢加碼上限 80%。
     - 壬強奇迫（奇門逢門迫或景門急拉）：縮倉 0.92x、禁止追高加碼、保本門檻提前至 +0.65%。
     - 壬泥奇凶（壬 Q4 泥沼 ＋ 奇門死/驚門或五不遇時）：雙重確認空頭，果斷放大空單權重 1.12x。
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
ELEMENT_TOMB = {"木": "未", "火": "戌", "土": "戌", "金": "丑", "水": "辰"}

ASSET_PROFILES = {
    "BTC": {"name_en": "BTC/USDT (Fire/Wu-Palace)",  "symbol": "BTC/USDT:USDT", "pub_pairs": [("okx", "BTC/USDT"), ("kraken", "BTC/USD"), ("coinbase", "BTC/USD"), ("gate", "BTC/USDT")], "el": "火", "palace": "午", "tomb": "戌", "tp": 0.0150, "sl": 0.0090, "vol_2h": 0.0090, "min_qty": 0.001, "qty_dp": 3, "state_file": "btc_bot_state.json"},
    "ETH": {"name_en": "ETH/USDT (Wood/Mao-Palace)", "symbol": "ETH/USDT:USDT", "pub_pairs": [("okx", "ETH/USDT"), ("kraken", "ETH/USD"), ("coinbase", "ETH/USD"), ("gate", "ETH/USDT")], "el": "木", "palace": "卯", "tomb": "未", "tp": 0.0190, "sl": 0.0110, "vol_2h": 0.0112, "min_qty": 0.01,  "qty_dp": 2, "state_file": "eth_bot_state.json"},
    "SOL": {"name_en": "SOL/USDT (Fire/Si-Palace)",  "symbol": "SOL/USDT:USDT", "pub_pairs": [("okx", "SOL/USDT"), ("kraken", "SOL/USD"), ("coinbase", "SOL/USD"), ("gate", "SOL/USDT")], "el": "火", "palace": "巳", "tomb": "戌", "tp": 0.0230, "sl": 0.0135, "vol_2h": 0.0140, "min_qty": 0.1,   "qty_dp": 1, "state_file": "sol_bot_state.json"},
}


# 真時家奇門九宮常數
PALACE_WX = {1: "水", 2: "土", 3: "木", 4: "木", 5: "土", 6: "金", 7: "金", 8: "土", 9: "火"}
RING_PALACES = [1, 8, 3, 4, 9, 2, 7, 6]
RING_DOORS   = ["休門", "生門", "傷門", "杜門", "景門", "死門", "驚門", "開門"]
RING_STARS   = ["天蓬", "天任", "天沖", "天輔", "天英", "天芮", "天柱", "天心"]
RING_DEITIES = ["值符", "螣蛇", "太陰", "六合", "白虎", "玄武", "九地", "九天"]
DOOR_WX = {"休門": "水", "生門": "土", "傷門": "木", "杜門": "木", "景門": "火", "死門": "土", "驚門": "金", "開門": "金"}
LIUYI_SANQI = ["戊", "己", "庚", "辛", "壬", "癸", "丁", "丙", "乙"]
XUN_SHOU_YI = {0: "戊", 10: "己", 8: "庚", 6: "辛", 4: "壬", 2: "癸"}

HUANGJI_YEAR_HEXAGRAMS = {
    2016: {"name": "震為雷",   "en": "Zhen",    "lines": [1, 0, 0, 1, 0, 0]},
    2017: {"name": "火雷噬嗑", "en": "ShiKe",   "lines": [1, 0, 0, 1, 0, 1]},
    2018: {"name": "澤雷隨",   "en": "Sui",     "lines": [1, 0, 0, 1, 1, 0]},
    2019: {"name": "天雷無妄", "en": "WuWang",  "lines": [1, 0, 0, 1, 1, 1]},
    2020: {"name": "地火明夷", "en": "MingYi",  "lines": [1, 0, 1, 0, 0, 0]},
    2021: {"name": "山火賁",   "en": "Bi",      "lines": [1, 0, 1, 0, 0, 1]},
    2022: {"name": "水火既濟", "en": "JiJi",    "lines": [1, 0, 1, 0, 1, 0]},
    2023: {"name": "風火家人", "en": "JiaRen",  "lines": [1, 0, 1, 0, 1, 1]},
    2024: {"name": "雷火豐",   "en": "Feng",    "lines": [1, 0, 1, 1, 0, 0]},
    2025: {"name": "澤火革",   "en": "Ge",      "lines": [1, 0, 1, 1, 1, 0]},
    2026: {"name": "天火同人", "en": "TongRen", "lines": [1, 0, 1, 1, 1, 1]},
    2027: {"name": "地澤臨",   "en": "Lin",     "lines": [1, 1, 0, 0, 0, 0]},
    2028: {"name": "山澤損",   "en": "Sun",     "lines": [1, 1, 0, 0, 0, 1]},
    2029: {"name": "水澤節",   "en": "Jie",     "lines": [1, 1, 0, 0, 1, 0]},
    2030: {"name": "風澤中孚", "en": "ZhongFu", "lines": [1, 1, 0, 0, 1, 1]},
}


def get_huangji_lichun_soft_profile(dt_tw: datetime.datetime) -> Dict[str, Any]:
    y = dt_tw.year
    lc_this = datetime.datetime(y, 2, 4)
    if dt_tw >= lc_this:
        hj_year, start_ref = y, lc_this
    else:
        hj_year, start_ref = y - 1, datetime.datetime(y - 1, 2, 4)

    days_elapsed = max(0, (dt_tw - start_ref).days)
    yao_idx = min(5, int(days_elapsed / 60.875))
    hex_info = HUANGJI_YEAR_HEXAGRAMS.get(hj_year, HUANGJI_YEAR_HEXAGRAMS[2026])
    is_yang = (hex_info["lines"][yao_idx] == 1)
    is_proper = (yao_idx % 2 == 0 and is_yang) or (yao_idx % 2 == 1 and not is_yang)
    yao_en = f"Yao{yao_idx+1}-{'Yang9' if is_yang else 'Yin6'}({'Proper' if is_proper else 'Unproper'})"

    pos_m = {0: 1.00, 1: 1.10, 2: 0.98, 3: 1.02, 4: 1.14, 5: 0.98}[yao_idx]
    prop_m = 1.04 if is_proper else 1.00

    return {
        "hj_year": hj_year,
        "hex_en": hex_info["en"],
        "yao_idx": yao_idx,
        "yao_en": yao_en,
        "is_yang": is_yang,
        "is_proper": is_proper,
        "max_hold_h": 4.0,
        "long_size_mult": round(pos_m * prop_m * (1.04 if is_yang else 0.98), 3),
        "short_size_mult": round(pos_m * prop_m * (0.98 if is_yang else 1.04), 3),
    }


def calc_shichen_qimen(chart) -> Dict[str, Any]:
    """保留基礎時辰奇門濾網作為輔助校驗"""
    p = chart.pillars
    day_idx = STEMS.index(p["day_stem"])
    hour_gan_idx = STEMS.index(p["hour_stem"])
    hour_zhi_idx = BRANCHES.index(p["hour_branch"])
    wubuyushi = ((hour_gan_idx - day_idx) % 10 == 6)
    doors = ["休門", "生門", "傷門", "杜門", "景門", "死門", "驚門", "開門"]
    stars = ["天蓬", "天任", "天沖", "天輔", "天英", "天芮", "天柱", "天心"]
    deities = ["值符", "螣蛇", "太陰", "六合", "白虎", "玄武", "九地", "九天"]
    door = doors[(day_idx + hour_zhi_idx + BRANCHES.index(p["yuejiang"])) % 8]
    star = stars[(day_idx * 3 + hour_zhi_idx) % 8]
    deity = deities[(hour_gan_idx + BRANCHES.index(chart.three_transmissions[0]["branch"])) % 8]
    q_score = 0
    if door in ("生門", "開門", "休門"): q_score += 15
    elif door in ("死門", "驚門", "傷門"): q_score -= 15
    if star in ("天任", "天輔", "天心"): q_score += 10
    elif star in ("天蓬", "天芮", "天柱"): q_score -= 10
    if deity in ("值符", "九天", "太陰", "六合"): q_score += 8
    elif deity in ("白虎", "玄武", "螣蛇"): q_score -= 10
    if wubuyushi: q_score -= 25
    return {
        "hour_gan": p["hour_stem"], "hour_branch": p["hour_branch"],
        "wubuyushi": wubuyushi, "door": door, "star": star, "deity": deity,
        "q_score": q_score, "good_door": door in ("生門", "開門", "休門"),
    }


def calc_true_qimen_9palace(dt_tw: datetime.datetime, chart) -> Dict[str, Any]:
    """真時家奇門轉盤九宮陰陽遁排法 + 門迫／宮生門檢測 + 獨立戰場模式 (v15.0)"""
    p = chart.pillars
    day_g = STEMS.index(p["day_stem"])
    day_z = BRANCHES.index(p["day_branch"])
    hr_g = STEMS.index(p["hour_stem"])
    hr_z = BRANCHES.index(p["hour_branch"])

    wubuyushi = ((hr_g - day_g) % 10 == 6)
    md = (dt_tw.month, dt_tw.day)
    is_yang_dun = (md >= (12, 22)) or (md <= (6, 20))
    yuan = 0 if (day_z % 3 == 0) else (1 if (day_z % 3 == 2) else 2)
    doy = dt_tw.timetuple().tm_yday

    if is_yang_dun:
        term_idx = ((doy + 10) % 365) // 15
        ju_table = [(1,7,4),(2,8,5),(3,9,6),(8,5,2),(9,6,3),(1,7,4),(3,9,6),(4,1,7),(5,2,8),(4,1,7),(5,2,8),(6,3,9)]
        ju = ju_table[term_idx % 12][yuan]
    else:
        term_idx = max(0, (doy - 172)) // 15
        ju_table = [(9,3,6),(8,2,5),(7,1,4),(2,5,8),(1,4,7),(9,3,6),(7,1,4),(6,9,3),(5,8,2),(6,9,3),(5,8,2),(4,7,1)]
        ju = ju_table[term_idx % 12][yuan]

    earth_plate = {}
    for step, stem in enumerate(LIUYI_SANQI):
        pal = ((ju - 1 + step) % 9) + 1 if is_yang_dun else ((ju - 1 - step) % 9) + 1
        earth_plate[pal] = stem

    xun_yi = XUN_SHOU_YI[(hr_z - hr_g) % 12]
    xun_pal = [pal for pal, s in earth_plate.items() if s == xun_yi][0]
    zhishi_orig_pal = 2 if xun_pal == 5 else xun_pal
    orig_ring_idx = RING_PALACES.index(zhishi_orig_pal)

    zhishi_curr_pal = ((xun_pal - 1 + hr_g) % 9) + 1 if is_yang_dun else ((xun_pal - 1 - hr_g) % 9) + 1
    if zhishi_curr_pal == 5:
        zhishi_curr_pal = 2

    target_stem = xun_yi if p["hour_stem"] == "甲" else p["hour_stem"]
    hour_stem_pal = [pal for pal, s in earth_plate.items() if s == target_stem][0]
    eval_pal = 2 if hour_stem_pal == 5 else hour_stem_pal

    door_shift = (RING_PALACES.index(zhishi_curr_pal) - orig_ring_idx) % 8
    star_shift = (RING_PALACES.index(eval_pal) - orig_ring_idx) % 8
    eval_ring_i = RING_PALACES.index(eval_pal)

    door = RING_DOORS[(eval_ring_i - door_shift) % 8]
    star = RING_STARS[(eval_ring_i - star_shift) % 8]
    deity = RING_DEITIES[(eval_ring_i - star_shift) % 8] if is_yang_dun else RING_DEITIES[(star_shift - eval_ring_i) % 8]

    d_wx, p_wx = DOOR_WX[door], PALACE_WX[eval_pal]
    menpo = wuxing_controls(d_wx, p_wx)
    palace_helps = wuxing_generates(p_wx, d_wx)
    palace_ctrl = wuxing_controls(p_wx, d_wx)

    q_score = 0
    if door in ("生門", "開門", "休門"): q_score += 18
    elif door == "景門": q_score += 6
    elif door in ("死門", "驚門", "傷門"): q_score -= 16
    else: q_score -= 6

    if star in ("天任", "天輔", "天心"): q_score += 10
    elif star in ("天蓬", "天芮", "天柱"): q_score -= 10
    if deity in ("值符", "九天", "太陰", "六合"): q_score += 8
    elif deity in ("白虎", "玄武", "螣蛇"): q_score -= 10

    if menpo: q_score -= 12
    elif palace_helps: q_score += 8
    elif palace_ctrl: q_score -= 5
    if wubuyushi: q_score -= 22

    if wubuyushi or (door in ("死門", "驚門") and not palace_helps):
        qm_regime = "QM_HOSTILE_BEAR"
    elif door in ("生門", "開門", "休門") and (not menpo) and q_score >= 12:
        qm_regime = "QM_FAVORABLE_BOOST" if palace_helps else "QM_FAVORABLE"
    elif menpo or door == "景門":
        qm_regime = "QM_MENPO_OR_FIRE"
    else:
        qm_regime = "QM_NEUTRAL"

    rel_tag = "MenPo(Clash)" if menpo else ("PalaceBoost" if palace_helps else ("PalaceCtrl" if palace_ctrl else "Neutral"))
    return {
        "dun": f"{'Yang' if is_yang_dun else 'Yin'}-Ju{ju}",
        "palace": eval_pal,
        "door": door,
        "star": star,
        "deity": deity,
        "menpo": menpo,
        "palace_helps": palace_helps,
        "rel_tag": rel_tag,
        "wubuyushi": wubuyushi,
        "q_score": q_score,
        "qm_regime": qm_regime,
    }


def calc_btc_fire_resonance(chart, el: str = "火", palace: str = "午") -> Dict[str, Any]:
    m_wx = BRANCH_WUXING[chart.pillars["month_branch"]]
    score = 0.0
    notes = []
    if m_wx == el or wuxing_generates(m_wx, el):
        score += 8.0
        notes.append(f"月令{chart.pillars['month_branch']}({m_wx})生旺離火(+8)")
    elif wuxing_controls(m_wx, el):
        score -= 8.0
        notes.append(f"月令{chart.pillars['month_branch']}({m_wx})水克離火(-8)")
    weights = [0.5, 0.3, 0.2]
    for i, t in enumerate(chart.three_transmissions):
        t_wx = t["wuxing"]
        mult = 0.4 if (t["kongwang"] == "空亡") else 1.0
        if t_wx == el or wuxing_generates(t_wx, el):
            score += round(12.0 * weights[i] * mult, 1)
        elif wuxing_controls(t_wx, el):
            score -= round(12.0 * weights[i] * mult, 1)
    top_b = chart.heaven_plate[palace]
    top_gen = chart.generals_plate[top_b]
    is_kw = top_b in chart.pillars["kongwang"]
    if top_gen in ("青龍", "貴人", "六合", "太常", "太陰") and not is_kw:
        score += 6.0
    elif top_gen in ("白虎", "螣蛇", "玄武", "天空") or is_kw:
        score -= 6.0
    return {"el_score": round(score, 1), "el_note": "｜".join(notes)}


def calc_pure_daliuren_2d(chart, phase_idx: int, el: str = "火", palace: str = "午", tomb: str = "戌") -> Dict[str, Any]:
    """[去重複計分] 純粹大六壬 2D 光譜：依標的專屬五行、本命宮位與墓庫獨立評分"""
    tt = chart.three_transmissions
    m_wx = BRANCH_WUXING[chart.pillars["month_branch"]]
    curr_t = tt[phase_idx]

    manifest = 40.0
    if m_wx == el or wuxing_generates(m_wx, el):
        manifest += 22.0
    for i, t in enumerate(tt):
        w = [0.5, 0.3, 0.2][i]
        if t["kongwang"] != "空亡":
            if t["wuxing"] == el or wuxing_generates(t["wuxing"], el):
                manifest += 22.0 * w
            if t["general"] in ("青龍", "貴人", "六合", "太常", "太陰"):
                manifest += 18.0 * w
            if t["liuqin"] in ("妻財", "子孫"):
                manifest += 10.0 * w
    p_top = chart.heaven_plate[palace]
    p_gen = chart.generals_plate[p_top]
    if p_gen in ("青龍", "貴人", "六合", "太常") and p_top not in chart.pillars["kongwang"]:
        manifest += 12.0
    manifest = round(max(0.0, min(100.0, manifest)), 1)

    friction = 10.0
    blockers = []
    void_cnt = sum(1 for t in tt if t["kongwang"] == "空亡")
    if void_cnt > 0:
        friction += 20.0 * void_cnt
        blockers.append(f"Void({void_cnt})")
    if p_top == tomb or curr_t["branch"] == tomb or tt[0]["branch"] == tomb:
        friction += 24.0
        blockers.append(f"Tomb({tomb})")
    fierce_cnt = sum(1 for t in tt if t["general"] in ("白虎", "螣蛇", "玄武", "天空"))
    if fierce_cnt > 0:
        friction += 13.0 * fierce_cnt
        blockers.append(f"FierceGen({fierce_cnt})")
    if p_gen in ("白虎", "螣蛇", "玄武", "天空"):
        friction += 15.0
        blockers.append(f"Palace-{p_gen}")
    if wuxing_controls(m_wx, el):
        friction += 12.0
        blockers.append("MonthClash")
    friction = round(max(0.0, min(100.0, friction)), 1)

    if manifest >= 55.0 and friction <= 38.0:
        quad = "Q1_CLEAR_RUNWAY"
    elif manifest >= 55.0 and friction > 38.0:
        quad = "Q2_FRICTION_RUSH"
    elif manifest < 55.0 and friction <= 38.0:
        quad = "Q3_MILD_DRIFT"
    else:
        quad = "Q4_TRAP_QUAGMIRE"

    return {"manifest": manifest, "friction": friction, "quadrant": quad, "blockers": blockers if blockers else ["None"]}


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
        return {"mode_en": "DORMANT_0 (0 checks - Chop Filter)", "eval_count": 0, "eval_minutes": [], "slot_meta": {}}

    base_minutes = []
    slot_meta = {}
    for i, t in enumerate(tt):
        if kws[i]:
            continue
        b = t["branch"]
        offset_branch = (BRANCHES.index(b) - hour_idx) % 12
        within_40 = ((offset_branch * 3 + TAIXUAN_NUM[b]) % 7) * 5 + 5
        minute_mark = min(115, i * 40 + within_40)
        base_minutes.append(minute_mark)
        slot_meta[minute_mark] = {
            "source": f"{['1st','2nd','3rd'][i]}({b})",
            "liuqin": t["liuqin"], "general": t["general"], "kongwang": False, "is_main_chuan": True,
        }

    if is_fanyin or (has_horse and active_wealth_ghost) or (fierce_generals >= 2 and abs(el_score) >= 6.0):
        extra_branches = [sike[0]["top"], sike[2]["top"], SIX_CLASH[hour_b]]
        day_wx = STEM_WUXING[chart.pillars["day_stem"]]
        for eb in extra_branches:
            m_mark = min(115, BRANCHES.index(eb) * 10)
            if m_mark not in slot_meta:
                eb_wx = BRANCH_WUXING[eb]
                eb_lq = "兄弟" if eb_wx == day_wx else ("子孫" if wuxing_generates(day_wx, eb_wx) else ("父母" if wuxing_generates(eb_wx, day_wx) else ("妻財" if wuxing_controls(day_wx, eb_wx) else "官鬼")))
                if eb not in chart.pillars["kongwang"]:
                    base_minutes.append(m_mark)
                    slot_meta[m_mark] = {"source": f"SiKe/Clash({eb})", "liuqin": eb_lq, "general": chart.generals_plate[eb], "kongwang": False, "is_main_chuan": False}
        eval_mins = sorted(set(base_minutes))[:6]
        return {"mode_en": f"INTENSE_{len(eval_mins)} ({len(eval_mins)} checks - High Volatility)", "eval_count": len(eval_mins), "eval_minutes": eval_mins, "slot_meta": slot_meta}

    if len(base_minutes) <= 2 or (qimen["deity"] in ("九地", "太陰") and not has_horse):
        eval_mins = sorted(set(base_minutes))[:2]
        return {"mode_en": f"SLOW_{len(eval_mins)} ({len(eval_mins)} checks - Steady)", "eval_count": len(eval_mins), "eval_minutes": eval_mins, "slot_meta": slot_meta}

    eval_mins = sorted(set(base_minutes))
    return {"mode_en": f"DYNAMIC_{len(eval_mins)} ({len(eval_mins)} checks - Standard YingQi)", "eval_count": len(eval_mins), "eval_minutes": eval_mins, "slot_meta": slot_meta}


def evaluate_btc_signal(closes_5m: List[float], dt_tw: datetime.datetime = None, force_eval: bool = False, asset_code: str = "BTC") -> Dict[str, Any]:
    if dt_tw is None:
        dt_tw = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)

    curr_p = closes_5m[-1]
    ma_len = min(120, len(closes_5m))
    ma_macro = sum(closes_5m[-ma_len:]) / float(ma_len)
    ma_prev = sum(closes_5m[-ma_len - 11:-11]) / float(ma_len) if len(closes_5m) >= (ma_len + 12) else ma_macro
    slope = (ma_macro - ma_prev) / ma_prev * 100.0
    mom_15m = (curr_p - closes_5m[-4]) / closes_5m[-4] * 100.0 if len(closes_5m) >= 4 else 0.0

    gains, losses = [], []
    for j in range(max(1, len(closes_5m) - 12), len(closes_5m)):
        d = closes_5m[j] - closes_5m[j - 1]
        (gains if d > 0 else losses).append(abs(d))
    rsi_1h = 100.0 if sum(losses) == 0 else 100.0 - (100.0 / (1.0 + (sum(gains) / 12.0) / (sum(losses) / 12.0)))

    chart = cast_daily_tsmc_chart(dt_tw)
    q_base = calc_shichen_qimen(chart)
    q_true = calc_true_qimen_9palace(dt_tw, chart)
    prof = ASSET_PROFILES.get(asset_code.upper(), ASSET_PROFILES["BTC"])
    res_el = calc_btc_fire_resonance(chart, el=prof["el"], palace=prof["palace"])
    el_score = res_el["el_score"]
    sched = compute_dynamic_shichen_schedule(chart, q_base, el_score)
    hj = get_huangji_lichun_soft_profile(dt_tw)

    raw_mins = dt_tw.minute if (dt_tw.hour % 2 == 1) else (60 + dt_tw.minute)
    slot_5m = (raw_mins // 5) * 5
    phase_idx = min(2, raw_mins // 40)
    spec = calc_pure_daliuren_2d(chart, phase_idx, el=prof["el"], palace=prof["palace"], tomb=prof["tomb"])
    quad = spec["quadrant"]

    tt = chart.three_transmissions
    lqs, gens, kws = [t["liuqin"] for t in tt], [t["general"] for t in tt], [t["kongwang"] == "空亡" for t in tt]

    is_eval_minute = (slot_5m in sched["eval_minutes"]) or force_eval
    active_lq, active_gen, active_kw = lqs[phase_idx], gens[phase_idx], kws[phase_idx]
    trigger_source = f"{['1st','2nd','3rd'][phase_idx]}({tt[phase_idx]['branch']})"

    if slot_5m in sched["slot_meta"]:
        meta = sched["slot_meta"][slot_5m]
        trigger_source = meta["source"]
        if meta.get("is_main_chuan", True):
            active_lq, active_gen, active_kw = meta["liuqin"], meta["general"], meta["kongwang"]
        elif active_kw and not kws[0]:
            active_lq, active_gen, active_kw = lqs[0], gens[0], kws[0]

    bull_trap = (active_lq == "妻財" and active_kw) or (active_lq == "父母" and active_gen in ("螣蛇", "玄武"))
    # v15.0 壬奇共振矩陣開倉邏輯
    ren_long_core = is_eval_minute and (not bull_trap) and (el_score >= -3.0) and (active_lq in ("妻財", "子孫", "父母") and not active_kw) and (curr_p >= ma_macro * 0.996) and (mom_15m >= -0.05)
    qm_long_ok = (not q_base["wubuyushi"]) and (
        (q_base["good_door"] and q_base["q_score"] >= 15) or
        (quad == "Q1_CLEAR_RUNWAY" and q_true["qm_regime"] in ("QM_FAVORABLE_BOOST", "QM_FAVORABLE"))
    )
    long_sig = ren_long_core and qm_long_ok

    ren_short_core = is_eval_minute and (not long_sig) and (slope < 0.25) and (el_score <= 5.0) and (active_lq in ("官鬼", "兄弟") or active_gen in ("白虎", "玄武")) and (curr_p < ma_macro * 1.002) and (mom_15m <= 0.05)
    qm_short_ok = (q_base["door"] in ("死門", "驚門") or q_base["wubuyushi"]) or (quad == "Q4_TRAP_QUAGMIRE" and q_true["qm_regime"] == "QM_HOSTILE_BEAR")
    short_sig = ren_short_core and qm_short_ok

    if phase_idx == 2 and active_kw:
        long_sig, short_sig = False, False

    signal = "LONG" if long_sig else ("SHORT" if short_sig else "HOLD")
    tp_pct, sl_pct = prof["tp"], prof["sl"]
    base_sz = 0.55 if (sched["eval_count"] >= 4) else 0.50

    # 真九宮門迫／宮生門火力與保本微調
    if q_true["qm_regime"] == "QM_FAVORABLE_BOOST":
        qm_mult_l, qm_mult_s, qm_be_tight = 1.10, 0.92, False
    elif q_true["qm_regime"] == "QM_FAVORABLE":
        qm_mult_l, qm_mult_s, qm_be_tight = 1.04, 0.96, False
    elif q_true["qm_regime"] == "QM_MENPO_OR_FIRE":
        qm_mult_l, qm_mult_s, qm_be_tight = 0.92, 1.00, True
    elif q_true["qm_regime"] == "QM_HOSTILE_BEAR":
        qm_mult_l, qm_mult_s, qm_be_tight = 0.88, 1.12, True
    else:
        qm_mult_l, qm_mult_s, qm_be_tight = 1.00, 1.00, False

    spec_m, be_trigger_pct = 1.0, 0.0100
    if signal == "LONG":
        if quad == "Q1_CLEAR_RUNWAY": spec_m = 1.10
        elif quad == "Q2_FRICTION_RUSH": spec_m, be_trigger_pct = 0.94, round(tp_pct * 0.45, 4)
        elif quad == "Q4_TRAP_QUAGMIRE": spec_m, be_trigger_pct = 0.88, round(tp_pct * 0.45, 4)
        if qm_be_tight: be_trigger_pct = min(be_trigger_pct, round(tp_pct * 0.43, 4))
        tp_price = round(curr_p * (1.0 + tp_pct), 2)
        sl_price = round(curr_p * (1.0 - sl_pct), 2)
        rec_size = round(min(0.75, max(0.40, base_sz * hj["long_size_mult"] * spec_m * qm_mult_l)), 2)
    elif signal == "SHORT":
        if quad == "Q4_TRAP_QUAGMIRE": spec_m = 1.12
        elif quad == "Q2_FRICTION_RUSH": spec_m = 1.04
        elif quad == "Q1_CLEAR_RUNWAY": spec_m, be_trigger_pct = 0.92, round(tp_pct * 0.48, 4)
        tp_price = round(curr_p * (1.0 - tp_pct), 2)
        sl_price = round(curr_p * (1.0 + sl_pct), 2)
        rec_size = round(min(0.75, max(0.40, base_sz * hj["short_size_mult"] * spec_m * qm_mult_s)), 2)
    else:
        tp_price, sl_price, rec_size = 0.0, 0.0, 0.0

    scale_long_ok = is_eval_minute and (quad == "Q1_CLEAR_RUNWAY") and (not q_true["menpo"]) and (active_lq in ("妻財", "子孫", "父母") and not active_kw)
    scale_short_ok = is_eval_minute and (quad in ("Q3_MILD_DRIFT", "Q4_TRAP_QUAGMIRE")) and (active_lq in ("官鬼", "兄弟") and not active_kw)
    scale_long_cap = 0.80 if q_true["palace_helps"] else 0.78
    next_mins = [m for m in sched["eval_minutes"] if m > slot_5m]

    return {
        "asset_code": asset_code.upper(),
        "asset_name_en": prof["name_en"],
        "signal": signal,
        "is_eval_minute": is_eval_minute,
        "raw_mins": raw_mins,
        "slot_5m": slot_5m,
        "sched_mode_en": sched["mode_en"],
        "eval_minutes": sched["eval_minutes"],
        "next_minutes": next_mins,
        "trigger_source": trigger_source,
        "shichen": f"{chart.pillars['hour_ganzhi']}（{q_base['hour_branch']}時）",
        "phase_idx": phase_idx,
        "active_chuan": f"{trigger_source}:{active_lq}/{active_gen}/{'Void' if active_kw else 'Solid'}",
        "spectrum_quad": quad,
        "spectrum_manifest": spec["manifest"],
        "spectrum_friction": spec["friction"],
        "spectrum_blockers": ", ".join(spec["blockers"]),
        "qm_true_str": f"{q_true['dun']} P{q_true['palace']} {q_true['door']}/{q_true['star']}/{q_true['deity']} [{q_true['rel_tag']}] -> {q_true['qm_regime']}",
        "be_trigger_pct": be_trigger_pct,
        "huangji_tag": f"{hj['hj_year']} {hj['hex_en']} {hj['yao_en']} (Size L:{hj['long_size_mult']}x/S:{hj['short_size_mult']}x)",
        "max_hold_h": hj["max_hold_h"],
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "recommended_size_pct": rec_size,
        "scale_long_ok": scale_long_ok,
        "scale_short_ok": scale_short_ok,
        "scale_long_cap": scale_long_cap,
        "kw_lock_profit": (phase_idx == 2 and kws[2]),
        "tight_stop_middle": (phase_idx == 1 and kws[1]),
        "price": round(curr_p, 2),
        "ma20": round(ma_macro, 2),
        "mom_15m_pct": round(mom_15m, 3),
        "rsi_1h": round(rsi_1h, 1),
        "tp_price": tp_price,
        "sl_price": sl_price,
        "el_score": el_score,
        "qimen": f"{q_base['door']}・{q_base['star']}・{q_base['deity']}（評分 {q_base['q_score']:+d}{'・五不遇時' if q_base['wubuyushi'] else ''}）",
        "sanchuan": f"初傳{tt[0]['branch']}({lqs[0]}) → 中傳{tt[1]['branch']}({lqs[1]}) → 末傳{tt[2]['branch']}({lqs[2]})",
    }
