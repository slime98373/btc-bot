#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

STEMS = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
BRANCHES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

STEM_WUXING = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土", "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
BRANCH_WUXING = {"子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土", "巳": "火", "午": "火", "未": "土", "申": "金", "酉": "金", "戌": "土", "亥": "水"}
STEM_YINYANG = {s: ("陽" if i % 2 == 0 else "陰") for i, s in enumerate(STEMS)}
BRANCH_YINYANG = {b: ("陽" if i % 2 == 0 else "陰") for i, b in enumerate(BRANCHES)}
STEM_PARASITIC_HOUSE = {"甲": "寅", "乙": "辰", "丙": "巳", "丁": "未", "戊": "巳", "己": "未", "庚": "申", "辛": "戌", "壬": "亥", "癸": "丑"}

MENG_BRANCHES = {"寅", "巳", "申", "亥"}
ZHONG_BRANCHES = {"子", "卯", "午", "酉"}
JI_BRANCHES = {"丑", "辰", "未", "戌"}

YUEJIANG_NAMES = {"亥": "登明", "戌": "河魁", "酉": "從魁", "申": "傳送", "未": "小吉", "午": "勝光", "巳": "太乙", "辰": "天罡", "卯": "太衝", "寅": "功曹", "丑": "大吉", "子": "神后"}
GENERALS_ORDER = ["貴人", "螣蛇", "朱雀", "六合", "勾陳", "青龍", "天空", "白虎", "太常", "玄武", "太陰", "天后"]
GENERAL_INFO = {
    "貴人": {"auspicious": "吉", "wuxing": "土", "score": +18, "stock_desc": "法人主力護盤、權值買盤加持"},
    "青龍": {"auspicious": "大吉", "wuxing": "木", "score": +22, "stock_desc": "資金充沛、多頭動能強勁"},
    "太常": {"auspicious": "吉", "wuxing": "土", "score": +12, "stock_desc": "基本面穩健、穩步墊高"},
    "六合": {"auspicious": "吉", "wuxing": "木", "score": +14, "stock_desc": "量價齊揚、換手順暢"},
    "天后": {"auspicious": "吉", "wuxing": "水", "score": +8,  "stock_desc": "低接買盤暗中承接、下檔有守"},
    "太陰": {"auspicious": "平吉", "wuxing": "金", "score": +5,  "stock_desc": "暗盤籌碼沉澱、狹幅整理"},
    "朱雀": {"auspicious": "平", "wuxing": "火", "score": -4,  "stock_desc": "消息面震盪、短線情緒波動"},
    "勾陳": {"auspicious": "凶", "wuxing": "土", "score": -10, "stock_desc": "籌碼套牢拖延、多空拉鋸"},
    "天空": {"auspicious": "凶", "wuxing": "土", "score": -12, "stock_desc": "虛漲無量、假突破真拉回"},
    "螣蛇": {"auspicious": "凶", "wuxing": "火", "score": -15, "stock_desc": "盤勢詭譎多變、急拉急殺"},
    "玄武": {"auspicious": "大凶", "wuxing": "水", "score": -18, "stock_desc": "主力拉高出貨、暗中調節"},
    "白虎": {"auspicious": "大凶", "wuxing": "金", "score": -22, "stock_desc": "空頭猛烈摜壓、急挫風險"}
}

