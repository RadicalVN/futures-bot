"""
sma_macd_cross.py — Chiến lược: SMA + MACD Cross (TuanTV1008)

Entry LONG khi đủ 3 điều kiện:
  1. MACD-Signal chuyển từ đỏ/cam → tím/xanh lá/xanh dương (momentum đảo chiều lên)
  2. MACD cắt qua MACD-Signal từ dưới lên (golden cross)
  3. Nến đóng cửa phía trên đường MA (giá cắt qua MA từ dưới lên)
  → Giá vào tiệm cận đường MA

Exit LONG khi:
  - Nến đóng cửa dưới MA
  - MA chuyển đỏ hoặc cam (slope âm)
  - MACD-Signal chuyển đỏ hoặc cam
  - MACD đỏ trong khi MA xanh lá (phân kỳ giảm)

Entry SHORT khi đủ 3 điều kiện:
  1. MACD-Signal chuyển từ xanh dương/xanh lá → tím/đỏ/cam (momentum đảo chiều xuống)
  2. MACD cắt qua MACD-Signal từ trên xuống (death cross)
  3. Nến đóng cửa phía dưới đường MA (giá cắt qua MA từ trên xuống)
  → Giá vào tiệm cận đường MA

Exit SHORT khi:
  - Nến đóng cửa trên MA
  - MA chuyển xanh dương hoặc xanh lá (slope dương)
  - MACD-Signal chuyển xanh dương hoặc xanh lá
  - MACD xanh dương trong khi MA cam (phân kỳ tăng)
"""
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, StrategySignal
from src.data.indicators import add_custom_sma_to_df, add_custom_macd_to_df


# ── Nhóm màu momentum ─────────────────────────────────────────────────────────
# Màu "đang tăng" (slope dương)
MA_BULLISH   = {"blue", "green"}      # xanh dương (tăng tốc) + xanh lá (giảm tốc nhưng vẫn lên)
# Màu "đang giảm" (slope âm)
MA_BEARISH   = {"red", "orange"}      # đỏ (tăng tốc xuống) + cam (giảm tốc xuống)
# Màu "đảo chiều / trung tính"
MA_REVERSAL  = {"purple", "yellow"}

# Màu signal momentum — dùng hàm _slope_color tương tự chart.js
# Tính từ 3 điểm liên tiếp của signal line


def _slope_color(curr: float, prev: float, older: float) -> str:
    """
    Tính màu slope giống rule chart.js slopeColor:
    - curr > prev + tăng tốc → blue
    - curr > prev + giảm tốc → green
    - curr < prev + tăng tốc → red
    - curr < prev + giảm tốc → orange
    - curr == prev           → yellow
    """
    if curr == prev:
        return "yellow"
    slope_curr = curr - prev
    slope_prev = prev - older
    if curr > prev:
        return "blue" if slope_curr >= slope_prev else "green"
    else:
        return "red" if slope_curr <= slope_prev else "orange"


