#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多幣種 (BTC/ETH/SOL) 大六壬 v15.1「真九宮奇門 × 純大六壬 2D 光譜 × 皇極立春倉位 × 獨立本金隔離」實盤加固版 (btc_autotrader.py)
=============================================================================================================================
完整整合：
  - [v15.1] 支援獨立資金配比與本金上限（--capital / BTC_CAPITAL_USD / ETH_CAPITAL_USD / CAPITAL_USD），實盤雙幣互不搶佔保證金
  - [v15.0] 真時家奇門陰陽遁九宮門迫檢測 + 壬奇共振矩陣 + 大六壬多維度光譜四象限
  - [v13.3] 皇極經世立春起算雙月六爻純倉位加權 + 動態保本移動停損
  - [v12.0] 大六壬動態應期 (每時辰 0～6 次) + 四大工程防呆（斷線安全跳過、原子寫檔/保護單重試、真實成交價、精簡日誌）
"""

import datetime
import json
import os
import sys
import time
from typing import Dict, Any, Optional, List, Tuple
from btc_strategy import evaluate_btc_signal, ASSET_PROFILES


def _resolve_asset_code() -> str:
    for idx, a in enumerate(sys.argv):
        if a == "--asset" and idx + 1 < len(sys.argv):
            return sys.argv[idx + 1].upper()
    return os.environ.get("ASSET_CODE", "BTC").upper()


ASSET_CODE = _resolve_asset_code()
ASSET_PROF = ASSET_PROFILES.get(ASSET_CODE, ASSET_PROFILES["BTC"])
SYMBOL = os.environ.get("TRADING_SYMBOL", ASSET_PROF["symbol"])
STATE_FILE = os.environ.get("BTC_STATE_FILE", ASSET_PROF["state_file"])

DEFAULT_ASSET_CAPS = {"BTC": 6000.0, "ETH": 4000.0, "SOL": 3000.0}
DEFAULT_LIVE_WEIGHTS = {"BTC": 0.60, "ETH": 0.40, "SOL": 0.30}


def resolve_capital_config() -> Tuple[float, bool]:
    """
    解析此幣種的獨立本金上限（優先順序：--capital > {ASSET}_CAPITAL_USD > CAPITAL_USD > 預設 60/40）。
    回傳 (capital_usd, is_explicitly_set)。
    """
    for idx, a in enumerate(sys.argv):
        if a == "--capital" and idx + 1 < len(sys.argv):
            try:
                val = float(sys.argv[idx + 1])
                if val > 0:
                    return val, True
            except ValueError:
                pass

    for env_key in (f"{ASSET_CODE}_CAPITAL_USD", "CAPITAL_USD"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            try:
                val = float(raw)
                if val > 0:
                    return val, True
            except ValueError:
                pass

    return DEFAULT_ASSET_CAPS.get(ASSET_CODE, 5000.0), False


def resolve_effective_usdt(dry_run: bool, exchange: Any) -> float:
    """
    計算本次下單可用的獨立本金：
      - 模擬盤：直接使用設定的獨立本金（預設 BTC $6,000 / ETH $4,000）
      - 實盤：若有設定 --capital / {ASSET}_CAPITAL_USD / CAPITAL_USD，取 min(帳戶總USDT, 獨立本金上限)；
              若未手動設定，則預設以帳戶總 USDT 的 60%(BTC) / 40%(ETH) 作為保護上限，避免雙幣互搶保證金。
    """
    cap_usd, is_explicit = resolve_capital_config()
    if dry_run or exchange is None:
        return cap_usd
    bal = exchange.fetch_balance()
    acct_usdt = float(bal["total"].get("USDT", 0.0))
    if is_explicit:
        return min(acct_usdt, cap_usd)
    return acct_usdt * DEFAULT_LIVE_WEIGHTS.get(ASSET_CODE, 0.50)


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
        "be_trigger_pct": 0.0100,
        "entry_time_utc": None,
        "tp_price": 0.0,
        "sl_price": 0.0,
        "tp_pct": ASSET_PROF["tp"],
        "sl_pct": ASSET_PROF["sl"],
        "max_hold_h": 4.0,
        "entry_quadrant": "",
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
            return True, round(qty, ASSET_PROF["qty_dp"]), ep
        return False, 0.0, 0.0
    except Exception as e:
        print(f"[WARN] Failed to fetch live positions: {e}")
        return True, -1.0, 0.0


def fetch_last_fill_price(exchange, fallback_price: float) -> float:
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
    if exchange is not None:
        try:
            ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe="5m", limit=320)
            if ohlcv and len(ohlcv) >= 120:
                return [float(bar[4]) for bar in ohlcv][-300:]
        except Exception as e:
            print(f"[WARN] CCXT authenticated 5m fetch failed: {e}")

    try:
        import ccxt
        for ex_id, sym in ASSET_PROF["pub_pairs"]:
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

    sig = evaluate_btc_signal(closes_5m, simulated_dt_tw, force_eval=force_eval, asset_code=ASSET_CODE)
    curr_p = sig["price"]
    leverage = int(os.environ.get("LEVERAGE", "1"))
    daily_loss_limit = float(os.environ.get("DAILY_MAX_LOSS_PCT", "-3.0"))
    cap_usd, is_explicit_cap = resolve_capital_config()

    if state["position"] is None and not sig["is_eval_minute"]:
        print(
            f"[STANDBY {ASSET_CODE} {now_utc.strftime('%m-%d %H:%M UTC')}] {to_en(sig['shichen'])} Min {sig['raw_mins']}m | "
            f"{ASSET_CODE} ${curr_p:,.2f} | {sig['spectrum_quad']} (M:{sig['spectrum_manifest']}/F:{sig['spectrum_friction']}) | Next: {sig['next_minutes']}"
        )
        save_state(state)
        return {"action": "STANDBY"}

    mode_lbl = "[PAPER / DRY-RUN]" if dry_run else "[LIVE / TESTNET]"
    cap_lbl = f"${cap_usd:,.2f} (Explicit Cap)" if is_explicit_cap else f"${cap_usd:,.2f} (Default {int(DEFAULT_LIVE_WEIGHTS.get(ASSET_CODE,0.5)*100)}%)"
    print("=" * 88)
    print(f"[{ASSET_PROF['name_en']} DaLiuRen v15.1 Tri-System AutoTrader] {mode_lbl} ({now_utc.strftime('%Y-%m-%d %H:%M UTC')})")
    print(f"Shichen: {to_en(sig['shichen'])} | Min: {sig['raw_mins']}m (Slot {sig['slot_5m']}m) | Mode: {sig['sched_mode_en']}")
    print(f"2D Spectrum : {sig['spectrum_quad']} | Manifest: {sig['spectrum_manifest']}/100 | Friction: {sig['spectrum_friction']}/100 | Blockers: {to_en(sig['spectrum_blockers'])}")
    print(f"HuangJi(LC) : {sig['huangji_tag']} | BE-Trigger: +{sig['be_trigger_pct']*100:.2f}% | Capital: {cap_lbl}")
    print(f"Market Data : {ASSET_CODE} ${curr_p:,.2f} | MA120(10H): ${sig['ma20']:,.2f} | 15m-Mom: {sig['mom_15m_pct']:+.2f}% | RSI(1H): {sig['rsi_1h']}")
    print(f"SanChuan    : {to_en(sig['sanchuan'])}")
    print(f"True QiMen  : {to_en(sig['qm_true_str'])}")
    print(f"El-Score    : {sig['el_score']:+.1f} | Trigger: {to_en(sig['active_chuan'])} | Signal: {sig['signal']}")
    print("=" * 88)

    if state["position"] is not None:
        pos = state["position"]
        ep = float(state["entry_price"])
        pos_pct = float(state.get("pos_pct", 0.50))

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
        be_trig = float(state.get("be_trigger_pct", 0.0100))

        # Dynamic Breakeven Trailing Stop
        if (not state.get("breakeven_armed", False)) and raw_ret >= be_trig:
            be_sl = round(ep * 1.0010, 2) if pos == "LONG" else round(ep * 0.9990, 2)
            state["sl_price"] = be_sl
            state["breakeven_armed"] = True
            if not dry_run and exchange is not None:
                try:
                    exchange.cancel_all_orders(SYMBOL)
                    place_protective_orders(exchange, pos, state["amount"], state["tp_price"], be_sl)
                except Exception as e:
                    print(f"[WARN] Updating exchange breakeven SL failed: {e}")
            print(f"[BREAKEVEN ARMED] Profit reached {raw_ret*100:+.2f}% (>=+{be_trig*100:.2f}%); SL moved to ${be_sl:,.2f} (+0.10% locked)!")

        # Trend Scale-Up
        if sig["is_eval_minute"] and (not state.get("scaled", False)) and raw_ret > 0.0015:
            if (pos == "LONG" and sig["scale_long_ok"]) or (pos == "SHORT" and sig["scale_short_ok"]):
                cap_pct = float(sig.get("scale_long_cap", 0.78)) if pos == "LONG" else 0.78
                mult_sc = 1.28 if pos == "LONG" else 1.25
                target_pct = min(cap_pct, round(pos_pct * mult_sc, 2))
                delta_pct = max(0.0, round(target_pct - pos_pct, 4))
                if delta_pct >= 0.05:
                    usdt_balance = resolve_effective_usdt(dry_run, exchange)
                    add_qty = round((usdt_balance * delta_pct * leverage) / curr_p, ASSET_PROF["qty_dp"])
                    if add_qty >= ASSET_PROF["min_qty"]:
                        old_qty = float(state.get("amount", 0.0))
                        fill_add_p = curr_p
                        if not dry_run and exchange is not None:
                            order_side = "buy" if pos == "LONG" else "sell"
                            ord_res = exchange.create_market_order(SYMBOL, order_side, add_qty)
                            fill_add_p = float(ord_res.get("average") or ord_res.get("price") or curr_p)

                        new_qty = round(old_qty + add_qty, ASSET_PROF["qty_dp"])
                        new_ep = round(((ep * old_qty) + (fill_add_p * add_qty)) / new_qty, 2) if new_qty > 0 else fill_add_p
                        tp_ratio = float(state.get("tp_pct", ASSET_PROF["tp"]))
                        sl_ratio = float(state.get("sl_pct", ASSET_PROF["sl"]))
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
                        print(f"[2D-SPECTRUM SCALE-UP] {sig['spectrum_quad']} confirmed; added {add_qty} {ASSET_CODE} -> {new_qty} {ASSET_CODE} ({int(target_pct*100)}%) @ avg ${new_ep:,.2f}")

        max_hold_h = float(state.get("max_hold_h", 4.0))
        hit_tp = (pos == "LONG" and curr_p >= state["tp_price"]) or (pos == "SHORT" and curr_p <= state["tp_price"])
        hit_sl = (pos == "LONG" and curr_p <= state["sl_price"]) or (pos == "SHORT" and curr_p >= state["sl_price"])
        hit_time = held_hours >= (max_hold_h - 0.05)
        opp_reversal = sig["is_eval_minute"] and ((pos == "LONG" and sig["signal"] == "SHORT") or (pos == "SHORT" and sig["signal"] == "LONG"))
        kw_lock = sig["kw_lock_profit"] and (raw_ret >= 0.0035)
        tight_sl = (not state.get("breakeven_armed", False)) and sig["tight_stop_middle"] and (raw_ret <= -0.0055)

        if hit_tp or hit_sl or hit_time or opp_reversal or kw_lock or tight_sl:
            tp_disp = float(state.get("tp_pct", ASSET_PROF["tp"])) * 100.0
            sl_disp = float(state.get("sl_pct", ASSET_PROF["sl"])) * 100.0
            if hit_tp:
                reason = f"Take-Profit (+{tp_disp:.1f}%)"
            elif hit_sl and state.get("breakeven_armed"):
                reason = "Breakeven Trailing-Stop (+0.1%)"
            elif kw_lock:
                reason = "3rd-Chuan Void Profit-Lock"
            elif tight_sl:
                reason = "2nd-Chuan Void Tight-Stop"
            elif opp_reversal:
                reason = f"YingQi Reversal -> {sig['signal']}"
            elif hit_sl:
                reason = f"Stop-Loss (-{sl_disp:.1f}%)"
            else:
                reason = "4H Time-Stop"

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
            print(f"[HOLDING] {pos} ({int(pos_pct*100)}% / {state['amount']} {ASSET_CODE}) @ ${ep:,.2f}{be_tag} (Held {held_hours:.2f}h/{max_hold_h}h | Unrealized: {raw_ret*100:+.2f}% | TP=${state['tp_price']} / SL=${state['sl_price']})")
            save_state(state)
            return {"action": f"HOLD_{pos}"}

    if sig["signal"] in ("LONG", "SHORT"):
        side = sig["signal"]
        pos_pct = float(sig["recommended_size_pct"])
        usdt_balance = resolve_effective_usdt(dry_run, exchange)
        if not dry_run and exchange is not None:
            exchange.set_leverage(leverage, SYMBOL)

        qty = round((usdt_balance * pos_pct * leverage) / curr_p, ASSET_PROF["qty_dp"])
        if qty < ASSET_PROF["min_qty"]:
            print(f"[WARN] Allocated capital (${usdt_balance:,.2f}) below min order size ({ASSET_PROF['min_qty']} {ASSET_CODE}), skipping.")
            return {"action": "SKIP_LOW_BALANCE"}

        fill_p, tp_p, sl_p = curr_p, sig["tp_price"], sig["sl_price"]
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
        state["be_trigger_pct"] = sig["be_trigger_pct"]
        state["entry_quadrant"] = sig["spectrum_quad"]
        state["entry_time_utc"] = now_utc.isoformat()
        state["tp_price"] = tp_p
        state["sl_price"] = sl_p
        state["tp_pct"] = sig["tp_pct"]
        state["sl_pct"] = sig["sl_pct"]
        state["max_hold_h"] = sig["max_hold_h"]
        save_state(state)
        print(f"[OPENED] {side} {qty} {ASSET_CODE} ({int(pos_pct*100)}% of ${usdt_balance:,.2f} | {sig['spectrum_quad']}) @ ${fill_p:,.2f} | BE>=+{sig['be_trigger_pct']*100:.2f}% | TP=${tp_p:,.2f} / SL=${sl_p:,.2f}")
        return {"action": f"OPEN_{side}", "qty": qty, "price": fill_p}

    save_state(state)
    print(f"[WAIT] YingQi trigger at {sig['slot_5m']}m evaluated ({sig['spectrum_quad']}) -> No entry signal; staying 100% USDT cash.")
    return {"action": "WAIT"}


if __name__ == "__main__":
    is_dry = os.environ.get("DRY_RUN", "true").lower() == "true"
    force_flag = ("--force" in sys.argv)
    run_bot_cycle(dry_run=is_dry, force_eval=force_flag)