DAY_GUIREN = {"甲": "丑", "戊": "丑", "庚": "丑", "乙": "子", "己": "子", "丙": "亥", "丁": "亥", "壬": "巳", "癸": "巳", "辛": "午"}
NIGHT_GUIREN = {"甲": "未", "戊": "未", "庚": "未", "乙": "申", "己": "申", "丙": "酉", "丁": "酉", "壬": "卯", "癸": "卯", "辛": "寅"}
BRANCH_CHONG = {"子": "午", "丑": "未", "寅": "申", "卯": "酉", "辰": "戌", "巳": "亥", "午": "子", "未": "丑", "申": "寅", "酉": "卯", "戌": "辰", "亥": "巳"}
BRANCH_XING = {"寅": "巳", "巳": "申", "申": "寅", "丑": "戌", "戌": "未", "未": "丑", "子": "卯", "卯": "子", "辰": "辰", "午": "午", "酉": "酉", "亥": "亥"}
STEM_HE = {"甲": "己", "己": "甲", "乙": "庚", "庚": "乙", "丙": "辛", "辛": "丙", "丁": "壬", "壬": "丁", "戊": "癸", "癸": "戊"}
BRANCH_SANHE_NEXT = {"申": "子", "子": "辰", "辰": "申", "寅": "午", "午": "戌", "戌": "寅", "巳": "酉", "酉": "丑", "丑": "巳", "亥": "卯", "卯": "未", "未": "亥"}
BRANCH_YIMA = {"申": "寅", "子": "寅", "辰": "寅", "寅": "申", "午": "申", "戌": "申", "巳": "亥", "酉": "亥", "丑": "亥", "亥": "巳", "卯": "巳", "未": "巳"}

def wuxing_controls(a: str, b: str) -> bool:
    return {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}.get(a) == b

def wuxing_generates(a: str, b: str) -> bool:
    return {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}.get(a) == b

def get_liuqin(day_stem: str, target_branch_or_stem: str) -> str:
    me_wx = STEM_WUXING[day_stem]
    target_wx = STEM_WUXING.get(target_branch_or_stem) or BRANCH_WUXING[target_branch_or_stem]
    if me_wx == target_wx: return "兄弟"
    if wuxing_generates(target_wx, me_wx): return "父母"
    if wuxing_generates(me_wx, target_wx): return "子孫"
    if wuxing_controls(target_wx, me_wx): return "官鬼"
    if wuxing_controls(me_wx, target_wx): return "妻財"
    return "兄弟"

def get_wangxiang(month_branch: str, target_branch: str) -> Tuple[str, float]:
    m_wx, t_wx = BRANCH_WUXING[month_branch], BRANCH_WUXING[target_branch]
    if m_wx == t_wx: return "旺", 1.30
    if wuxing_generates(m_wx, t_wx): return "相", 1.15
    if wuxing_generates(t_wx, m_wx): return "休", 0.95
    if wuxing_controls(t_wx, m_wx): return "囚", 0.80
    return "死", 0.65

def julian_day(year: int, month: int, day: int, hour: float = 12.0) -> float:
    if month <= 2:
        year -= 1
        month += 12
    a = math.floor(year / 100)
    b = 2 - a + math.floor(a / 4)
    return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + (hour / 24.0) + b - 1524.5

def sun_ecliptic_longitude(jd: float) -> float:
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + 36000.76983 * t + 0.0003032 * t * t) % 360.0
    m = (357.52911 + 35999.05029 * t - 0.0001537 * t * t) % 360.0
    m_rad = math.radians(m)
    c = (1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m_rad) + (0.019993 - 0.000101 * t) * math.sin(2 * m_rad) + 0.000289 * math.sin(3 * m_rad)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    return (true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))) % 360.0

