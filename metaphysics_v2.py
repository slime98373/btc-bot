#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
metaphysics_v2.py
Phase 1: Corrected Tri-System Metaphysics Engine
  1. True ZhuanPan QiMen 9-Palace (ChaiBu / Solar Longitude / FuTou SanYuan / Fixed Deities)
     with all 3 evaluation schemes:
       - Scheme A: ZhiShi Door Palace (值使門落宮)
       - Scheme B: Asset Element Natal Palace (資產五行對應宮位)
       - Scheme C: Host vs Guest (天盤日干宮 vs 天盤時干宮生克)
  2. Pure DaLiuRen 2D Spectrum (Manifest / Friction / Quadrants / Tomb)
  3. Astronomical LiChun HuangJi Jingshi (315 deg exact solar longitude)
"""

import datetime
from typing import Any, Dict, List, Optional
from daliuren_engine import (
    STEMS,
    BRANCHES,
    BRANCH_WUXING,
    wuxing_generates,
    wuxing_controls,
    get_yuejiang_and_month_branch,
)

PALACE_WX = {1: "水", 2: "土", 3: "木", 4: "木", 5: "土", 6: "金", 7: "金", 8: "土", 9: "火"}
RING_PALACES = [1, 8, 3, 4, 9, 2, 7, 6]
RING_DOORS   = ["休門", "生門", "傷門", "杜門", "景門", "死門", "驚門", "開門"]
RING_STARS   = ["天蓬", "天任", "天沖", "天輔", "天英", "天芮", "天柱", "天心"]
RING_DEITIES = ["值符", "螣蛇", "太陰", "六合", "白虎", "玄武", "九地", "九天"]
DOOR_WX = {"休門": "水", "生門": "土", "傷門": "木", "杜門": "木", "景門": "火", "死門": "土", "驚門": "金", "開門": "金"}
LIUYI_SANQI = ["戊", "己", "庚", "辛", "壬", "癸", "丁", "丙", "乙"]
XUN_SHOU_YI = {0: "戊", 10: "己", 8: "庚", 6: "辛", 4: "壬", 2: "癸"}

YANG_JU_TABLE = [
    (1, 7, 4), (2, 8, 5), (3, 9, 6),  # 冬至, 小寒, 大寒
    (8, 5, 2), (9, 6, 3), (1, 7, 4),  # 立春, 雨水, 驚蟄
    (3, 9, 6), (4, 1, 7), (5, 2, 8),  # 春分, 清明, 穀雨
    (4, 1, 7), (5, 2, 8), (6, 3, 9),  # 立夏, 小滿, 芒種
]
YIN_JU_TABLE = [
    (9, 3, 6), (8, 2, 5), (7, 1, 4),  # 夏至, 小暑, 大暑
    (2, 5, 8), (1, 4, 7), (9, 3, 6),  # 立秋, 處暑, 白露
    (7, 1, 4), (6, 9, 3), (5, 8, 2),  # 秋分, 寒露, 霜降
    (6, 9, 3), (5, 8, 2), (4, 7, 1),  # 立冬, 小雪, 大雪
]

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

# 資產五行對應洛書九宮預設值（供奇門方案 B 使用）
ELEMENT_TO_PALACE = {"水": 1, "土": 2, "木": 3, "金": 7, "火": 9}


def _score_single_palace(pal: int, door: str, star: str, deity: str, wubuyushi: bool) -> Dict[str, Any]:
    d_wx = DOOR_WX[door]
    p_wx = PALACE_WX[pal]
    menpo = wuxing_controls(d_wx, p_wx)
    palace_helps = wuxing_generates(p_wx, d_wx)
    palace_ctrl = wuxing_controls(p_wx, d_wx)

    q_score = 0
    if door in ("生門", "開門", "休門"):
        q_score += 18
    elif door == "景門":
        q_score += 6
    elif door in ("死門", "驚門", "傷門"):
        q_score -= 16
    else:
        q_score -= 6

    if star in ("天任", "天輔", "天心"):
        q_score += 10
    elif star in ("天蓬", "天芮", "天柱"):
        q_score -= 10

    if deity in ("值符", "九天", "太陰", "六合"):
        q_score += 8
    elif deity in ("白虎", "玄武", "螣蛇"):
        q_score -= 10

    if menpo:
        q_score -= 12
    elif palace_helps:
        q_score += 8
    elif palace_ctrl:
        q_score -= 5
    if wubuyushi:
        q_score -= 22

    if wubuyushi or (door in ("死門", "驚門") and not palace_helps):
        regime = "QM_HOSTILE_BEAR"
    elif door in ("生門", "開門", "休門") and (not menpo) and q_score >= 12:
        regime = "QM_FAVORABLE_BOOST" if palace_helps else "QM_FAVORABLE"
    elif menpo or door == "景門":
        regime = "QM_MENPO_OR_FIRE"
    else:
        regime = "QM_NEUTRAL"

    rel_tag = "MenPo(Clash)" if menpo else ("PalaceBoost" if palace_helps else ("PalaceCtrl" if palace_ctrl else "Neutral"))
    return {
        "palace": pal,
        "door": door,
        "star": star,
        "deity": deity,
        "menpo": menpo,
        "palace_helps": palace_helps,
        "palace_ctrl": palace_ctrl,
        "rel_tag": rel_tag,
        "q_score": q_score,
        "qm_regime": regime,
    }


def calc_true_qimen_v2(chart, asset_qm_palace: int = 9) -> Dict[str, Any]:
    """
    正統轉盤時家奇門（拆補法 + 太陽黃經定節氣 + 符頭定三元 + 正確八神排布）
    同時回傳三種取用宮位方案：scheme_a (值使門宮), scheme_b (資產宮), scheme_c (主客對比)。
    """
    p = chart.pillars
    day_g = STEMS.index(p["day_stem"])
    day_z = BRANCHES.index(p["day_branch"])
    hr_g = STEMS.index(p["hour_stem"])
    hr_z = BRANCHES.index(p["hour_branch"])
    sun_lon = float(p["sun_longitude"])

    wubuyushi = ((hr_g - day_g) % 10 == 6)

    # 1. 精確太陽黃經定陰陽遁與節氣（冬至=270°, 夏至=90°）
    is_yang_dun = (sun_lon >= 270.0) or (sun_lon < 90.0)
    if is_yang_dun:
        term_idx = int(((sun_lon - 270.0) % 360.0) // 15.0) % 12
        ju_row = YANG_JU_TABLE[term_idx]
    else:
        term_idx = int((sun_lon - 90.0) // 15.0) % 12
        ju_row = YIN_JU_TABLE[term_idx]

    # 2. 正統符頭（甲／己日地支）定三元（每元連續 5 日）
    futou_z = (day_z - (day_g % 5)) % 12
    yuan = 0 if (futou_z % 3 == 0) else (1 if (futou_z % 3 == 2) else 2)
    ju = ju_row[yuan]

    # 3. 排地盤三奇六儀
    earth_plate: Dict[int, str] = {}
    earth_stem_to_pal: Dict[str, int] = {}
    for step, stem in enumerate(LIUYI_SANQI):
        pal = ((ju - 1 + step) % 9) + 1 if is_yang_dun else ((ju - 1 - step) % 9) + 1
        earth_plate[pal] = stem
        earth_stem_to_pal[stem] = pal

    # 4. 旬首、值符星與值使門原宮（中五寄坤二）
    xun_yi = XUN_SHOU_YI[(hr_z - hr_g) % 12]
    xun_pal = earth_stem_to_pal[xun_yi]
    orig_pal = 2 if xun_pal == 5 else xun_pal
    orig_ring_idx = RING_PALACES.index(orig_pal)

    # 5. 值符隨時干（找時干地盤落宮）
    hr_target_stem = xun_yi if p["hour_stem"] == "甲" else p["hour_stem"]
    hr_earth_pal = earth_stem_to_pal[hr_target_stem]
    zhifu_curr_pal = 2 if hr_earth_pal == 5 else hr_earth_pal
    zf_curr_ring_idx = RING_PALACES.index(zhifu_curr_pal)
    star_shift = (zf_curr_ring_idx - orig_ring_idx) % 8

    # 6. 值使隨時宮（由旬首宮陽順陰逆數至時干步數）
    zhishi_curr_pal = ((xun_pal - 1 + hr_g) % 9) + 1 if is_yang_dun else ((xun_pal - 1 - hr_g) % 9) + 1
    if zhishi_curr_pal == 5:
        zhishi_curr_pal = 2
    zs_curr_ring_idx = RING_PALACES.index(zhishi_curr_pal)
    door_shift = (zs_curr_ring_idx - orig_ring_idx) % 8

    # 7. 建立完整八宮轉盤（含正確八神與天盤干寄宮）
    board: Dict[int, Dict[str, Any]] = {}
    heaven_stem_to_pal: Dict[str, int] = {}
    for ring_i, pal in enumerate(RING_PALACES):
        src_star_idx = (ring_i - star_shift) % 8
        src_door_idx = (ring_i - door_shift) % 8
        src_pal_for_stem = RING_PALACES[src_star_idx]

        star = RING_STARS[src_star_idx]
        door = RING_DOORS[src_door_idx]
        # 小值符隨大值符（zf_curr_ring_idx），陽順陰逆
        deity = (
            RING_DEITIES[(ring_i - zf_curr_ring_idx) % 8]
            if is_yang_dun
            else RING_DEITIES[(zf_curr_ring_idx - ring_i) % 8]
        )

        h_stems = [earth_plate[src_pal_for_stem]]
        if src_pal_for_stem == 2:
            h_stems.append(earth_plate[5])  # 中五宮隨坤二天芮星飛轉
        for hs in h_stems:
            heaven_stem_to_pal[hs] = pal

        info = _score_single_palace(pal, door, star, deity, wubuyushi)
        info["earth_stem"] = earth_plate[pal]
        info["heaven_stems"] = h_stems
        board[pal] = info

    # --- 方案 A：值使門落宮 ---
    scheme_a = board[zhishi_curr_pal]

    # --- 方案 B：資產五行對應宮位 ---
    b_pal = 2 if asset_qm_palace == 5 else asset_qm_palace
    scheme_b = board[b_pal]

    # --- 方案 C：主客對比（天盤日干宮為主 vs 天盤時干宮為客） ---
    day_xun_yi = XUN_SHOU_YI[(day_z - day_g) % 12]
    day_target_stem = day_xun_yi if p["day_stem"] == "甲" else p["day_stem"]
    day_pal = heaven_stem_to_pal[day_target_stem]
    hour_pal = heaven_stem_to_pal[hr_target_stem]

    d_wx = PALACE_WX[day_pal]
    h_wx = PALACE_WX[hour_pal]
    if wuxing_generates(h_wx, d_wx):
        hg_rel = "HourGenDay"     # 客生主（順勢助漲）
    elif d_wx == h_wx:
        hg_rel = "Same"           # 主客比和
    elif wuxing_controls(d_wx, h_wx):
        hg_rel = "DayCtrlHour"    # 主克客（多方主導）
    elif wuxing_generates(d_wx, h_wx):
        hg_rel = "DayGenHour"     # 主生客（動能洩氣）
    else:
        hg_rel = "HourCtrlDay"    # 客克主（盤面反噬）

    day_board = board[day_pal]
    if wubuyushi or hg_rel == "HourCtrlDay":
        hg_regime = "HG_HOSTILE"
    elif hg_rel in ("HourGenDay", "Same", "DayCtrlHour") and (not day_board["menpo"]) and day_board["door"] in ("生門", "開門", "休門"):
        hg_regime = "HG_FAVORABLE_BOOST"
    elif hg_rel in ("HourGenDay", "Same", "DayCtrlHour"):
        hg_regime = "HG_FAVORABLE"
    else:
        hg_regime = "HG_WEAK_DRAIN"

    scheme_c = {
        "day_palace": day_pal,
        "hour_palace": hour_pal,
        "day_wx": d_wx,
        "hour_wx": h_wx,
        "hg_rel": hg_rel,
        "hg_pure_group": "HG_FAV_PURE" if hg_rel in ("HourGenDay", "Same", "DayCtrlHour") else "HG_HOSTILE_PURE",
        "qm_regime": hg_regime,
        "day_door": day_board["door"],
        "day_menpo": day_board["menpo"],
        "q_score": day_board["q_score"] + (10 if hg_rel == "HourGenDay" else (4 if hg_rel in ("Same", "DayCtrlHour") else (-6 if hg_rel == "DayGenHour" else -12))),
    }

    return {
        "dun": f"{'Yang' if is_yang_dun else 'Yin'}-Ju{ju}",
        "wubuyushi": wubuyushi,
        "scheme_a": scheme_a,
        "scheme_b": scheme_b,
        "scheme_c": scheme_c,
        "board": board,
    }


def calc_pure_daliuren_2d_v2(chart, phase_idx: int = 0, el: str = "火", palace: str = "午", tomb: str = "戌") -> Dict[str, Any]:
    """純大六壬 2D 光譜（依標的專屬五行、本命宮位與墓庫獨立評分）"""
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
    blockers: List[str] = []
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

    return {
        "manifest": manifest,
        "friction": friction,
        "quadrant": quad,
        "has_tomb": any("Tomb(" in b for b in blockers),
        "blockers": blockers if blockers else ["None"],
    }


def get_huangji_astro_profile(dt_tw: datetime.datetime, sun_lon: Optional[float] = None) -> Dict[str, Any]:
    """精確太陽黃經立春（315°）起算皇極經世雙月六爻"""
    if sun_lon is None:
        _, _, _, sun_lon = get_yuejiang_and_month_branch(dt_tw)

    hj_year = dt_tw.year - (1 if (dt_tw.month <= 2 and 200.0 < sun_lon < 315.0) else 0)
    deg_since_lichun = (sun_lon - 315.0) % 360.0
    yao_idx = min(5, int(deg_since_lichun // 60.0))

    hex_info = HUANGJI_YEAR_HEXAGRAMS.get(hj_year, HUANGJI_YEAR_HEXAGRAMS[2026])
    is_yang = (hex_info["lines"][yao_idx] == 1)
    is_proper = (yao_idx % 2 == 0 and is_yang) or (yao_idx % 2 == 1 and not is_yang)

    pos_m = {0: 1.00, 1: 1.10, 2: 0.98, 3: 1.02, 4: 1.14, 5: 0.98}[yao_idx]
    prop_m = 1.04 if is_proper else 1.00
    return {
        "hj_year": hj_year,
        "hex_en": hex_info["en"],
        "yao_idx": yao_idx,
        "is_yang": is_yang,
        "is_proper": is_proper,
        "long_size_mult": round(pos_m * prop_m * (1.04 if is_yang else 0.98), 3),
        "short_size_mult": round(pos_m * prop_m * (0.98 if is_yang else 1.04), 3),
    }
