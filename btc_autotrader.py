#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比特幣 (BTC/USDT) 大六壬 v13.3 實盤加固版全自動交易機器人 (btc_autotrader.py)
=============================================================================
已修復之 4 大程式隱患 + 4 大策略微調：
  [FIX 1] 移除寫死假價格備援：若所有行情源皆暫時斷線，安全跳過本輪巡檢，絕不誤砍真實倉位。
  [FIX 2] 保護單重試＋原子寫檔 (Atomic JSON Write)：加碼/開倉掛 TP/SL 具備自動重試保護，避免倉位裸奔與狀態檔損毀。
  [FIX 3] 真實成交均價對齊：實盤開倉採用交易所真實成交均價，同步平倉時查詢真實成交紀錄 (fetch_my_trades) 精算當日熔斷損益。
  [FIX 4] 統一 300 根 5m 均線窗口＋精簡 STANDBY 日誌，避免 VPS 硬碟被日誌塞爆。
  [UPGRADE] 整合「皇極經世立春軟加權」＋「ATR 動態停利停損」＋「保本移動停損 (+1.00% 鎖死 +0.10%)」＋「RSI 極端防呆」。
"""

import datetime
import json
import os
import sys
import time
from typing import Dict, Any, Optional, List, Tuple
from btc_strategy import evaluate_btc_signal

SYMBOL = os.environ.get("TRADING_SYMBOL", "BTC/USDT:USDT")
STATE_FILE = os.environ.get("BTC_STATE_FILE", "btc_bot_state.json")

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


def default_flat_fields() -> Dict[str, Any]:
    return {
        "position": None,
        "entry_price": 0.0,
        "amount": 0.0,
        "pos_pct": 0.50,
        "scaled": False,
        "breakeven_armed": False,
        "entry_time_utc": None,
        "tp_price": 0.0,
        "sl_price": 0.0,
        "tp_pct": 0.015,
        "sl_pct": 0.009,
        "max_hold_h": 4.0,
    }


def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in default_flat_fields().items():
            data.setdefault(k, v)
        return data
    state = default_flat_fields()
    state.update({
        "daily_date": "",
        "daily_pnl_pct": 0.0,
        "halted_until_utc": None,
        "trade_history": [],
    })
    return state


def save_state(state: Dict[str, Any]) -> None:
    """原子寫入狀態檔，避免寫入中斷造成 JSON 損毀"""
    tmp_path = f"{STATE_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, STATE_FILE)


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


def place_protective_orders(exchange, side: str, qty: float, tp_price: float, sl_price: float, retries: int = 2) -> bool:
    """掛出交易所原生減倉停利與停損條件單（具備自動重試保護）"""
    close_side = "sell" if side == "LONG" else "buy"
    for attempt in range(1, retries + 1):
        try:
            exchange.create_order(
                SYMBOL, "TAKE_PROFIT_MARKET", close_side, qty,
                params={"stopPrice": tp_price, "reduceOnly": True},
            )
            exchange.create_order(
                SYMBOL, "STOP_MARKET", close_side, qty,
                params={"stopPrice": sl_price, "reduceOnly": True},
            )
            return True
        except Exception as e:
            print(f"[WARN] place_protective_orders attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(1.0)
    return False


def fetch_live_position(exchange, expected_side: str) -> Tuple[bool, float, float]:
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for p in positions:
            sym = p.get("symbol", "")
            if sym and SYMBOL.split(":")[0] not in sym:
                continue
            contracts = float(p.get("contracts") or 0.0)
            info_amt = float((p.get("info") or {}).get("positionAmt", 0.0) or 0.0)
            qty = abs(contracts) if abs(contracts) > 0 else abs(info_amt)
            if qty <= 0:
                continue
            p_side = (p.get("side") or "").upper()
            if not p_side and info_amt != 0:
                p_side = "LONG" if info_amt > 0 else "SHORT"
            if p_side in ("LONG", "SHORT") and p_side != expected_side:
                continue
            ep = float(p.get("entryPrice") or 0.0)
            return True, round(qty, 3), ep
        return False, 0.0, 0.0
    except Exception as e:
        print(f"[WARN] Failed to fetch live positions: {e}")
        return True, -1.0, 0.0


def fetch_last_fill_price(exchange, fallback_price: float) -> float:
    """查詢交易所最近一筆真實成交均價，確保損益與單日熔斷精準"""
    try:
        trades = exchange.fetch_my_trades(SYMBOL, limit=5)
        if trades:
            last_p = float(trades[-1].get("price") or 0.0)
            if last_p > 0:
                return last_p
    except Exception as e:
        print(f"[WARN] fetch_my_trades fallback triggered: {e}")
    return fallback_price


def fetch_btc_5m_closes(exchange=None) -> Optional[List[float]]:
    """
    統一抓取 300 根 5m K 線 (25 小時)。
    [FIX 1] 若所有來源皆暫時斷線，回傳 None 安全跳過本輪，絕不回傳寫死的假價格！
    """
    if exchange is not None:
        try:
            ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe="5m", limit=320)
            if ohlcv and len(ohlcv) >= 120:
                return [float(bar[4]) for bar in ohlcv][-300:]
        except Exception as e:
            print(f"[WARN] CCXT authenticated 5m fetch failed: {e}")

    try:
        import ccxt
        for ex_id, sym in [("okx", "BTC/USDT"), ("kraken", "BTC/USD"), ("coinbase", "BTC/USD"), ("gate", "BTC/USDT")]:
            try:
                pub_ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
                ohlcv = pub_ex.fetch_ohlcv(sym, timeframe="5m", limit=320)
                if ohlcv and len(ohlcv) >= 120:
                    return [float(bar[4]) for bar in ohlcv][-300:]
            except Exception:
                continue
    except Exception:
        pass

    return None


def run_bot_cycle(
    dry_run: bool = True,
    force_eval: bool = False,
    simulated_closes: Optional[List[float]] = None,
    simulated_dt_tw: Optional[datetime.datetime] = None,
    exchange_override: Any = None,
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

    exchange = exchange_override if exchange_override is not None else (None if dry_run else get_exchange())
    closes_5m = simulated_closes if simulated_closes is not None else fetch_btc_5m_closes(exchange)

    if closes_5m is None or len(closes_5m) < 60:
        msg = f"[ABORT {now_utc.strftime('%H:%M UTC')}] Live market data unavailable across all feeds; skipping cycle safely (existing exchange orders untouched)."
        print(msg)
        return {"action": "ABORT_NO_DATA", "message": msg}

    sig = evaluate_btc_signal(closes_5m, simulated_dt_tw, force_eval=force_eval)
    curr_p = sig["price"]
    leverage = int(os.environ.get("LEVERAGE", "1"))
    daily_loss_limit = float(os.environ.get("DAILY_MAX_LOSS_PCT", "-3.0"))

    # [FIX 4] 空手且非應期分鐘時，只印出精簡 1 行日誌，避免 bot.log 無限膨脹
    if state["position"] is None and not sig["is_eval_minute"]:
        print(
            f"[STANDBY {now_utc.strftime('%m-%d %H:%M UTC')}] {to_en(sig['shichen'])} Min {sig['raw_mins']}m | "
            f"BTC ${curr_p:,.2f} | {sig['huangji_tag']} | Next YingQi: {sig['next_minutes']}"
        )
        save_state(state)
        return {"action": "STANDBY"}

    mode_lbl = "[PAPER / DRY-RUN]" if dry_run else "[LIVE / TESTNET]"
    print("=" * 84)
    print(f"[BTC/USDT DaLiuRen v13.3 Hardened AutoTrader] {mode_lbl} ({now_utc.strftime('%Y-%m-%d %H:%M UTC')})")
    print(f"Shichen: {to_en(sig['shichen'])} | Min: {sig['raw_mins']}m (Slot {sig['slot_5m']}m) | Mode: {sig['sched_mode_en']}")
    print(f"HuangJi (LiChun Soft): {sig['huangji_tag']} | ATR-Mult: {sig['atr_mult']}x (TP {sig['tp_pct']*100:.2f}% / SL {sig['sl_pct']*100:.2f}%)")
    print(f"Price: ${curr_p:,.2f} | MA120(10H): ${sig['ma20']:,.2f} | 15m-Mom: {sig['mom_15m_pct']:+.2f}% | RSI(1H): {sig['rsi_1h']}")
    print(f"SanChuan: {to_en(sig['sanchuan'])} | QiMen: {to_en(sig['qimen'])}")
    print(f"Fire-Resonance: {sig['el_score']:+.1f} | Trigger: {to_en(sig['active_chuan'])} | Signal: {sig['signal']}")
    print("=" * 84)

    # 1. 若目前持有倉位：先同步交易所 -> 檢查保本移動停損 -> 檢查應期加碼 -> 檢查各類平倉條件
    if state["position"] is not None:
        pos = state["position"]
        ep = float(state["entry_price"])
        pos_pct = float(state.get("pos_pct", 0.50))

        # 1a. 實盤同步檢查
        if not dry_run and exchange is not None:
            is_open, live_qty, live_ep = fetch_live_position(exchange, pos)
            if not is_open:
                try:
                    exchange.cancel_all_orders(SYMBOL)
                except Exception as e:
                    print(f"[WARN] cancel_all_orders after exchange close failed: {e}")

                est_fallback = float(state["tp_price"]) if abs(curr_p - state["tp_price"]) <= abs(curr_p - state["sl_price"]) else float(state["sl_price"])
                real_exit = fetch_last_fill_price(exchange, est_fallback if est_fallback > 0 else curr_p)
                sync_reason = "Exchange TP/SL Filled (Realized Fill)"
                raw_ret_sync = ((real_exit - ep) / ep) if pos == "LONG" else ((ep - real_exit) / ep)
                net_ret_pct = round((raw_ret_sync - 0.0006) * 100.0 * pos_pct * leverage, 3)

                state["daily_pnl_pct"] = round(state["daily_pnl_pct"] + net_ret_pct, 3)
                state["trade_history"].append({
                    "side": pos, "entry": ep, "exit": real_exit, "pnl_pct": net_ret_pct,
                    "reason": sync_reason, "time_utc": now_utc.isoformat(),
                })
                state.update(default_flat_fields())
                if state["daily_pnl_pct"] <= daily_loss_limit:
                    state["halted_until_utc"] = (now_utc + datetime.timedelta(hours=24)).isoformat()
                    print(f"[CIRCUIT BREAKER] Daily PnL {state['daily_pnl_pct']}% hit limit, halting 24h!")
                save_state(state)
                print(f"[SYNC CLOSED] {pos} @ ${ep:,.2f} -> ${real_exit:,.2f} | Net PnL: {net_ret_pct:+.3f}%")
                return {"action": f"SYNC_CLOSE_{pos}", "reason": sync_reason, "pnl_pct": net_ret_pct}

            if live_qty > 0:
                state["amount"] = live_qty
            if live_ep > 0:
                ep = live_ep
                state["entry_price"] = live_ep

        entry_dt = datetime.datetime.fromisoformat(state["entry_time_utc"])
        held_hours = (now_utc - entry_dt).total_seconds() / 3600.0
        raw_ret = ((curr_p - ep) / ep) if pos == "LONG" else ((ep - curr_p) / ep)

        # 1b. [UPGRADE] 保本移動停損：一旦浮盈達 +0.80%，立刻把 SL 上移至進場價 +0.10% 鎖死保本！
        if (not state.get("breakeven_armed", False)) and raw_ret >= 0.0100:
            be_sl = round(ep * 1.0010, 2) if pos == "LONG" else round(ep * 0.9990, 2)
            state["sl_price"] = be_sl
            state["breakeven_armed"] = True
            if not dry_run and exchange is not None:
                try:
                    exchange.cancel_all_orders(SYMBOL)
                    place_protective_orders(exchange, pos, state["amount"], state["tp_price"], be_sl)
                except Exception as e:
                    print(f"[WARN] Updating exchange breakeven SL failed: {e}")
            print(f"[BREAKEVEN ARMED] Profit reached {raw_ret*100:+.2f}%; SL moved to ${be_sl:,.2f} (+0.10% locked)!")

        # 1c. 應期順勢加碼（實盤具備保護單重試）
        if sig["is_eval_minute"] and (not state.get("scaled", False)) and raw_ret > 0.0015:
            if (pos == "LONG" and sig["scale_long_ok"]) or (pos == "SHORT" and sig["scale_short_ok"]):
                target_pct = min(0.75, round(pos_pct * 1.25, 2))
                delta_pct = max(0.0, round(target_pct - pos_pct, 4))
                if delta_pct >= 0.05:
                    usdt_balance = 10000.0
                    if not dry_run and exchange is not None:
                        bal = exchange.fetch_balance()
                        usdt_balance = float(bal["total"].get("USDT", 0.0))
                    add_qty = round((usdt_balance * delta_pct * leverage) / curr_p, 3)
                    if add_qty >= 0.001:
                        old_qty = float(state.get("amount", 0.0))
                        fill_add_p = curr_p
                        if not dry_run and exchange is not None:
                            order_side = "buy" if pos == "LONG" else "sell"
                            ord_res = exchange.create_market_order(SYMBOL, order_side, add_qty)
                            fill_add_p = float(ord_res.get("average") or ord_res.get("price") or curr_p)

                        new_qty = round(old_qty + add_qty, 3)
                        new_ep = round(((ep * old_qty) + (fill_add_p * add_qty)) / new_qty, 2) if new_qty > 0 else fill_add_p
                        tp_ratio = float(state.get("tp_pct", sig["tp_pct"]))
                        sl_ratio = float(state.get("sl_pct", sig["sl_pct"]))
                        new_tp = round(new_ep * (1.0 + tp_ratio), 2) if pos == "LONG" else round(new_ep * (1.0 - tp_ratio), 2)
                        new_sl = state["sl_price"] if state.get("breakeven_armed") else (
                            round(new_ep * (1.0 - sl_ratio), 2) if pos == "LONG" else round(new_ep * (1.0 + sl_ratio), 2)
                        )

                        if not dry_run and exchange is not None:
                            exchange.cancel_all_orders(SYMBOL)
                            ok_prot = place_protective_orders(exchange, pos, new_qty, new_tp, new_sl, retries=2)
                            if not ok_prot:
                                print("[CRITICAL WARN] Protective orders failed after scale-up! Monitor immediately.")

                        state["amount"] = new_qty
                        state["entry_price"] = new_ep
                        state["tp_price"] = new_tp
                        state["sl_price"] = new_sl
                        state["pos_pct"] = target_pct
                        state["scaled"] = True
                        ep = new_ep
                        pos_pct = target_pct
                        raw_ret = ((curr_p - ep) / ep) if pos == "LONG" else ((ep - curr_p) / ep)
                        print(f"[YINGQI SCALE-UP] Added {add_qty} BTC -> total {new_qty} BTC ({int(target_pct*100)}%) @ avg ${new_ep:,.2f} | TP=${new_tp:,.2f} / SL=${new_sl:,.2f}")

        # 1d. 檢查出場條件（採用皇極立春軟加權之 max_hold_h）
        max_hold_h = float(state.get("max_hold_h", sig["max_hold_h"]))
        hit_tp = (pos == "LONG" and curr_p >= state["tp_price"]) or (pos == "SHORT" and curr_p <= state["tp_price"])
        hit_sl = (pos == "LONG" and curr_p <= state["sl_price"]) or (pos == "SHORT" and curr_p >= state["sl_price"])
        hit_time = held_hours >= (max_hold_h - 0.05)
        opp_reversal = sig["is_eval_minute"] and ((pos == "LONG" and sig["signal"] == "SHORT") or (pos == "SHORT" and sig["signal"] == "LONG"))
        kw_lock = sig["kw_lock_profit"] and (raw_ret >= 0.0035)
        tight_sl = (not state.get("breakeven_armed", False)) and sig["tight_stop_middle"] and (raw_ret <= -0.0055)

        if hit_tp or hit_sl or hit_time or opp_reversal or kw_lock or tight_sl:
            if hit_tp:
                reason = "Take-Profit (+1.5%)"
            elif hit_sl and state.get("breakeven_armed"):
                reason = "Breakeven Trailing-Stop (+0.1%)"
            elif kw_lock:
                reason = "3rd-Chuan Void Profit-Lock"
            elif tight_sl:
                reason = "2nd-Chuan Void Tight-Stop"
            elif opp_reversal:
                reason = f"YingQi Reversal -> {sig['signal']}"
            elif hit_sl:
                reason = "Stop-Loss (-0.9%)"
            else:
                reason = f"HuangJi Time-Stop ({max_hold_h}h)"

            exit_p = curr_p
            if not dry_run and exchange is not None:
                close_side = "sell" if pos == "LONG" else "buy"
                exchange.cancel_all_orders(SYMBOL)
                close_ord = exchange.create_market_order(SYMBOL, close_side, state["amount"], params={"reduceOnly": True})
                exit_p = float(close_ord.get("average") or close_ord.get("price") or curr_p)

            final_raw_ret = ((exit_p - ep) / ep) if pos == "LONG" else ((ep - exit_p) / ep)
            net_ret_pct = round((final_raw_ret - 0.0006) * 100.0 * pos_pct * leverage, 3)

            state["daily_pnl_pct"] = round(state["daily_pnl_pct"] + net_ret_pct, 3)
            state["trade_history"].append({
                "side": pos, "entry": ep, "exit": exit_p, "pnl_pct": net_ret_pct,
                "reason": reason, "time_utc": now_utc.isoformat(),
            })
            state.update(default_flat_fields())
            if state["daily_pnl_pct"] <= daily_loss_limit:
                state["halted_until_utc"] = (now_utc + datetime.timedelta(hours=24)).isoformat()
                print(f"[CIRCUIT BREAKER] Daily PnL {state['daily_pnl_pct']}% hit limit, halting 24h!")

            save_state(state)
            print(f"[CLOSED] {pos} @ ${ep:,.2f} -> ${exit_p:,.2f} | Reason: {reason} | Net PnL: {net_ret_pct:+.3f}%")
            return {"action": f"CLOSE_{pos}", "reason": reason, "pnl_pct": net_ret_pct}
        else:
            be_tag = " [BE-LOCKED]" if state.get("breakeven_armed") else ""
            print(f"[HOLDING] {pos} ({int(pos_pct*100)}% / {state['amount']} BTC) @ ${ep:,.2f}{be_tag} (Held {held_hours:.2f}h/{max_hold_h}h | Unrealized: {raw_ret*100:+.2f}% | TP=${state['tp_price']} / SL=${state['sl_price']})")
            save_state(state)
            return {"action": f"HOLD_{pos}"}

    # 2. 空手且命中應期分鐘：開倉
    if sig["signal"] in ("LONG", "SHORT"):
        side = sig["signal"]
        pos_pct = float(sig["recommended_size_pct"])
        usdt_balance = 10000.0
        if not dry_run and exchange is not None:
            bal = exchange.fetch_balance()
            usdt_balance = float(bal["total"].get("USDT", 0.0))
            exchange.set_leverage(leverage, SYMBOL)

        qty = round((usdt_balance * pos_pct * leverage) / curr_p, 3)
        if qty < 0.001:
            print("[WARN] Balance below min order size (0.001 BTC), skipping.")
            return {"action": "SKIP_LOW_BALANCE"}

        fill_p = curr_p
        tp_p = sig["tp_price"]
        sl_p = sig["sl_price"]
        if not dry_run and exchange is not None:
            order_side = "buy" if side == "LONG" else "sell"
            ord_res = exchange.create_market_order(SYMBOL, order_side, qty)
            fill_p = float(ord_res.get("average") or ord_res.get("price") or curr_p)
            tp_p = round(fill_p * (1.0 + sig["tp_pct"]), 2) if side == "LONG" else round(fill_p * (1.0 - sig["tp_pct"]), 2)
            sl_p = round(fill_p * (1.0 - sig["sl_pct"]), 2) if side == "LONG" else round(fill_p * (1.0 + sig["sl_pct"]), 2)
            place_protective_orders(exchange, side, qty, tp_p, sl_p, retries=2)

        state["position"] = side
        state["entry_price"] = fill_p
        state["amount"] = qty
        state["pos_pct"] = pos_pct
        state["scaled"] = False
        state["breakeven_armed"] = False
        state["entry_time_utc"] = now_utc.isoformat()
        state["tp_price"] = tp_p
        state["sl_price"] = sl_p
        state["tp_pct"] = sig["tp_pct"]
        state["sl_pct"] = sig["sl_pct"]
        state["max_hold_h"] = sig["max_hold_h"]
        save_state(state)
        print(f"[OPENED] {side} {qty} BTC ({int(pos_pct*100)}% alloc) @ ${fill_p:,.2f} | Hold<={sig['max_hold_h']}h | TP=${tp_p:,.2f} / SL=${sl_p:,.2f}")
        return {"action": f"OPEN_{side}", "qty": qty, "price": fill_p}

    save_state(state)
    print(f"[WAIT] YingQi trigger at {sig['slot_5m']}m evaluated -> No entry signal; staying 100% USDT cash.")
    return {"action": "WAIT"}


if __name__ == "__main__":
    is_dry = os.environ.get("DRY_RUN", "true").lower() == "true"
    force_flag = ("--force" in sys.argv)
    run_bot_cycle(dry_run=is_dry, force_eval=force_flag)
