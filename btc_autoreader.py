#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比特幣 (BTC/USDT) 大六壬 v11.0「一辰三傳・每40分鐘判斷1次（單時辰3次決策）」全自動下單機器人 (btc_autotrader.py)
================================================================================================================
升級亮點 (v11.0 3-Phase SanChuan Progressive Engine)：
  1. 每個時辰（120 分鐘）拆為 3 段，每 40 分鐘執行 1 次（台灣時間奇數點 01分、41分，偶數點 21分）：
     - Phase 0 [1st-Chuan 00-40m 初傳發用]：氣機起勢，符合條件建立 50%~55% 部位
     - Phase 1 [2nd-Chuan 40-80m 中傳移易]：空手可半路切入；若持倉且中傳同向生旺+浮盈則順勢加碼至 65%；若中傳逢空亡且虧損逾 -0.55% 提早停損逃命
     - Phase 2 [3rd-Chuan 80-120m 末傳歸計]：末傳逢空亡絕不開新倉；若持倉遇末傳空亡且浮盈 >= +0.35% 立即提前落袋鎖利！
  2. 純英文終端機輸出 (Web Console 零亂碼)，內建免金鑰公開即時 K 線 (OKX / Kraken / Coinbase / Gate) 與五大風控鎖。
"""

import datetime
import json
import os
import sys
from typing import Dict, Any, Optional, List
from btc_strategy import evaluate_btc_signal

_EN_MAP = {
    "甲": "Jia", "乙": "Yi", "丙": "Bing", "丁": "Ding", "戊": "Wu",
    "己": "Ji", "庚": "Geng", "辛": "Xin", "壬": "Ren", "癸": "Gui",
    "子": "Zi", "丑": "Chou", "寅": "Yin", "卯": "Mao", "辰": "Chen", "巳": "Si",
    "午": "Wu", "未": "Wei", "申": "Shen", "酉": "You", "戌": "Xu", "亥": "Hai",
    "妻財": "Wealth", "官鬼": "Ghost", "子孫": "Offspring", "父母": "Parent", "兄弟": "Sibling",
    "開門": "Open-Door", "休門": "Rest-Door", "生門": "Life-Door", "傷門": "Harm-Door",
    "杜門": "Delusion-Door", "景門": "Scenery-Door", "死門": "Death-Door", "驚門": "Fear-Door",
    "天蓬": "TianPeng", "天任": "TianRen", "天沖": "TianChong", "天輔": "TianFu",
    "天英": "TianYing", "天芮": "TianRui", "天柱": "TianZhu", "天心": "TianXin", "天禽": "TianQin",
    "值符": "ZhiFu", "螣蛇": "TengShe", "太陰": "TaiYin", "六合": "LiuHe",
    "白虎": "BaiHu", "玄武": "XuanWu", "九地": "JiuDi", "九天": "JiuTian",
    "貴人": "GuiRen", "青龍": "QingLong", "太常": "TaiChang", "天空": "TianKong",
    "勾陳": "GouChen", "朱雀": "ZhuQue", "天后": "TianHou",
    "初傳": "1st:", "中傳": "2nd:", "末傳": "3rd:", "時": "-Hour",
    "空亡": "Void", "實": "Solid",
    "評分": "Score", "五不遇時": "WuBuYuShi", "→": "->", "・": " / ", "（": "(", "）": ")",
}


def to_en(text: str) -> str:
    for k in sorted(_EN_MAP.keys(), key=len, reverse=True):
        text = text.replace(k, _EN_MAP[k])
    return text


STATE_FILE = os.environ.get("BTC_STATE_FILE", "btc_bot_state.json")


def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "position": None,          # None / "LONG" / "SHORT"
        "entry_price": 0.0,
        "amount": 0.0,
        "pos_pct": 0.50,
        "scaled": False,
        "entry_time_utc": None,
        "tp_price": 0.0,
        "sl_price": 0.0,
        "daily_date": "",
        "daily_pnl_pct": 0.0,
        "halted_until_utc": None,
        "trade_history": [],
    }


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_exchange():
    import ccxt
    exchange_id = os.environ.get("EXCHANGE_ID", "binanceusdm").lower()
    api_key = os.environ.get("EXCHANGE_API_KEY", "")
    api_secret = os.environ.get("EXCHANGE_API_SECRET", "")
    use_testnet = os.environ.get("USE_TESTNET", "true").lower() == "true"

    ex_class = getattr(ccxt, exchange_id)
    ex = ex_class({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
    if use_testnet:
        ex.set_sandbox_mode(True)
    return ex


def fetch_btc_40m_closes(exchange=None) -> List[float]:
    """
    抓取最新 5 分鐘 K 線並每 8 根合成 1 根 40 分鐘（一傳）K 線；若無則降級抓 1h/2h K 線
    """
    if exchange is not None:
        try:
            ohlcv_5m = exchange.fetch_ohlcv("BTC/USDT:USDT", timeframe="5m", limit=520)
            if ohlcv_5m and len(ohlcv_5m) >= 200:
                closes_5m = [float(bar[4]) for bar in ohlcv_5m]
                closes_40m = closes_5m[7::8]
                if closes_40m[-1] != closes_5m[-1]:
                    closes_40m.append(closes_5m[-1])
                return closes_40m[-65:]
        except Exception as e:
            print(f"[WARN] CCXT authenticated 5m/40m fetch failed: {e}")

    try:
        import ccxt
        for ex_id, sym in [("okx", "BTC/USDT"), ("kraken", "BTC/USD"), ("coinbase", "BTC/USD"), ("gate", "BTC/USDT")]:
            try:
                pub_ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
                ohlcv_5m = pub_ex.fetch_ohlcv(sym, timeframe="5m", limit=520)
                if ohlcv_5m and len(ohlcv_5m) >= 200:
                    closes_5m = [float(bar[4]) for bar in ohlcv_5m]
                    closes_40m = closes_5m[7::8]
                    if closes_40m[-1] != closes_5m[-1]:
                        closes_40m.append(closes_5m[-1])
                    print(f"[PUBLIC FEED] Loaded live 40m (SanChuan) candles from {ex_id.upper()} ({sym})")
                    return closes_40m[-65:]
            except Exception:
                continue
    except Exception:
        pass

    base = 64012.79
    return [round(base * (1.0 + ((i % 7) - 3) * 0.0025), 2) for i in range(65)]


def run_bot_cycle(
    dry_run: bool = True,
    simulated_closes: Optional[List[float]] = None,
    simulated_dt_tw: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    today_str = now_utc.strftime("%Y-%m-%d")
    state = load_state()

    if state.get("daily_date") != today_str:
        state["daily_date"] = today_str
        state["daily_pnl_pct"] = 0.0

    if state.get("halted_until_utc"):
        halt_dt = datetime.datetime.fromisoformat(state["halted_until_utc"])
        if now_utc < halt_dt:
            msg = f"[CIRCUIT BREAKER] Trading halted until {halt_dt.isoformat()} UTC"
            print(msg)
            return {"action": "HALTED", "message": msg}
        state["halted_until_utc"] = None

    exchange = None if dry_run else get_exchange()
    closes = simulated_closes if simulated_closes is not None else fetch_btc_40m_closes(exchange)
    sig = evaluate_btc_signal(closes, simulated_dt_tw)
    curr_p = sig["price"]
    leverage = int(os.environ.get("LEVERAGE", "1"))
    daily_loss_limit = float(os.environ.get("DAILY_MAX_LOSS_PCT", "-3.0"))

    mode_lbl = "[PAPER / DRY-RUN]" if dry_run else "[LIVE / TESTNET]"
    print("=" * 76)
    print(f"[BTC/USDT DaLiuRen v11.0 3-Phase AutoTrader] {mode_lbl}")
    print(f"Shichen: {to_en(sig['shichen'])} | Phase: {sig['phase_en']} | Active: {to_en(sig['active_chuan'])}")
    print(f"Price: ${curr_p:,.2f} | 20MA: ${sig['ma20']:,.2f} | RSI5: {sig['rsi5']}")
    print(f"SanChuan: {to_en(sig['sanchuan'])} | QiMen: {to_en(sig['qimen'])}")
    print(f"Fire-Resonance: {sig['el_score']:+.1f} | Phase Signal: {sig['signal']}")
    print("=" * 76)

    # 1. 若目前持有倉位，先檢查「三傳動態加減碼 / 末傳空亡提前鎖利 / 中傳空亡緊縮停損 / 停利停損 / 滿4小時(6傳)平倉」
    if state["position"] is not None:
        pos = state["position"]
        ep = state["entry_price"]
        pos_pct = float(state.get("pos_pct", 0.50))
        entry_dt = datetime.datetime.fromisoformat(state["entry_time_utc"])
        held_hours = (now_utc - entry_dt).total_seconds() / 3600.0
        raw_ret = ((curr_p - ep) / ep) if pos == "LONG" else ((ep - curr_p) / ep)

        # (A) 中傳 (Phase 1) 順勢加碼檢查
        if (not state.get("scaled", False)) and raw_ret > 0.0015:
            if (pos == "LONG" and sig["scale_long_ok"]) or (pos == "SHORT" and sig["scale_short_ok"]):
                state["pos_pct"] = 0.65
                state["scaled"] = True
                pos_pct = 0.65
                print(f"[2ND-CHUAN SCALE-UP] {pos} supported by 2nd-Chuan; position scaled up to 65%!")

        # (B) 檢查各項出場條件
        hit_tp = (pos == "LONG" and curr_p >= state["tp_price"]) or (pos == "SHORT" and curr_p <= state["tp_price"])
        hit_sl = (pos == "LONG" and curr_p <= state["sl_price"]) or (pos == "SHORT" and curr_p >= state["sl_price"])
        hit_time = held_hours >= 3.95  # 滿 6 傳 (4 小時 = 2 個時辰)
        opp_reversal = (pos == "LONG" and sig["signal"] == "SHORT") or (pos == "SHORT" and sig["signal"] == "LONG")
        kw_lock = sig["kw_lock_profit"] and (raw_ret >= 0.0035)
        tight_sl = sig["tight_stop_middle"] and (raw_ret <= -0.0055)

        if hit_tp or hit_sl or hit_time or opp_reversal or kw_lock or tight_sl:
            if hit_tp:
                reason = "Take-Profit (+1.5%)"
            elif kw_lock:
                reason = "3rd-Chuan Void Profit-Lock (末傳空亡提前鎖利)"
            elif tight_sl:
                reason = "2nd-Chuan Void Tight-Stop (中傳空亡提早逃命)"
            elif opp_reversal:
                reason = f"SanChuan Signal Reversal -> {sig['signal']}"
            elif hit_sl:
                reason = "Stop-Loss (-0.9%)"
            else:
                reason = "6-Chuan (4H) Time-Stop"

            net_ret_pct = round((raw_ret - 0.0006) * 100.0 * pos_pct * leverage, 3)

            if not dry_run and exchange is not None:
                close_side = "sell" if pos == "LONG" else "buy"
                exchange.cancel_all_orders("BTC/USDT:USDT")
                exchange.create_market_order("BTC/USDT:USDT", close_side, state["amount"], params={"reduceOnly": True})

            state["daily_pnl_pct"] = round(state["daily_pnl_pct"] + net_ret_pct, 3)
            state["trade_history"].append({
                "side": pos, "entry": ep, "exit": curr_p, "pnl_pct": net_ret_pct,
                "reason": to_en(reason), "time_utc": now_utc.isoformat()
            })
            state["position"] = None
            state["entry_price"] = 0.0
            state["amount"] = 0.0
            state["pos_pct"] = 0.50
            state["scaled"] = False
            state["entry_time_utc"] = None

            if state["daily_pnl_pct"] <= daily_loss_limit:
                state["halted_until_utc"] = (now_utc + datetime.timedelta(hours=24)).isoformat()
                print(f"[CIRCUIT BREAKER] Daily PnL {state['daily_pnl_pct']}% hit limit, halting 24h!")

            save_state(state)
            print(f"[CLOSED] {pos} @ ${ep:,.2f} -> ${curr_p:,.2f} | Reason: {to_en(reason)} | Net PnL: {net_ret_pct:+.3f}%")
            return {"action": f"CLOSE_{pos}", "reason": to_en(reason), "pnl_pct": net_ret_pct}
        else:
            print(f"[HOLDING] {pos} ({int(pos_pct*100)}%) @ ${ep:,.2f} (Held {held_hours:.1f}h | TP=${state['tp_price']} / SL=${state['sl_price']})")
            save_state(state)
            return {"action": f"HOLD_{pos}"}

    # 2. 若空手且當傳出現明確 LONG / SHORT 訊號（且非末傳空亡），自動開倉
    if sig["signal"] in ("LONG", "SHORT"):
        side = sig["signal"]
        pos_pct = float(sig.get("recommended_size_pct", 0.50))
        usdt_balance = 10000.0
        if not dry_run and exchange is not None:
            bal = exchange.fetch_balance()
            usdt_balance = float(bal["total"].get("USDT", 0.0))
            exchange.set_leverage(leverage, "BTC/USDT:USDT")

        alloc_usdt = usdt_balance * pos_pct * leverage
        qty = round(alloc_usdt / curr_p, 3)
        if qty <= 0:
            print("[WARN] Balance below min order size (0.001 BTC), skipping.")
            return {"action": "SKIP_LOW_BALANCE"}

        if not dry_run and exchange is not None:
            order_side = "buy" if side == "LONG" else "sell"
            close_side = "sell" if side == "LONG" else "buy"
            exchange.create_market_order("BTC/USDT:USDT", order_side, qty)
            exchange.create_order("BTC/USDT:USDT", "TAKE_PROFIT_MARKET", close_side, qty, params={"stopPrice": sig["tp_price"], "reduceOnly": True})
            exchange.create_order("BTC/USDT:USDT", "STOP_MARKET", close_side, qty, params={"stopPrice": sig["sl_price"], "reduceOnly": True})

        state["position"] = side
        state["entry_price"] = curr_p
        state["amount"] = qty
        state["pos_pct"] = pos_pct
        state["scaled"] = (pos_pct > 0.50)
        state["entry_time_utc"] = now_utc.isoformat()
        state["tp_price"] = sig["tp_price"]
        state["sl_price"] = sig["sl_price"]
        save_state(state)
        print(f"[OPENED] {side} {qty} BTC ({int(pos_pct*100)}% alloc) @ ${curr_p:,.2f} | Phase: {sig['phase_en']} | TP=${sig['tp_price']:,.2f} / SL=${sig['sl_price']:,.2f}")
        return {"action": f"OPEN_{side}", "qty": qty, "price": curr_p}

    save_state(state)
    print(f"[WAIT] No entry in {sig['phase_en']}; staying 100% USDT cash.")
    return {"action": "WAIT"}


if __name__ == "__main__":
    is_dry = os.environ.get("DRY_RUN", "true").lower() == "true"
    run_bot_cycle(dry_run=is_dry)