class SmaMacdCrossStrategy(BaseStrategy):
    """
    Chiến lược SMA + MACD Cross — kết hợp Custom SMA và Custom MACD TuanTV1008.

    Tham số:
    - fast_len (int): SMA nhanh, mặc định 1
    - slow_len (int): SMA chậm, mặc định 5
    - len_c (int): Chu kỳ làm mượt SMA, mặc định 200
    - factor (float): Hệ số nhiễu SMA, mặc định 0.05
    - bb_length (int): Chu kỳ BB/MA cơ sở, mặc định 50
    - macd_fast (int): MACD fast, mặc định 12
    - macd_slow (int): MACD slow, mặc định 26
    - macd_signal_length (int): MACD signal smoothing, mặc định 500
    - macd_src (str): "EMA" | "SMA", mặc định "EMA"
    - macd_sig_type (str): "EMA" | "SMA", mặc định "EMA"
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "sma_macd_cross"
        # SMA params
        self.fast_len    = self.get_param("fast_len", 1)
        self.slow_len    = self.get_param("slow_len", 5)
        self.len_c       = self.get_param("len_c", 200)
        self.factor      = self.get_param("factor", 0.05)
        self.bb_length   = self.get_param("bb_length", 50)
        # MACD params
        self.macd_fast          = self.get_param("macd_fast", 12)
        self.macd_slow          = self.get_param("macd_slow", 26)
        self.macd_signal_length = self.get_param("macd_signal_length", 500)
        self.macd_src           = self.get_param("macd_src", "EMA")
        self.macd_sig_type      = self.get_param("macd_sig_type", "EMA")

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        df = pd.DataFrame(ohlcv_data, columns=["timestamp", "open", "high", "low", "close", "volume"])

        n_required = max(self.slow_len, self.len_c, self.bb_length, self.macd_signal_length) + 10
        if len(df) < n_required:
            return StrategySignal(signal="none", symbol=symbol, price=0, reason="Không đủ dữ liệu")

        # ── Tính indicators ───────────────────────────────────────────────────
        df = add_custom_sma_to_df(
            df,
            fast_len=self.fast_len, slow_len=self.slow_len,
            len_c=self.len_c, factor=self.factor, bb_length=self.bb_length,
        )
        df = add_custom_macd_to_df(
            df,
            fast=self.macd_fast, slow=self.macd_slow,
            signal_length=self.macd_signal_length,
            src=self.macd_src, sig_type=self.macd_sig_type,
        )

        # ── Lấy giá trị hiện tại và trước đó ─────────────────────────────────
        close_curr  = df["close"].iloc[-1]
        close_prev  = df["close"].iloc[-2]

        ma_curr     = df["custom_sma_basis"].iloc[-1]
        ma_prev     = df["custom_sma_basis"].iloc[-2]
        ma_older    = df["custom_sma_basis"].iloc[-3]

        macd_curr   = df["custom_macd"].iloc[-1]
        macd_prev   = df["custom_macd"].iloc[-2]
        macd_older  = df["custom_macd"].iloc[-3]

        sig_curr    = df["custom_macd_signal"].iloc[-1]
        sig_prev    = df["custom_macd_signal"].iloc[-2]
        sig_older   = df["custom_macd_signal"].iloc[-3]

        # ── Tính màu slope ────────────────────────────────────────────────────
        ma_color_curr  = _slope_color(ma_curr,  ma_prev,  ma_older)
        ma_color_prev  = _slope_color(ma_prev,  ma_older, df["custom_sma_basis"].iloc[-4])

        sig_color_curr = _slope_color(sig_curr, sig_prev, sig_older)
        sig_color_prev = _slope_color(sig_prev, sig_older, df["custom_macd_signal"].iloc[-4])

        macd_color_curr = _slope_color(macd_curr, macd_prev, macd_older)

        # ── Xác định vị thế hiện tại ──────────────────────────────────────────
        pos_side = None
        for pos in current_positions:
            pos_sym = pos.get("symbol", "").replace("/", "")
            if pos_sym == symbol.replace("/", ""):
                pos_side = pos.get("side", "")
                break

        final_signal = "none"
        reason = (
            f"Chờ | MA={ma_color_curr} | Sig={sig_color_curr} | "
            f"MACD={macd_color_curr} | Close={'trên' if close_curr > ma_curr else 'dưới'} MA"
        )

        # ══════════════════════════════════════════════════════════════════════
        # EXIT LOGIC (ưu tiên kiểm tra trước)
        # ══════════════════════════════════════════════════════════════════════
        if pos_side == "long":
            exit_reason = None

            # 1. Nến đóng cửa dưới MA
            if close_curr < ma_curr:
                exit_reason = f"Đóng LONG: Giá đóng cửa dưới MA ({close_curr:.4f} < {ma_curr:.4f})"

            # 2. MA chuyển đỏ hoặc cam
            elif ma_color_curr in MA_BEARISH:
                exit_reason = f"Đóng LONG: MA chuyển {ma_color_curr}"

            # 3. MACD-Signal chuyển đỏ hoặc cam
            elif sig_color_curr in MA_BEARISH:
                exit_reason = f"Đóng LONG: MACD-Signal chuyển {sig_color_curr}"

            # 4. MACD đỏ trong khi MA xanh lá (phân kỳ giảm)
            elif macd_color_curr == "red" and ma_color_curr == "green":
                exit_reason = f"Đóng LONG: MACD đỏ + MA xanh lá (phân kỳ giảm)"

            if exit_reason:
                final_signal = "close_long"
                reason = exit_reason

        elif pos_side == "short":
            exit_reason = None

            # 1. Nến đóng cửa trên MA
            if close_curr > ma_curr:
                exit_reason = f"Đóng SHORT: Giá đóng cửa trên MA ({close_curr:.4f} > {ma_curr:.4f})"

            # 2. MA chuyển xanh dương hoặc xanh lá
            elif ma_color_curr in MA_BULLISH:
                exit_reason = f"Đóng SHORT: MA chuyển {ma_color_curr}"

            # 3. MACD-Signal chuyển xanh dương hoặc xanh lá
            elif sig_color_curr in MA_BULLISH:
                exit_reason = f"Đóng SHORT: MACD-Signal chuyển {sig_color_curr}"

            # 4. MACD xanh dương trong khi MA cam (phân kỳ tăng)
            elif macd_color_curr == "blue" and ma_color_curr == "orange":
                exit_reason = f"Đóng SHORT: MACD xanh dương + MA cam (phân kỳ tăng)"

            if exit_reason:
                final_signal = "close_short"
                reason = exit_reason

        # ══════════════════════════════════════════════════════════════════════
        # ENTRY LOGIC
        # ══════════════════════════════════════════════════════════════════════
        elif pos_side is None:

            # ── LONG: 3 điều kiện ─────────────────────────────────────────────
            # Điều kiện 1: MACD-Signal chuyển từ đỏ/cam → tím/xanh lá/xanh dương
            sig_was_bearish = sig_color_prev in MA_BEARISH
            sig_now_bullish = sig_color_curr in (MA_BULLISH | MA_REVERSAL)
            cond1_long = sig_was_bearish and sig_now_bullish

            # Điều kiện 2: MACD cắt qua Signal từ dưới lên (golden cross)
            cond2_long = (macd_prev <= sig_prev) and (macd_curr > sig_curr)

            # Điều kiện 3: Nến đóng cửa trên MA (giá cắt qua MA từ dưới lên)
            cond3_long = (close_prev <= ma_prev) and (close_curr > ma_curr)

            if cond1_long and cond2_long and cond3_long:
                final_signal = "long"
                reason = (
                    f"Mở LONG: Signal {sig_color_prev}→{sig_color_curr} | "
                    f"MACD golden cross | Giá cắt lên MA ({close_curr:.4f}>{ma_curr:.4f})"
                )

            # ── SHORT: 3 điều kiện ────────────────────────────────────────────
            # Điều kiện 1: MACD-Signal chuyển từ xanh dương/xanh lá → tím/đỏ/cam
            sig_was_bullish = sig_color_prev in MA_BULLISH
            sig_now_bearish = sig_color_curr in (MA_BEARISH | MA_REVERSAL)
            cond1_short = sig_was_bullish and sig_now_bearish

            # Điều kiện 2: MACD cắt qua Signal từ trên xuống (death cross)
            cond2_short = (macd_prev >= sig_prev) and (macd_curr < sig_curr)

            # Điều kiện 3: Nến đóng cửa dưới MA (giá cắt qua MA từ trên xuống)
            cond3_short = (close_prev >= ma_prev) and (close_curr < ma_curr)

            if cond1_short and cond2_short and cond3_short:
                final_signal = "short"
                reason = (
                    f"Mở SHORT: Signal {sig_color_prev}→{sig_color_curr} | "
                    f"MACD death cross | Giá cắt xuống MA ({close_curr:.4f}<{ma_curr:.4f})"
                )

        return StrategySignal(
            signal=final_signal,
            symbol=symbol,
            price=ma_curr if final_signal in ("long", "short") else close_curr,
            reason=reason,
            metadata={
                "ma_color": ma_color_curr,
                "sig_color": sig_color_curr,
                "macd_color": macd_color_curr,
                "ma": round(float(ma_curr), 6),
                "macd": round(float(macd_curr), 8),
                "macd_signal": round(float(sig_curr), 8),
                "close": round(float(close_curr), 6),
                "trend": int(df["custom_sma_trend"].iloc[-1]),
                "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                "momentum": ma_color_curr,   # dùng ma_color làm momentum để hiển thị log
                "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
            }
        )
