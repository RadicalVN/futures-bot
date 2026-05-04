"""
adts/strategy.py — Adaptive Dynamic Trend & Shield (ADTS) Strategy

Luồng xử lý:
  1. [Calibration]  Mỗi 24h: tính Base_ATR, Sideway_Threshold, Min_Slope từ D1
  2. [Filtering]    The Shield: ADX > 25, BBWidth > Threshold, |EMA20_Slope| > Min_Slope
  3. [Signaling]    Entry: Shield Passed + giá cắt EMA20 + slope đúng chiều
  4. [Execution]    SL/TP động theo ATR, TP1 chốt 50%, TP2 trailing, Emergency Exit

Tích hợp với BotEngine qua interface BaseStrategy.analyze().
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from src.strategies.base_strategy import BaseStrategy, StrategySignal
from .models import ADTSConfig, CalibrationResult, ShieldState, OrderState
from .scanner import run_calibration
from .indicators import build_indicator_snapshot, IndicatorSnapshot
from .risk_manager import calculate_position_plan, check_emergency_exit


class ADTSStrategy(BaseStrategy):
    """
    Adaptive Dynamic Trend & Shield Strategy.

    Tham số config (tất cả có giá trị mặc định hợp lý):
      atr_period (int=14), adx_period (int=14), ema_period (int=20)
      bb_period (int=20), bb_std (float=2.0), bbwidth_sma_period (int=200)
      adx_threshold (float=25.0), bbwidth_threshold_factor (float=0.85)
      min_slope_atr_factor (float=0.05)
      risk_pct (float=0.01), sl_atr_mult (float=1.5)
      tp1_rr (float=1.2), tp1_close_pct (float=0.5)
      tp2_trail_atr_mult (float=2.0)
      emergency_adx_threshold (float=20.0), emergency_close_pct (float=0.5)
      d1_lookback (int=300), calibration_interval_hours (float=24.0)
      leverage (int=5), max_open_positions (int=3)
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.name = "adts"

        # Parse và validate config qua Pydantic
        self.cfg = ADTSConfig.from_dict(config)

        # Calibration state — được cập nhật mỗi 24h
        self._calibration: Optional[CalibrationResult] = None
        self._calibration_lock = asyncio.Lock()

        # Per-symbol order state (tracking TP1 hit, trailing stop, ...)
        # Key: symbol (normalized), Value: OrderState
        self._order_states: dict[str, OrderState] = {}

        logger.info(
            f"[ADTS] Khởi tạo | "
            f"ADX_thr={self.cfg.adx_threshold} | "
            f"SL={self.cfg.sl_atr_mult}×ATR | "
            f"TP1=R:R1:{self.cfg.tp1_rr} | "
            f"TP2=Trail{self.cfg.tp2_trail_atr_mult}×ATR | "
            f"Risk={self.cfg.risk_pct*100:.1f}%"
        )

    # ── Public interface ──────────────────────────────────────────────────────

    async def analyze(
        self,
        symbol: str,
        ohlcv_data: list,
        current_positions: list,
    ) -> StrategySignal:
        """
        Phân tích OHLCV và trả về StrategySignal.

        Luồng:
          Calibration → Filtering (Shield) → Signaling → Exit checks
        """
        no_signal = StrategySignal(signal="none", symbol=symbol, price=0, reason="No signal")

        # ── Bước 1: Chuyển sang DataFrame ────────────────────────────────────
        if len(ohlcv_data) < 50:
            return StrategySignal(
                signal="none", symbol=symbol, price=0,
                reason=f"Không đủ dữ liệu: có {len(ohlcv_data)} nến, cần ≥50"
            )

        df = pd.DataFrame(
            ohlcv_data,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df = df.astype({
            "open": float, "high": float, "low": float,
            "close": float, "volume": float,
        })

        # ── Bước 2: Calibration (D1) — chạy nếu chưa có hoặc đã stale ───────
        logger.debug(f"[ADTS][{symbol}] ── Calibration ──")
        calibration = await self._ensure_calibration(ohlcv_data, symbol)
        if calibration is None:
            return StrategySignal(
                signal="none", symbol=symbol, price=0,
                reason="Calibration chưa sẵn sàng — thiếu dữ liệu D1",
                metadata={"shield_passed": False, "calibration_ready": False},
            )

        # ── Bước 3: Tính indicator intraday ──────────────────────────────────
        snap = build_indicator_snapshot(
            df,
            atr_period=self.cfg.atr_period,
            adx_period=self.cfg.adx_period,
            ema_period=self.cfg.ema_period,
            ema200_period=self.cfg.ema200_period,
            bb_period=self.cfg.bb_period,
            bb_std=self.cfg.bb_std,
        )
        if snap is None:
            return StrategySignal(
                signal="none", symbol=symbol, price=0,
                reason="Không đủ dữ liệu để tính indicator"
            )

        # ── Bước 4: The Shield (Sideway Filter) ──────────────────────────────
        logger.debug(f"[ADTS][{symbol}] ── Filtering (The Shield) ──")
        shield = self._evaluate_shield(snap, calibration)
        logger.debug(f"[ADTS][{symbol}] {shield.summary}")

        # ── Bước 5: Kiểm tra vị thế hiện tại ─────────────────────────────────
        pos_side = self._get_position_side(symbol, current_positions)
        order_state = self._order_states.get(symbol)

        # ── Bước 6: Exit checks (ưu tiên trước entry) ────────────────────────
        if pos_side is not None and order_state is not None:
            exit_signal = self._check_exits(
                symbol=symbol,
                snap=snap,
                order_state=order_state,
                calibration=calibration,
                shield=shield,
            )
            if exit_signal is not None:
                # Dọn dẹp order state nếu đóng toàn bộ
                if exit_signal.metadata.get("full_close", False):
                    self._order_states.pop(symbol, None)
                return exit_signal

        # ── Bước 7: Entry Signal ──────────────────────────────────────────────
        if pos_side is None:
            logger.debug(f"[ADTS][{symbol}] ── Signaling ──")
            entry_signal = self._check_entry(
                symbol=symbol,
                snap=snap,
                shield=shield,
                calibration=calibration,
            )
            if entry_signal is not None:
                return entry_signal

        # ── Không có tín hiệu ─────────────────────────────────────────────────
        reason_parts = [shield.summary]
        if pos_side:
            reason_parts.append(f"Đang giữ {pos_side.upper()}")
        return StrategySignal(
            signal="none",
            symbol=symbol,
            price=snap.close,
            reason=" | ".join(reason_parts),
            metadata=self._build_metadata(snap, calibration, shield),
        )

    # ── Calibration ───────────────────────────────────────────────────────────

    async def _ensure_calibration(
        self,
        intraday_ohlcv: list,
        symbol: str,
    ) -> Optional[CalibrationResult]:
        """
        Đảm bảo calibration còn hiệu lực.
        Nếu chưa có hoặc stale → chạy lại từ dữ liệu intraday (dùng làm proxy D1).

        Trong production, nên truyền dữ liệu D1 thực từ exchange.
        Ở đây dùng intraday OHLCV để resample sang D1 khi không có D1 riêng.
        """
        async with self._calibration_lock:
            if self._calibration is not None and not self._calibration.is_stale:
                return self._calibration

            logger.info(f"[ADTS][{symbol}] Chạy Daily Calibration...")

            # Resample intraday → D1 để tính calibration
            d1_ohlcv = self._resample_to_d1(intraday_ohlcv)
            if not d1_ohlcv:
                logger.warning(f"[ADTS][{symbol}] Không thể resample sang D1")
                return self._calibration  # Dùng calibration cũ nếu có

            result = run_calibration(d1_ohlcv, self.cfg, symbol)
            if result is not None:
                self._calibration = result

            return self._calibration

    def _resample_to_d1(self, ohlcv: list) -> list:
        """
        Resample dữ liệu intraday sang D1 bằng pandas.
        Trả về list [[ts_ms, o, h, l, c, v], ...] dạng D1.
        """
        try:
            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("timestamp")
            df = df.astype(float)

            d1 = df.resample("1D").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }).dropna()

            if len(d1) < 10:
                return []

            result = []
            for ts, row in d1.iterrows():
                result.append([
                    int(ts.timestamp() * 1000),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["volume"]),
                ])
            return result
        except Exception as e:
            logger.error(f"[ADTS] Lỗi resample D1: {e}")
            return []

    # ── Shield ────────────────────────────────────────────────────────────────

    def _evaluate_shield(
        self,
        snap: IndicatorSnapshot,
        calibration: CalibrationResult,
    ) -> ShieldState:
        """Đánh giá 3 điều kiện của The Shield."""
        adx_ok = snap.adx > self.cfg.adx_threshold
        bbwidth_ok = snap.bb_width > calibration.sideway_threshold
        slope_ok = abs(snap.ema20_slope) > calibration.min_slope

        return ShieldState(
            adx=snap.adx,
            bb_width=snap.bb_width,
            ema20_slope=snap.ema20_slope,
            adx_ok=adx_ok,
            bbwidth_ok=bbwidth_ok,
            slope_ok=slope_ok,
        )

    # ── Entry Signal ──────────────────────────────────────────────────────────

    def _check_entry(
        self,
        symbol: str,
        snap: IndicatorSnapshot,
        shield: ShieldState,
        calibration: CalibrationResult,
    ) -> Optional[StrategySignal]:
        """
        Kiểm tra điều kiện vào lệnh.

        Buy:  Shield Passed + close > EMA20 + EMA20_Slope > 0 + close > EMA200
        Sell: Shield Passed + close < EMA20 + EMA20_Slope < 0 + close < EMA200
        """
        if not shield.passed:
            return None

        # ── Trend Filter: EMA200 ──────────────────────────────────────────────
        # Long chỉ khi giá trên EMA200 (xu hướng tăng dài hạn)
        # Short chỉ khi giá dưới EMA200 (xu hướng giảm dài hạn)
        above_ema200 = snap.close > snap.ema200
        below_ema200 = snap.close < snap.ema200

        # ── BUY ──────────────────────────────────────────────────────────────
        buy_condition = (
            snap.close > snap.ema20    # Giá đóng cửa trên EMA20
            and snap.ema20_slope > 0   # EMA20 dốc lên
            and above_ema200           # Trend Filter: trên EMA200
        )

        # ── SELL ─────────────────────────────────────────────────────────────
        sell_condition = (
            snap.close < snap.ema20    # Giá đóng cửa dưới EMA20
            and snap.ema20_slope < 0   # EMA20 dốc xuống
            and below_ema200           # Trend Filter: dưới EMA200
        )

        if not buy_condition and not sell_condition:
            # Log lý do bị chặn bởi trend filter
            if shield.passed:
                if snap.close > snap.ema20 and snap.ema20_slope > 0 and not above_ema200:
                    logger.debug(
                        f"[ADTS][{symbol}] Trend Filter BLOCK LONG: "
                        f"close={snap.close:.4f} < EMA200={snap.ema200:.4f}"
                    )
                elif snap.close < snap.ema20 and snap.ema20_slope < 0 and not below_ema200:
                    logger.debug(
                        f"[ADTS][{symbol}] Trend Filter BLOCK SHORT: "
                        f"close={snap.close:.4f} > EMA200={snap.ema200:.4f}"
                    )
            return None

        side = "long" if buy_condition else "short"
        entry_price = snap.close

        logger.info(
            f"[ADTS][{symbol}] ── Signaling ── "
            f"{side.upper()} | "
            f"Close={entry_price:.4f} EMA20={snap.ema20:.4f} "
            f"EMA200={snap.ema200:.4f} Slope={snap.ema20_slope:+.6f}"
        )

        # Tính SL/TP (không cần balance ở đây — chỉ cần giá)
        atr_sl_distance  = self.cfg.sl_atr_mult * snap.atr
        hard_sl_distance = entry_price * self.cfg.hard_sl_pct
        sl_distance      = min(atr_sl_distance, hard_sl_distance)
        sl_source        = "ATR" if atr_sl_distance <= hard_sl_distance else "Hard"

        tp1_distance       = sl_distance * self.cfg.tp1_rr
        tp2_trail_distance = self.cfg.tp2_trail_atr_mult * snap.atr

        if side == "long":
            stop_loss = entry_price - sl_distance
            take_profit_1 = entry_price + tp1_distance
            tp2_initial = entry_price - tp2_trail_distance
        else:
            stop_loss = entry_price + sl_distance
            take_profit_1 = entry_price - tp1_distance
            tp2_initial = entry_price + tp2_trail_distance

        reason = (
            f"ADTS {side.upper()} | "
            f"Shield PASS | "
            f"ADX={snap.adx:.1f} | "
            f"BBW={snap.bb_width:.5f} | "
            f"Slope={snap.ema20_slope:+.6f} | "
            f"EMA200={'above' if above_ema200 else 'below'} | "
            f"SL={stop_loss:.4f}({sl_source}) | TP1={take_profit_1:.4f}"
        )

        metadata = self._build_metadata(snap, calibration, shield)
        metadata.update({
            "entry_price": round(entry_price, 6),
            "stop_loss": round(stop_loss, 6),
            "take_profit_1": round(take_profit_1, 6),
            "tp2_initial_trail": round(tp2_initial, 6),
            "sl_distance": round(sl_distance, 6),
            "sl_source": sl_source,
            "atr_sl_distance": round(atr_sl_distance, 6),
            "hard_sl_distance": round(hard_sl_distance, 6),
            "tp1_distance": round(tp1_distance, 6),
            "atr_at_entry": round(snap.atr, 6),
            "ema200": round(snap.ema200, 6),
            "above_ema200": above_ema200,
        })

        return StrategySignal(
            signal=side,
            symbol=symbol,
            price=entry_price,
            reason=reason,
            confidence=self._calc_confidence(snap, shield),
            metadata=metadata,
        )

    # ── Exit Checks ───────────────────────────────────────────────────────────

    def _check_exits(
        self,
        symbol: str,
        snap: IndicatorSnapshot,
        order_state: OrderState,
        calibration: CalibrationResult,
        shield: ShieldState,
    ) -> Optional[StrategySignal]:
        """
        Kiểm tra tất cả điều kiện thoát lệnh theo thứ tự ưu tiên:
          1. Emergency Exit (ADX < 20 hoặc BBWidth < Threshold)
          2. Stop Loss (SL cứng hoặc SL đã dời về entry)
          3. TP1 (chốt 50% nếu chưa hit)
          4. TP2 Trailing Stop (phần còn lại)
        """
        side = order_state.side
        close = snap.close
        high = snap.high
        low = snap.low

        # ── 1. Emergency Exit ─────────────────────────────────────────────────
        is_emergency, emg_reason = check_emergency_exit(
            adx=snap.adx,
            bb_width=snap.bb_width,
            sideway_threshold=calibration.sideway_threshold,
            config=self.cfg,
        )
        if is_emergency:
            logger.warning(f"[ADTS][{symbol}] {emg_reason}")
            # Cập nhật trailing stop trước khi thoát
            order_state.update_trailing_stop(close, snap.atr, self.cfg.tp2_trail_atr_mult)
            return self._make_exit_signal(
                symbol=symbol,
                side=side,
                price=close,
                reason=emg_reason,
                partial=True,
                partial_pct=self.cfg.emergency_close_pct,
                snap=snap,
                calibration=calibration,
                shield=shield,
                full_close=False,
            )

        # ── 2. Stop Loss ──────────────────────────────────────────────────────
        sl = order_state.stop_loss
        if side == "long" and low <= sl:
            reason = (
                f"🛑 SL LONG: low={low:.4f} ≤ SL={sl:.4f} "
                f"({'Entry SL' if order_state.sl_moved_to_entry else 'ATR SL'})"
            )
            logger.info(f"[ADTS][{symbol}] {reason}")
            return self._make_exit_signal(
                symbol=symbol, side=side,
                price=min(sl, close),
                reason=reason,
                partial=False,
                snap=snap, calibration=calibration, shield=shield,
                full_close=True,
            )

        if side == "short" and high >= sl:
            reason = (
                f"🛑 SL SHORT: high={high:.4f} ≥ SL={sl:.4f} "
                f"({'Entry SL' if order_state.sl_moved_to_entry else 'ATR SL'})"
            )
            logger.info(f"[ADTS][{symbol}] {reason}")
            return self._make_exit_signal(
                symbol=symbol, side=side,
                price=max(sl, close),
                reason=reason,
                partial=False,
                snap=snap, calibration=calibration, shield=shield,
                full_close=True,
            )

        # ── 3. TP1 (chốt 50% nếu chưa hit) ──────────────────────────────────
        if not order_state.tp1_hit:
            tp1 = order_state.take_profit_1
            tp1_hit = (side == "long" and high >= tp1) or (side == "short" and low <= tp1)

            if tp1_hit:
                tp1_price = tp1
                reason = (
                    f"🎯 TP1 {side.upper()}: "
                    f"{'high' if side == 'long' else 'low'}="
                    f"{high if side == 'long' else low:.4f} "
                    f"{'≥' if side == 'long' else '≤'} TP1={tp1:.4f} "
                    f"(chốt {self.cfg.tp1_close_pct*100:.0f}%)"
                )
                logger.info(f"[ADTS][{symbol}] {reason}")

                # Cập nhật order state: đánh dấu TP1 hit, dời SL về entry
                order_state.tp1_hit = True
                order_state.sl_moved_to_entry = True
                order_state.stop_loss = order_state.entry_price  # SL → Entry (Break-even)
                # Khởi tạo trailing stop từ TP1
                order_state.take_profit_2_trail = tp1_price
                order_state.amount_remaining = (
                    order_state.amount_total * (1.0 - self.cfg.tp1_close_pct)
                )

                logger.info(
                    f"[ADTS][{symbol}] SL dời về Entry={order_state.entry_price:.4f} | "
                    f"Còn lại {order_state.amount_remaining:.4f} contracts"
                )

                return self._make_exit_signal(
                    symbol=symbol, side=side,
                    price=tp1_price,
                    reason=reason,
                    partial=True,
                    partial_pct=self.cfg.tp1_close_pct,
                    snap=snap, calibration=calibration, shield=shield,
                    full_close=False,
                )

        # ── 4. TP2 Trailing Stop ──────────────────────────────────────────────
        if order_state.tp1_hit:
            # Cập nhật trailing stop
            new_trail = order_state.update_trailing_stop(
                close, snap.atr, self.cfg.tp2_trail_atr_mult
            )
            trail = order_state.take_profit_2_trail

            trail_hit = (side == "long" and low <= trail) or (side == "short" and high >= trail)

            if trail_hit:
                reason = (
                    f"🏁 TP2 Trailing {side.upper()}: "
                    f"{'low' if side == 'long' else 'high'}="
                    f"{low if side == 'long' else high:.4f} "
                    f"{'≤' if side == 'long' else '≥'} Trail={trail:.4f} "
                    f"({self.cfg.tp2_trail_atr_mult}×ATR)"
                )
                logger.info(f"[ADTS][{symbol}] {reason}")
                return self._make_exit_signal(
                    symbol=symbol, side=side,
                    price=trail,
                    reason=reason,
                    partial=False,
                    snap=snap, calibration=calibration, shield=shield,
                    full_close=True,
                )

        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_exit_signal(
        self,
        symbol: str,
        side: str,
        price: float,
        reason: str,
        partial: bool,
        snap: IndicatorSnapshot,
        calibration: CalibrationResult,
        shield: ShieldState,
        partial_pct: float = 0.5,
        full_close: bool = True,
    ) -> StrategySignal:
        """Tạo StrategySignal thoát lệnh."""
        signal_type = f"close_{side}"
        meta = self._build_metadata(snap, calibration, shield)
        meta.update({
            "partial_close": partial,
            "partial_pct": partial_pct if partial else 1.0,
            "full_close": full_close,
        })
        return StrategySignal(
            signal=signal_type,
            symbol=symbol,
            price=price,
            reason=reason,
            metadata=meta,
        )

    def _get_position_side(self, symbol: str, positions: list) -> Optional[str]:
        """Lấy side của vị thế đang mở cho symbol này."""
        sym_clean = symbol.replace("/", "").replace(":USDT", "")
        for pos in positions:
            pos_sym = pos.get("symbol", "").replace("/", "").replace(":USDT", "")
            if pos_sym == sym_clean:
                size = float(pos.get("contracts", pos.get("size", 0)) or 0)
                if size > 0:
                    return pos.get("side", "long")
        return None

    def _calc_confidence(self, snap: IndicatorSnapshot, shield: ShieldState) -> float:
        """
        Tính confidence score 0.0 → 1.0 dựa trên sức mạnh tín hiệu.
        ADX càng cao, BBWidth càng rộng → confidence càng cao.
        """
        adx_score = min((snap.adx - self.cfg.adx_threshold) / 25.0, 1.0)
        adx_score = max(adx_score, 0.0)
        return round(0.5 + adx_score * 0.5, 2)

    def _build_metadata(
        self,
        snap: IndicatorSnapshot,
        calibration: CalibrationResult,
        shield: ShieldState,
    ) -> dict:
        """Tổng hợp metadata để hiển thị trên dashboard và lưu DB."""
        return {
            # Indicator values
            "close": round(snap.close, 6),
            "high": round(snap.high, 6),
            "low": round(snap.low, 6),
            "atr": round(snap.atr, 6),
            "adx": round(snap.adx, 2),
            "bb_width": round(snap.bb_width, 6),
            "ema20": round(snap.ema20, 6),
            "ema20_slope": round(snap.ema20_slope, 8),
            "ema200": round(snap.ema200, 6),
            "above_ema200": snap.close > snap.ema200,
            # Calibration
            "base_atr_d1": round(calibration.base_atr, 6),
            "sideway_threshold": round(calibration.sideway_threshold, 6),
            "min_slope": round(calibration.min_slope, 8),
            "calibrated_at": calibration.calibrated_at.isoformat(),
            # Shield
            "shield_passed": shield.passed,
            "adx_ok": shield.adx_ok,
            "bbwidth_ok": shield.bbwidth_ok,
            "slope_ok": shield.slope_ok,
        }

    def register_order_state(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        amount: float,
        stop_loss: float,
        take_profit_1: float,
        tp2_initial_trail: float,
        atr: float,
    ) -> None:
        """
        Đăng ký trạng thái lệnh mới sau khi entry được thực thi.
        Được gọi từ bên ngoài (bot_engine hoặc order_manager) sau khi lệnh khớp.
        """
        self._order_states[symbol] = OrderState(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            amount_total=amount,
            amount_remaining=amount,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2_trail=tp2_initial_trail,
            atr_at_entry=atr,
        )
        logger.info(
            f"[ADTS][{symbol}] OrderState đăng ký: "
            f"{side.upper()} entry={entry_price:.4f} "
            f"SL={stop_loss:.4f} TP1={take_profit_1:.4f} "
            f"Trail_init={tp2_initial_trail:.4f}"
        )

    def clear_order_state(self, symbol: str) -> None:
        """Xóa order state khi lệnh đã đóng hoàn toàn."""
        self._order_states.pop(symbol, None)
        logger.debug(f"[ADTS][{symbol}] OrderState đã xóa")