def get_yuejiang_and_month_branch(dt_tw: datetime.datetime) -> Tuple[str, str, str, float]:
    utc_dt = dt_tw - datetime.timedelta(hours=8)
    hour_utc = utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0
    jd = julian_day(utc_dt.year, utc_dt.month, utc_dt.day, hour_utc)
    lon = sun_ecliptic_longitude(jd)
    yj_order = ["亥", "戌", "酉", "申", "未", "午", "巳", "辰", "卯", "寅", "丑", "子"]
    yuejiang = yj_order[int(((lon - 330.0) % 360.0) // 30.0)]
    mb_order = ["寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥", "子", "丑"]
    month_branch = mb_order[int(((lon - 315.0) % 360.0) // 30.0)]
    return yuejiang, YUEJIANG_NAMES[yuejiang], month_branch, round(lon, 2)

def get_four_pillars(dt_tw: datetime.datetime) -> Dict[str, Any]:
    yuejiang, yj_name, month_branch, sun_lon = get_yuejiang_and_month_branch(dt_tw)
    calc_year = dt_tw.year - (1 if (dt_tw.month <= 2 and 200.0 < sun_lon < 315.0) else 0)
    year_stem, year_branch = STEMS[(calc_year - 4) % 10], BRANCHES[(calc_year - 4) % 12]
    yin_month_stem_idx = ((STEMS.index(year_stem) % 5) * 2 + 2) % 10
    m_offset = (BRANCHES.index(month_branch) - BRANCHES.index("寅")) % 12
    month_stem = STEMS[(yin_month_stem_idx + m_offset) % 10]
    day_dt = dt_tw + datetime.timedelta(hours=1) if dt_tw.hour == 23 else dt_tw
    jdn = int(math.floor(julian_day(day_dt.year, day_dt.month, day_dt.day, 12.0) + 0.5))
    day_cycle = (jdn + 49) % 60
    day_stem, day_branch = STEMS[day_cycle % 10], BRANCHES[day_cycle % 12]
    hour_branch_idx = ((dt_tw.hour + 1) // 2) % 12
    hour_branch = BRANCHES[hour_branch_idx]
    hour_stem = STEMS[((STEMS.index(day_stem) % 5) * 2 + hour_branch_idx) % 10]
    xun_start_branch_idx = (BRANCHES.index(day_branch) - STEMS.index(day_stem)) % 12
    kongwang = (BRANCHES[(xun_start_branch_idx - 2) % 12], BRANCHES[(xun_start_branch_idx - 1) % 12])
    return {
        "year_ganzhi": f"{year_stem}{year_branch}", "month_ganzhi": f"{month_stem}{month_branch}",
        "day_ganzhi": f"{day_stem}{day_branch}", "hour_ganzhi": f"{hour_stem}{hour_branch}",
        "year_stem": year_stem, "year_branch": year_branch, "month_stem": month_stem, "month_branch": month_branch,
        "day_stem": day_stem, "day_branch": day_branch, "hour_stem": hour_stem, "hour_branch": hour_branch,
        "yuejiang": yuejiang, "yuejiang_name": yj_name, "sun_longitude": sun_lon, "kongwang": kongwang,
    }

@dataclass
class DaLiuRenChart:
    dt_str: str
    pillars: Dict[str, Any]
    heaven_plate: Dict[str, str]
    generals_plate: Dict[str, str]
    guiren_direction: str
    four_lessons: List[Dict[str, str]]
    three_transmissions: List[Dict[str, Any]]
    method_name: str
    total_score: float
    signal_label: str
    trend_summary: str
    intraday_windows: List[Dict[str, Any]] = field(default_factory=list)
    key_factors: List[str] = field(default_factory=list)

def build_heaven_plate(yuejiang: str, hour_branch: str) -> Dict[str, str]:
    offset = (BRANCHES.index(yuejiang) - BRANCHES.index(hour_branch)) % 12
    return {earth_b: BRANCHES[(i + offset) % 12] for i, earth_b in enumerate(BRANCHES)}

def build_generals_plate(day_stem: str, hour_branch: str, heaven_plate: Dict[str, str]) -> Tuple[Dict[str, str], str]:
    is_day = hour_branch in {"卯", "辰", "巳", "午", "未", "申"}
    guiren_heaven_branch = DAY_GUIREN[day_stem] if is_day else NIGHT_GUIREN[day_stem]
    heaven_to_earth = {h: e for e, h in heaven_plate.items()}
    guiren_earth_branch = heaven_to_earth[guiren_heaven_branch]
    is_forward = guiren_earth_branch in {"亥", "子", "丑", "寅", "卯", "辰"}
    gr_idx = BRANCHES.index(guiren_heaven_branch)
    generals_map = {BRANCHES[(gr_idx + step) % 12 if is_forward else (gr_idx - step) % 12]: gen_name for step, gen_name in enumerate(GENERALS_ORDER)}
    return generals_map, f"{'晝貴' if is_day else '夜貴'}（{guiren_heaven_branch}臨地盤{guiren_earth_branch}・{'順布' if is_forward else '逆布'}）"

def build_four_lessons(day_stem: str, day_branch: str, heaven_plate: Dict[str, str], generals_plate: Dict[str, str]) -> List[Dict[str, str]]:
    k1_top = heaven_plate[STEM_PARASITIC_HOUSE[day_stem]]
    k2_top = heaven_plate[k1_top]
    k3_top = heaven_plate[day_branch]
    k4_top = heaven_plate[k3_top]
    raw_lessons = [
        ("第一課（干陽）", k1_top, day_stem, STEM_WUXING[day_stem]),
        ("第二課（干陰）", k2_top, k1_top, BRANCH_WUXING[k1_top]),
        ("第三課（支陽）", k3_top, day_branch, BRANCH_WUXING[day_branch]),
        ("第四課（支陰）", k4_top, k3_top, BRANCH_WUXING[k3_top]),
    ]
    lessons = []
    for title, top_b, bot_sym, bot_wx in raw_lessons:
        top_wx = BRANCH_WUXING[top_b]
        rel = "下賊上" if wuxing_controls(bot_wx, top_wx) else ("上克下" if wuxing_controls(top_wx, bot_wx) else ("下生上" if wuxing_generates(bot_wx, top_wx) else ("上生下" if wuxing_generates(top_wx, bot_wx) else "比和")))
        lessons.append({"title": title, "top": top_b, "bottom": bot_sym, "top_wuxing": top_wx, "bottom_wuxing": bot_wx, "general": generals_plate[top_b], "liuqin": get_liuqin(day_stem, top_b), "relation": rel})
    return lessons

def calc_shehai_depth(top_branch: str, heaven_to_earth: Dict[str, str], mode: str) -> int:
    start_idx, end_idx = BRANCHES.index(heaven_to_earth[top_branch]), BRANCHES.index(top_branch)
    top_wx = BRANCH_WUXING[top_branch]
    earth_parasitic_stems: Dict[str, List[str]] = {b: [] for b in BRANCHES}
    for s, house in STEM_PARASITIC_HOUSE.items():
        earth_parasitic_stems[house].append(s)
    depth = 0
    for step in range(((end_idx - start_idx) % 12) + 1):
        curr_b = BRANCHES[(start_idx + step) % 12]
        curr_wx = BRANCH_WUXING[curr_b]
        if mode == "下賊上":
            if wuxing_controls(curr_wx, top_wx): depth += 1
            for p_stem in earth_parasitic_stems[curr_b]:
                if wuxing_controls(STEM_WUXING[p_stem], top_wx): depth += 1
        else:
            if wuxing_controls(top_wx, curr_wx): depth += 1
            for p_stem in earth_parasitic_stems[curr_b]:
                if wuxing_controls(top_wx, STEM_WUXING[p_stem]): depth += 1
    return depth

def derive_three_transmissions(day_stem: str, day_branch: str, yuejiang: str, hour_branch: str, heaven_plate: Dict[str, str], four_lessons: List[Dict[str, str]]) -> Tuple[List[str], str]:
    heaven_to_earth = {h: e for e, h in heaven_plate.items()}
    day_yy = STEM_YINYANG[day_stem]
    k1_top, k3_top = four_lessons[0]["top"], four_lessons[2]["top"]
    zeike_down = [ls for ls in four_lessons if ls["relation"] == "下賊上"]
    zeike_up = [ls for ls in four_lessons if ls["relation"] == "上克下"]
    if yuejiang == hour_branch:
        if zeike_down or zeike_up:
            chosen, keti = (zeike_down if zeike_down else zeike_up)[0]["top"], "伏吟課（不虞）"
        else:
            chosen, keti = (k1_top, "伏吟課（自任）") if day_yy == "陽" else (k3_top, "伏吟課（自信）")
        zhong = BRANCH_XING[chosen]
        if zhong == chosen:
            if chosen == k1_top and k3_top != chosen:
                zhong = k3_top
            elif chosen == k3_top and k1_top != chosen:
                zhong = k1_top
            else:
                zhong = BRANCH_CHONG[chosen]
        mo = BRANCH_XING[zhong]
        if mo == zhong or mo == chosen: mo = BRANCH_CHONG[zhong]
        return [chosen, zhong, mo], keti
    is_fanyin = (BRANCH_CHONG[yuejiang] == hour_branch)
    if zeike_down or zeike_up:
        mode = "下賊上" if zeike_down else "上克下"
        unique_cands, seen_tops = [], set()
        for c in (zeike_down if zeike_down else zeike_up):
            if c["top"] not in seen_tops:
                seen_tops.add(c["top"])
                unique_cands.append(c)
        if len(unique_cands) == 1:
            chu = unique_cands[0]["top"]
            keti = f"{'返吟・' if is_fanyin else ''}賊克課（{'重審' if mode == '下賊上' else '元首'}）"
        else:
            biyong_cands = [c for c in unique_cands if BRANCH_YINYANG[c["top"]] == day_yy]
            if len(biyong_cands) == 1:
                chu, keti = biyong_cands[0]["top"], "比用課（知一）"
            else:
                pool = biyong_cands if len(biyong_cands) > 1 else unique_cands
                scored = sorted([(calc_shehai_depth(c["top"], heaven_to_earth, mode), 3 if heaven_to_earth[c["top"]] in MENG_BRANCHES else (2 if heaven_to_earth[c["top"]] in ZHONG_BRANCHES else 1), -idx, c["top"]) for idx, c in enumerate(pool)], reverse=True)
                chu = scored[0][3]
                earth_pos = heaven_to_earth[chu]
                keti = f"涉害課（{'見機' if earth_pos in MENG_BRANCHES else ('察微' if earth_pos in ZHONG_BRANCHES else '綴瑕')}）"
        zhong = heaven_plate[chu]
        return [chu, zhong, heaven_plate[zhong]], keti
    if is_fanyin:
        return [BRANCH_YIMA[day_branch], k3_top, k1_top], "返吟課（井欄射）"
    day_wx = STEM_WUXING[day_stem]
    shen_ke_gan, gan_ke_shen, seen_yk = [], [], set()
    for ls in four_lessons[1:]:
        t_b = ls["top"]
        if t_b not in seen_yk:
            seen_yk.add(t_b)
            if wuxing_controls(ls["top_wuxing"], day_wx): shen_ke_gan.append(t_b)
            elif wuxing_controls(day_wx, ls["top_wuxing"]): gan_ke_shen.append(t_b)
    if shen_ke_gan or gan_ke_shen:
        yk_pool = shen_ke_gan if shen_ke_gan else gan_ke_shen
        by = [b for b in yk_pool if BRANCH_YINYANG[b] == day_yy]
        chu = yk_pool[0] if len(yk_pool) == 1 else (by[0] if by else yk_pool[0])
        zhong = heaven_plate[chu]
        return [chu, zhong, heaven_plate[zhong]], f"遙克課（{'蒿矢' if shen_ke_gan else '彈射'}）"
    distinct_tops = {ls["top"] for ls in four_lessons}
    if k1_top == k3_top:
        chu = BRANCHES[(BRANCHES.index(k1_top) + 2) % 12] if day_yy == "陽" else BRANCHES[(BRANCHES.index(four_lessons[3]["top"]) - 2) % 12]
        return [chu, k1_top, k1_top], "八專課（帷簿）"
    if len(distinct_tops) == 3:
        chu = heaven_plate[STEM_PARASITIC_HOUSE[STEM_HE[day_stem]]] if day_yy == "陽" else BRANCH_SANHE_NEXT[day_branch]
        return [chu, k1_top, k1_top], "別責課（蕪淫）"
    return ([heaven_plate["酉"], k3_top, k1_top], "昴星課（虎視轉蓬）") if day_yy == "陽" else ([heaven_to_earth["酉"], k1_top, k3_top], "昴星課（冬蛇掩目）")

def evaluate_stock_divination(pillars: Dict[str, Any], heaven_plate: Dict[str, str], generals_plate: Dict[str, str], four_lessons: List[Dict[str, str]], trans_branches: List[str], method_name: str) -> Tuple[List[Dict[str, Any]], float, str, str, List[str]]:
    day_stem, month_branch, kongwang = pillars["day_stem"], pillars["month_branch"], pillars["kongwang"]
    liuqin_base_score = {"妻財": +18.0, "子孫": +15.0, "父母": +6.0, "兄弟": -10.0, "官鬼": -16.0}
    stage_names = [("初傳（早盤 09:00–10:30）", 0.45), ("中傳（盤中 10:30–12:00）", 0.30), ("末傳（尾盤 12:00–13:30）", 0.25)]
    trans_details, weighted_trans_score, key_factors = [], 0.0, []
    for i, b in enumerate(trans_branches):
        stage_label, weight = stage_names[i]
        lq, gen = get_liuqin(day_stem, b), generals_plate[b]
        gen_meta = GENERAL_INFO[gen]
        wx_state, wx_mult = get_wangxiang(month_branch, b)
        is_kw = b in kongwang
        base_lq = -14.0 if (is_kw and lq in ("妻財", "子孫")) else (+4.0 if (is_kw and lq in ("官鬼", "兄弟")) else (liuqin_base_score[lq] * 0.4 if is_kw else liuqin_base_score[lq]))
        gen_sc = gen_meta["score"] * (0.5 if is_kw else 1.0)
        raw_stage_score = (base_lq + gen_sc) * wx_mult
        weighted_trans_score += raw_stage_score * weight
        trans_details.append({"stage": stage_label, "branch": b, "wuxing": BRANCH_WUXING[b], "liuqin": lq, "general": gen, "general_auspicious": gen_meta["auspicious"], "wangxiang": wx_state, "kongwang": "空亡" if is_kw else "實支", "stage_score": round(raw_stage_score, 1), "interpretation": f"{lq}乘{gen}（{wx_state}{'・落空亡' if is_kw else ''}）：{gen_meta['stock_desc']}"})
    k1, k3 = four_lessons[0], four_lessons[2]
    k1_gen_score, k3_gen_score = GENERAL_INFO[k1["general"]]["score"] * 0.25, GENERAL_INFO[k3["general"]]["score"] * 0.35
    inter_score = 8.0 if wuxing_generates(k1["top_wuxing"], k3["top_wuxing"]) else (10.0 if wuxing_generates(k3["top_wuxing"], k1["top_wuxing"]) else (-10.0 if wuxing_controls(k3["top_wuxing"], k1["top_wuxing"]) else (4.0 if wuxing_controls(k1["top_wuxing"], k3["top_wuxing"]) else 0.0)))
    w0, w1, w2 = [BRANCH_WUXING[b] for b in trans_branches]
    if wuxing_generates(w0, w1) and wuxing_generates(w1, w2): inter_score += 12.0
    elif wuxing_controls(w0, w1) and wuxing_controls(w1, w2): inter_score -= 12.0
    total_score = max(-100.0, min(100.0, round(weighted_trans_score * 1.6 + k1_gen_score + k3_gen_score + inter_score, 1)))
    signal = "🟢 強烈買進" if total_score >= 30 else ("🟢 偏多布局" if total_score >= 10 else ("🟡 區間觀望" if total_score > -10 else ("🟠 逢高減碼" if total_score > -30 else "🔴 偏空避險")))
    return trans_details, total_score, signal, f"課體屬【{method_name}】", key_factors

def evaluate_intraday_windows(target_date: datetime.date, day_chart_score: float) -> List[Dict[str, Any]]:
    windows_spec = [("巳時", "09:00 – 11:00", 9, 30, "開盤早盤動能期"), ("午時", "11:00 – 13:00", 11, 30, "盤中換手轉折期"), ("未時", "13:00 – 13:30", 13, 15, "尾盤收盤定調期")]
    results = []
    for shichen, time_range, hr, mn, phase_desc in windows_spec:
        dt = datetime.datetime(target_date.year, target_date.month, target_date.day, hr, mn)
        pillars = get_four_pillars(dt)
        hp = build_heaven_plate(pillars["yuejiang"], pillars["hour_branch"])
        gp, _ = build_generals_plate(pillars["day_stem"], pillars["hour_branch"], hp)
        fl = build_four_lessons(pillars["day_stem"], pillars["day_branch"], hp, gp)
        tb, m_name = derive_three_transmissions(pillars["day_stem"], pillars["day_branch"], pillars["yuejiang"], pillars["hour_branch"], hp, fl)
        td, sc, _, _, _ = evaluate_stock_divination(pillars, hp, gp, fl, tb, m_name)
        chu, k3 = td[0], fl[2]
        action = "🟢 買進／加碼良機" if sc >= 18 else ("🟢 逢低承接／續抱" if sc >= 5 else ("🟡 觀望守候" if sc > -8 else ("🟠 逢高獲利調節" if sc > -22 else "🔴 減碼避險")))
        results.append({"shichen": shichen, "time_range": time_range, "phase_desc": phase_desc, "hour_ganzhi": pillars["hour_ganzhi"], "method_name": m_name, "san_chuan": f"{tb[0]}→{tb[1]}→{tb[2]}", "chu_general": f"{chu['branch']}乘{chu['general']}", "stock_branch_top": f"{k3['top']}乘{k3['general']}({k3['liuqin']})", "score": sc, "action": action, "detail": chu["interpretation"]})
    return results

def cast_daily_tsmc_chart(target_dt: Optional[datetime.datetime] = None, include_intraday: bool = False) -> DaLiuRenChart:
    if target_dt is None:
        now_tw = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)
        target_dt = datetime.datetime(now_tw.year, now_tw.month, now_tw.day, 9, 0, 0)
    pillars = get_four_pillars(target_dt)
    heaven_plate = build_heaven_plate(pillars["yuejiang"], pillars["hour_branch"])
    generals_plate, guiren_dir = build_generals_plate(pillars["day_stem"], pillars["hour_branch"], heaven_plate)
    four_lessons = build_four_lessons(pillars["day_stem"], pillars["day_branch"], heaven_plate, generals_plate)
    trans_branches, method_name = derive_three_transmissions(pillars["day_stem"], pillars["day_branch"], pillars["yuejiang"], pillars["hour_branch"], heaven_plate, four_lessons)
    trans_details, total_score, signal_label, trend_summary, key_factors = evaluate_stock_divination(pillars, heaven_plate, generals_plate, four_lessons, trans_branches, method_name)
    intraday_windows = evaluate_intraday_windows(target_dt.date(), total_score) if include_intraday else []
    return DaLiuRenChart(dt_str=target_dt.strftime("%Y-%m-%d %H:%M"), pillars=pillars, heaven_plate=heaven_plate, generals_plate=generals_plate, guiren_direction=guiren_dir, four_lessons=four_lessons, three_transmissions=trans_details, method_name=method_name, total_score=total_score, signal_label=signal_label, trend_summary=trend_summary, intraday_windows=intraday_windows, key_factors=key_factors)
