#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比特幣 (BTC/USD) 專屬大六壬十二時辰 × 一辰三傳（每40分鐘一傳）× 奇門 × 離火共振策略模組 (btc_strategy.py v11.0)
========================================================================================================
支援兩種決策頻率（預設啟用 v11.0 一辰三傳 40 分鐘三段式遞進聯動）：
  - 初傳・發用 (00–40m, phase 0)：氣機初動，決定首波建倉（若中傳亦同向生扶則提高初始部位至 55%）
  - 中傳・移易 (40–80m, phase 1)：氣機轉折，空手可半路切入；持倉若同向生旺且浮盈則順勢加碼至 65%；若中傳逢空亡則收緊停損至 -0.55%
  - 末傳・歸計 (80–120m, phase 2)：時辰收尾，「末傳空亡，事終無成」— 末傳空亡絕不開新倉，且若帳面浮盈 >= +0.35% 立即提前落袋鎖利！
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


def get_shichen_phase(dt_tw: datetime.datetime) -> Dict[str, Any]:
    """
    計算當前台灣時間處於該時辰的第幾分鐘與對應三傳段落：
      - 奇數整點 (01, 03, 05, ..., 23) 為時辰起點 (第 0 分鐘)
      - 00–39 分鐘 -> phase_idx = 0 (初傳・發用 1st-Chuan)
      - 40–79 分鐘 -> phase_idx = 1 (中傳・移易 2nd-Chuan)
      - 80–119 分鐘 -> phase_idx = 2 (末傳・歸計 3rd-Chuan)
    """
    mins = dt_tw.minute if (dt_tw.hour % 2 == 1) else (60 + dt_tw.minute)
    if mins < 40:
        return {"phase_idx": 0, "mins": mins, "phase_zh": "初傳・發用(00-40m)", "phase_en": "1st-Chuan(00-40m)"}
    elif mins < 80:
        return {"phase_idx": 1, "mins": mins, "phase_zh": "中傳・移易(40-80m)", "phase_en": "2nd-Chuan(40-80m)"}
    else:
        return {"phase_idx": 2, "mins": mins, "phase_zh": "末傳・歸計(80-120m)", "phase_en": "3rd-Chuan(80-120m)"}


def evaluate_btc_signal(closes: List[float], dt_tw: datetime.datetime = None) -> Dict[str, Any]:
    """
    輸入 K 線收盤價序列，依當前時辰落點（初傳/中傳/末傳）回傳 v11.0 三段式遞進交易訊號與動態風控參數
    """
    if dt_tw is None:
        dt_tw = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)

    curr_p = closes[-1]
    ma_len = min(60, len(closes)) if len(closes) >= 60 else min(20, len(closes))
    ma20 = sum(closes[-ma_len:]) / float(ma_len)
    ma20_prev = sum(closes[-ma_len - 5:-5]) / float(ma_len) if len(closes) >= (ma_len + 5) else ma20
    slope = (ma20 - ma20_prev) / ma20_prev * 100.0

    gains, losses = [], []
    for j in range(len(closes) - 5, len(closes)):
        d = closes[j] - closes[j - 1]
        if d > 0:
            gains.append(d)
        else:
            losses.append(-d)
    rsi5 = 100.0 if sum(losses) == 0 else 100.0 - (100.0 / (1.0 + (sum(gains) / 5.0) / (sum(losses) / 5.0)))

    chart = cast_daily_tsmc_chart(dt_tw)
    q = calc_shichen_qimen(chart)
    res_el = calc_btc_fire_resonance(chart)
    el_score = res_el["el_score"]
    ph = get_shichen_phase(dt_tw)
    phase_idx = ph["phase_idx"]

    tt = chart.three_transmissions
    lqs = [t["liuqin"] for t in tt]
    gens = [t["general"] for t in tt]
    kws = [t["kongwang"] == "空亡" for t in tt]

    lq_curr = lqs[phase_idx]
    gen_curr = gens[phase_idx]
    kw_curr = kws[phase_idx]

    bull_trap = (lq_curr == "妻財" and kw_curr) or (lq_curr == "父母" and gen_curr in ("螣蛇", "玄武"))
    long_sig = (not bull_trap) and (not q["wubuyushi"]) and q["good_door"] and (q["q_score"] >= 15) and (el_score >= -3.0) and (
        lq_curr in ("妻財", "子孫", "父母") and not kw_curr
    ) and (curr_p >= ma20 * 0.996 or rsi5 <= 30.0)

    short_sig = (not long_sig) and (slope < 0.25) and (el_score <= 5.0) and (
        (q["door"] in ("死門", "驚門") or q["wubuyushi"]) and (lq_curr in ("官鬼", "兄弟") or gen_curr in ("白虎", "玄武"))
    ) and (curr_p < ma20 * 1.002) and (rsi5 >= 28.0)

    # 末傳逢空亡（「末傳空亡，事終無成」）絕不追高開新倉
    if phase_idx == 2 and kw_curr:
        long_sig = False
        short_sig = False

    signal = "LONG" if long_sig else ("SHORT" if short_sig else "HOLD")
    tp_pct = 0.015   # v11.0 三傳模式停利 +1.5%
    sl_pct = 0.009   # v11.0 三傳模式停損 -0.9%

    if signal == "LONG":
        tp_price = round(curr_p * (1.0 + tp_pct), 2)
        sl_price = round(curr_p * (1.0 - sl_pct), 2)
        rec_size = 0.55 if (phase_idx == 0 and lqs[1] in ("妻財", "子孫") and not kws[1]) else 0.50
    elif signal == "SHORT":
        tp_price = round(curr_p * (1.0 - tp_pct), 2)
        sl_price = round(curr_p * (1.0 + sl_pct), 2)
        rec_size = 0.55 if (phase_idx == 0 and lqs[1] in ("官鬼", "兄弟") and not kws[1]) else 0.50
    else:
        tp_price, sl_price, rec_size = 0.0, 0.0, 0.0

    # 中傳順勢加碼條件與末傳空亡提前鎖利標記
    scale_long_ok = (phase_idx == 1) and (lq_curr in ("妻財", "子孫", "父母") and not kw_curr)
    scale_short_ok = (phase_idx == 1) and (lq_curr in ("官鬼", "兄弟") and not kw_curr)
    kw_lock_profit = (phase_idx == 2) and kw_curr
    tight_stop_middle = (phase_idx == 1) and kw_curr

    active_chuan_str = f"{['初傳','中傳','末傳'][phase_idx]}{tt[phase_idx]['branch']}({lq_curr}/{gen_curr}/{'空亡' if kw_curr else '實'})"

    return {
        "signal": signal,
        "shichen": f"{chart.pillars['hour_ganzhi']}（{q['hour_branch']}時）",
        "phase_idx": phase_idx,
        "phase_en": ph["phase_en"],
        "phase_zh": ph["phase_zh"],
        "active_chuan": active_chuan_str,
        "curr_kw": kw_curr,
        "recommended_size_pct": rec_size,
        "scale_long_ok": scale_long_ok,
        "scale_short_ok": scale_short_ok,
        "kw_lock_profit": kw_lock_profit,
        "tight_stop_middle": tight_stop_middle,
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
