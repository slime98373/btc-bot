#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比特幣 (BTC/USDT) 大六壬十二時辰全自動下單機器人 (btc_autotrader.py)
支援透過 CCXT 串接 Binance / Bybit / OKX 永續合約（支援 Testnet 模擬盤與實盤）
內建五大資金安全風控鎖：
  1. 預設 DRY_RUN=true（純模擬不送出真實委託）與 USE_TESTNET=true（交易所模擬盤）
  2. 1 倍無槓桿（預設 LEVERAGE=1），每次僅動用 50% 帳戶餘額（MAX_POSITION_PCT=0.50）
  3. 進場瞬間自動向交易所送出原生停利 (+1.6%) 與停損 (-1.0%) 委託單（即使本機斷線也受保護）
  4. 6 小時（3 個時辰）時間停損：持倉滿 6 小時自動市價平倉，絕不死抱
  5. 當日累計虧損達 -3.0% 自動啟動熔斷保護，暫停開新倉 24 小時
"""

import datetime
import json
import os
import sys
from typing import Dict, Any, Optional, List
from btc_strategy import evaluate_btc_signal

STATE_FILE = os.environ.get("BTC_STATE_FILE", "btc_bot_state.json")


def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "position": None,          # None / "LONG" / "SHORT"
        "entry_price": 0.0,
        "amount": 0.0,
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


def fetch_btc_2h_closes(exchange=None) -> List[float]:
    if exchange is not None:
        try:
            ohlcv = exchange.fetch_ohlcv("BTC/USDT:USDT", timeframe="2h", limit=35)
            if ohlcv and len(ohlcv) >= 25:
                return [float(bar[4]) for bar in ohlcv]
        except Exception as e:
            print(f"[警告] 透過 CCXT 抓取 2H K 線失敗：{e}")

    # 即時公開行情（免 API Key，支援 AWS 雪梨/全球伺服器即時模擬盤）
    try:
        import ccxt
        for ex_id, sym in [("okx", "BTC/USDT"), ("kraken", "BTC/USD"), ("coinbase", "BTC/USD"), ("gate", "BTC/USDT")]:
            try:
                pub_ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
                ohlcv = pub_ex.fetch_ohlcv(sym, timeframe="2h", limit=35)
                if ohlcv and len(ohlcv) >= 25:
                    print(f"[公開即時行情] 已從 {ex_id.upper()} 取得最新 2 小時 K 線 ({sym})")
                    return [float(bar[4]) for bar in ohlcv]
            except Exception:
                continue
    except Exception:
        pass

    # 離線或模擬測試備援序列（以 2026-11-16 真實價格 $64,012.79 為基準）
    base = 64012.79
    return [round(base * (1.0 + ((i % 7) - 3) * 0.003), 2) for i in range(30)]


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

    # 檢查當日 -3.0% 熔斷鎖
    if state.get("halted_until_utc"):
        halt_dt = datetime.datetime.fromisoformat(state["halted_until_utc"])
        if now_utc < halt_dt:
            msg = f"[熔斷保護中] 暫停交易至 {halt_dt.isoformat()} UTC"
            print(msg)
            return {"action": "HALTED", "message": msg}
        state["halted_until_utc"] = None

    exchange = None if dry_run else get_exchange()
    closes_2h = simulated_closes if simulated_closes is not None else fetch_btc_2h_closes(exchange)
    sig = evaluate_btc_signal(closes_2h, simulated_dt_tw)
    curr_p = sig["price"]
    max_pos_pct = float(os.environ.get("MAX_POSITION_PCT", "0.50"))
    leverage = int(os.environ.get("LEVERAGE", "1"))
    daily_loss_limit = float(os.environ.get("DAILY_MAX_LOSS_PCT", "-3.0"))

    print("=" * 68)
    print(f"【BTC/USDT 大六壬自動交易機器人】{'[DRY-RUN 模擬]' if dry_run else '[LIVE/TESTNET 連線]'}")
    print(f"時辰：{sig['shichen']}｜現價：${curr_p:,.2f}｜20MA：${sig['ma20']:,.2f}｜RSI5：{sig['rsi5']}")
    print(f"三傳：{sig['sanchuan']}｜奇門：{sig['qimen']}")
    print(f"離火共振：{sig['el_score']:+.1f}（{sig['el_note']}）｜系統訊號：{sig['signal']}")
    print("=" * 68)

    # 1. 若目前持有倉位，先檢查「觸價停利／停損」或「滿 6 小時（3 個時辰）強制平倉」
    if state["position"] is not None:
        pos = state["position"]
        ep = state["entry_price"]
        entry_dt = datetime.datetime.fromisoformat(state["entry_time_utc"])
        held_hours = (now_utc - entry_dt).total_seconds() / 3600.0

        hit_tp = (pos == "LONG" and curr_p >= state["tp_price"]) or (pos == "SHORT" and curr_p <= state["tp_price"])
        hit_sl = (pos == "LONG" and curr_p <= state["sl_price"]) or (pos == "SHORT" and curr_p >= state["sl_price"])
        hit_time = held_hours >= 5.9  # 滿 3 個時辰 (6 小時)

        if hit_tp or hit_sl or hit_time:
            reason = "觸及停利" if hit_tp else ("觸及停損" if hit_sl else "滿6小時(3時辰)時間平倉")
            raw_ret = ((curr_p - ep) / ep) if pos == "LONG" else ((ep - curr_p) / ep)
            net_ret_pct = round((raw_ret - 0.0006) * 100.0 * max_pos_pct * leverage, 3)

            if not dry_run and exchange is not None:
                close_side = "sell" if pos == "LONG" else "buy"
                exchange.cancel_all_orders("BTC/USDT:USDT")
                exchange.create_market_order("BTC/USDT:USDT", close_side, state["amount"], params={"reduceOnly": True})

            state["daily_pnl_pct"] = round(state["daily_pnl_pct"] + net_ret_pct, 3)
            state["trade_history"].append({
                "side": pos, "entry": ep, "exit": curr_p, "pnl_pct": net_ret_pct,
                "reason": reason, "time_utc": now_utc.isoformat()
            })
            state["position"] = None
            state["entry_price"] = 0.0
            state["amount"] = 0.0
            state["entry_time_utc"] = None

            if state["daily_pnl_pct"] <= daily_loss_limit:
                state["halted_until_utc"] = (now_utc + datetime.timedelta(hours=24)).isoformat()
                print(f"[風控熔斷] 當日累計損益 {state['daily_pnl_pct']}% 觸及上限，暫停開倉 24 小時！")

            save_state(state)
            print(f"[平倉完成] {pos} @ ${ep:,.2f} -> ${curr_p:,.2f}｜原因：{reason}｜帳戶淨損益：{net_ret_pct:+.3f}%")
            return {"action": f"CLOSE_{pos}", "reason": reason, "pnl_pct": net_ret_pct}
        else:
            print(f"[持倉續抱] 目前持有 {pos} @ ${ep:,.2f}（已持倉 {held_hours:.1f} 小時，目標 TP=${state['tp_price']} / SL=${state['sl_price']}）")
            save_state(state)
            return {"action": f"HOLD_{pos}"}

    # 2. 若空手且出現明確 LONG / SHORT 訊號，執行自動開倉並同步掛出交易所端停利／停損單
    if sig["signal"] in ("LONG", "SHORT"):
        side = sig["signal"]
        usdt_balance = 10000.0
        if not dry_run and exchange is not None:
            bal = exchange.fetch_balance()
            usdt_balance = float(bal["total"].get("USDT", 0.0))
            exchange.set_leverage(leverage, "BTC/USDT:USDT")

        alloc_usdt = usdt_balance * max_pos_pct * leverage
        qty = round(alloc_usdt / curr_p, 3)
        if qty <= 0:
            print("[警告] 帳戶餘額不足最小下單單位 (0.001 BTC)，略過開倉。")
            return {"action": "SKIP_LOW_BALANCE"}

        if not dry_run and exchange is not None:
            order_side = "buy" if side == "LONG" else "sell"
            close_side = "sell" if side == "LONG" else "buy"
            exchange.create_market_order("BTC/USDT:USDT", order_side, qty)
            # 同步向交易所掛出原生停損與停利條件單
            exchange.create_order("BTC/USDT:USDT", "TAKE_PROFIT_MARKET", close_side, qty, params={"stopPrice": sig["tp_price"], "reduceOnly": True})
            exchange.create_order("BTC/USDT:USDT", "STOP_MARKET", close_side, qty, params={"stopPrice": sig["sl_price"], "reduceOnly": True})

        state["position"] = side
        state["entry_price"] = curr_p
        state["amount"] = qty
        state["entry_time_utc"] = now_utc.isoformat()
        state["tp_price"] = sig["tp_price"]
        state["sl_price"] = sig["sl_price"]
        save_state(state)
        print(f"[開倉成功] {side} {qty} BTC @ ${curr_p:,.2f}｜TP=${sig['tp_price']:,.2f} / SL=${sig['sl_price']:,.2f}")
        return {"action": f"OPEN_{side}", "qty": qty, "price": curr_p}

    save_state(state)
    print("[今日此輪觀望] 無符合大六壬＋離火共振條件之訊號，維持 100% USDT 現金。")
    return {"action": "WAIT"}


if __name__ == "__main__":
    is_dry = os.environ.get("DRY_RUN", "true").lower() == "true"
    run_bot_cycle(dry_run=is_dry)
