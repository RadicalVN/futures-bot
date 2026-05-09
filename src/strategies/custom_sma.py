"""
custom_sma.py — Custom SMA Strategy (ittuantruong)

Chiến thuật dựa trên chỉ báo Custom SMA:
  1. Tính SMA nhanh + chậm, kết hợp và làm mượt thêm → center_line
  2. Tạo band_up / band_dn từ center_line và log(10)
  3. State machine xác định trend_direction (+1 / -1)
  4. Entry khi trend đảo chiều, Exit khi trend đảo ngược vị thế

Momentum analysis (1-phiên và n-phiên) được tính từ SMA(bb_length)
để cung cấp thêm context cho dashboard và AI filter.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from src.data.indicators import add_custom_sma_to_df
from src.strategies.base_strategy import BaseStrategy, StrategySignal


class CustomSMAStrategy(BaseStrategy):
    """Custom SMA Strategy — Zero-Core-Edit plugin.

    Kế thừa BaseStrategy và triển khai đầy đủ contract:
    - STRATEGY_NAME = "custom_sma"
    - get_required_lookback(): tự tính lookback
    - prepare_metadata(): tính indicators cho ExitMonitorService
    - analyze(): logic giao dịch đầy đủ
    """

    STRATEGY_NAME: str = "custom_sma"

    # ── Class-level contract ──────────────────────────────────────────────────

    @classmethod
    def get_required_lookback(cls, parameters: dict) -> int:
        """Tính số nến tối thiểu cần thiết.

        Args:
            parameters: Dict tham số từ Bot.parameters.

        Returns:
            Số nến tối thiểu để tính đủ SMA và momentum.
        """
        len_c      = int(parameters.get("len_c", 200))
        bb_length  = int(parameters.get("bb_length", 50))
        momentum_n = int(parameters.get("momentum_n", 3))
        return max(len_c, bb_length) * 2 + momentum_n * 2 + 10

    # ── Constructor ───────────────────────────────────────────────────────────

    def __init__(self, config: dict) -> None:
        """Khởi tạo CustomSMAStrategy với config dict từ Bot.parameters.

        Args:
            config: Dict tham số từ Bot.parameters trong DB.
        """
        super().__init__(config)

        self.fast_length:  int   = int(self.get_param("fast_length", 1))
        self.slow_length:  int   = int(self.get_param("slow_length", 5))
        self.signal_length: int  = int(self.get_param("len_c", 200))
        self.trend_factor: float = float(self.get_param("factor", 0.05))
        self.bb_length:    int   = int(self.get_param("bb_length", 50))
        self.bb_mult:      float = float(self.get_param("bb_mult", 2.0))
        self.momentum_n:   int   = int(self.get_param("momentum_n", 3))
        self.min_slope_pct:    float = float(self.get_param("min_slope_pct", 0.0))
        self.min_momentum_pct: float = float(self.get_param("min_momentum_pct", 0.0))

    # ── prepare_metadata (BaseStrategy contract) ──────────────────────────────

    async def prepare_metadata(self, df: pd.DataFrame) -> dict:
        """Tính Custom SMA indicators cho ExitMonitorService.

        Args:
            df: DataFrame OHLCV với columns [timestamp, open, high, low, close, volume].

        Returns:
            Dict metadata với trend, momentum, slope. Trả về {} nếu lỗi.
        """
        try:
            df = add_custom_sma_to_df(
                df.copy(),
                fast_len=self.fast_length,
                slow_len=self.slow_length,
                len_c=self.signal_length,
                factor=self.trend_factor,
                bb_length=self.bb_length,
                bb_mult=self.bb_mult,
                momentum_n=self.momentum_n,
            )
            trend    = int(df["custom_sma_trend"].iloc[-1])
            prev_t   = int(df["custom_sma_trend"].iloc[-2])
            momentum = str(df["custom_sma_momentum"].iloc[-1])
            slope    = float(df["custom_sma_slope_pct"].iloc[-1])
            mom_pct  = float(df["custom_sma_momentum_pct"].iloc[-1])
            mom_n    = str(df["custom_sma_momentum_n"].iloc[-1])
            mom_n_pct = float(df["custom_sma_momentum_n_pct"].iloc[-1])
            return {
                "trend":          trend,
                "prev_trend":     prev_t,
                "momentum":       momentum,
                "slope_pct":      round(slope, 4),
                "momentum_pct":   round(mom_pct, 4),
                "momentum_n":     mom_n,
                "momentum_n_pct": round(mom_n_pct, 4),
            }
        except Exception as exc:
            logger.debug(f"[CustomSMA] prepare_metadata loi: {exc}")
            return {}

    # ── analyze (BaseStrategy contract) ──────────────────────────────────────

    async def analyze(
        self,
        symbol:            str,
        ohlcv_data:        list,
        current_positions: list,
    ) -> StrategySignal:
        """Phan tich OHLCV va tra ve StrategySignal.

        Args:
            symbol: Symbol giao dich (vd: "BTC/USDT").
            ohlcv_data: List [[timestamp_ms, open, high, low, close, volume], ...].
            current_positions: List vi the dang mo tu exchange.

        Returns:
            StrategySignal voi signal, price, reason, metadata.
        """
        min_len = max(self.slow_length, self.signal_length) * 2
        if len(ohlcv_data) < min_len:
            return StrategySignal(
                signal="none", symbol=symbol, price=0,
                reason=f"Khong du du lieu: co {len(ohlcv_data)}, can >={min_len}",
            )

        df = self._to_dataframe(ohlcv_data)

        # Tinh tat ca indicators qua add_custom_sma_to_df (tai su dung tu indicators.py)
        df = add_custom_sma_to_df(
            df,
            fast_len=self.fast_length,
            slow_len=self.slow_length,
            len_c=self.signal_length,
            factor=self.trend_factor,
            bb_length=self.bb_length,
            bb_mult=self.bb_mult,
            momentum_n=self.momentum_n,
        )

        # Kiem tra du lieu hop le
        if df["custom_sma_trend"].isna().all():
            return StrategySignal(
                signal="none", symbol=symbol, price=0,
                reason="Khong du du lieu hop le de tinh trend",
            )

        current_trend = int(df["custom_sma_trend"].iloc[-1])
        prev_trend    = int(df["custom_sma_trend"].iloc[-2])
        current_price = float(df["close"].iloc[-1])

        # Lay momentum info de build reason va metadata
        mom_info = self._extract_momentum_info(df)

        # Uu tien: kiem tra exit truoc
        exit_signal = self._check_exit(symbol, current_trend, current_price, current_positions, mom_info)
        if exit_signal is not None:
            return exit_signal

        # Kiem tra entry
        entry_signal = self._check_entry(
            symbol, current_trend, prev_trend, current_price, mom_info
        )
        if entry_signal is not None:
            return entry_signal

        # Khong co tin hieu
        reason = (
            f"Cho tin hieu | Trend={current_trend} | "
            f"Mom(1): {mom_info['momentum']} ({mom_info['momentum_pct']:.4f}%) | "
            f"Mom({self.momentum_n}): {mom_info['momentum_n']} ({mom_info['momentum_n_pct']:.4f}%) | "
            f"Doc: {mom_info['slope_pct']:.4f}%"
        )
        return StrategySignal(
            signal="none",
            symbol=symbol,
            price=current_price,
            reason=reason,
            metadata=self._build_metadata(df, current_trend, mom_info),
        )

    # ── Entry / Exit helpers ──────────────────────────────────────────────────

    def _check_entry(
        self,
        symbol:        str,
        current_trend: int,
        prev_trend:    int,
        price:         float,
        mom_info:      dict,
    ) -> StrategySignal | None:
        """Kiem tra dieu kien vao lenh khi trend dao chieu.

        Args:
            symbol: Symbol giao dich.
            current_trend: Trend hien tai (+1 / -1 / 0).
            prev_trend: Trend phien truoc.
            price: Gia dong cua hien tai.
            mom_info: Dict chua slope_pct, momentum_pct, momentum_n_pct, ...

        Returns:
            StrategySignal entry hoac None.
        """
        slope    = mom_info["slope_pct"]
        mom_pct  = mom_info["momentum_pct"]
        mom_n    = mom_info["momentum_n"]
        mom_n_pct = mom_info["momentum_n_pct"]
        momentum = mom_info["momentum"]

        # Trend dao chieu len -> LONG
        if current_trend == 1 and prev_trend == -1:
            if slope >= self.min_slope_pct and mom_pct >= self.min_momentum_pct:
                reason = (
                    f"Mo LONG: Custom SMA Trend Tang | "
                    f"Mom(1): {momentum} ({mom_pct:.4f}%) | "
                    f"Mom({self.momentum_n}): {mom_n} ({mom_n_pct:.4f}%) | "
                    f"Doc: {slope:.4f}%"
                )
                return StrategySignal(
                    signal="long", symbol=symbol, price=price, reason=reason
                )
            return StrategySignal(
                signal="none", symbol=symbol, price=price,
                reason=(
                    f"Bo qua LONG: Doc hoac Gia toc khong dat nguong | "
                    f"slope={slope:.4f}% (min={self.min_slope_pct}) | "
                    f"mom={mom_pct:.4f}% (min={self.min_momentum_pct})"
                ),
            )

        # Trend dao chieu xuong -> SHORT
        if current_trend == -1 and prev_trend == 1:
            if slope <= -self.min_slope_pct and mom_pct <= -self.min_momentum_pct:
                reason = (
                    f"Mo SHORT: Custom SMA Trend Giam | "
                    f"Mom(1): {momentum} ({mom_pct:.4f}%) | "
                    f"Mom({self.momentum_n}): {mom_n} ({mom_n_pct:.4f}%) | "
                    f"Doc: {slope:.4f}%"
                )
                return StrategySignal(
                    signal="short", symbol=symbol, price=price, reason=reason
                )
            return StrategySignal(
                signal="none", symbol=symbol, price=price,
                reason=(
                    f"Bo qua SHORT: Doc hoac Gia toc khong dat nguong | "
                    f"slope={slope:.4f}% (min={-self.min_slope_pct}) | "
                    f"mom={mom_pct:.4f}% (min={-self.min_momentum_pct})"
                ),
            )

        return None

    def _check_exit(
        self,
        symbol:            str,
        current_trend:     int,
        price:             float,
        current_positions: list,
        mom_info:          dict,
    ) -> StrategySignal | None:
        """Kiem tra dieu kien dong lenh khi trend dao nguoc vi the.

        Args:
            symbol: Symbol giao dich.
            current_trend: Trend hien tai.
            price: Gia dong cua hien tai.
            current_positions: List vi the dang mo.
            mom_info: Dict momentum info.

        Returns:
            StrategySignal exit hoac None.
        """
        sym_clean = symbol.replace("/", "")
        for pos in current_positions:
            pos_sym = pos.get("symbol", "").replace("/", "")
            if pos_sym != sym_clean:
                continue
            side = pos.get("side", "")
            if side == "long" and current_trend == -1:
                return StrategySignal(
                    signal="close_long", symbol=symbol, price=price,
                    reason="Dong LONG: Custom SMA Trend Giam",
                )
            if side == "short" and current_trend == 1:
                return StrategySignal(
                    signal="close_short", symbol=symbol, price=price,
                    reason="Dong SHORT: Custom SMA Trend Tang",
                )
        return None

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _extract_momentum_info(self, df: pd.DataFrame) -> dict:
        """Lay cac gia tri momentum tu DataFrame da tinh indicators.

        Args:
            df: DataFrame sau khi da chay add_custom_sma_to_df.

        Returns:
            Dict chua slope_pct, momentum_pct, momentum, momentum_n, momentum_n_pct.
        """
        try:
            return {
                "slope_pct":      float(df["custom_sma_slope_pct"].iloc[-1]),
                "momentum_pct":   float(df["custom_sma_momentum_pct"].iloc[-1]),
                "momentum":       str(df["custom_sma_momentum"].iloc[-1]),
                "momentum_n":     str(df["custom_sma_momentum_n"].iloc[-1]),
                "momentum_n_pct": float(df["custom_sma_momentum_n_pct"].iloc[-1]),
                "basis":          float(df["custom_sma_basis"].iloc[-1]),
                "basis_prev":     float(df["custom_sma_basis"].iloc[-2]),
            }
        except Exception:
            return {
                "slope_pct": 0.0, "momentum_pct": 0.0,
                "momentum": "yellow", "momentum_n": "yellow",
                "momentum_n_pct": 0.0, "basis": 0.0, "basis_prev": 0.0,
            }

    def _build_metadata(
        self,
        df:            pd.DataFrame,
        current_trend: int,
        mom_info:      dict,
    ) -> dict:
        """Tong hop metadata de hien thi tren dashboard va luu DB.

        Args:
            df: DataFrame sau khi da tinh indicators.
            current_trend: Trend hien tai (+1 / -1 / 0).
            mom_info: Dict momentum info tu _extract_momentum_info.

        Returns:
            Dict metadata day du.
        """
        trend_color = "blue" if current_trend == 1 else "yellow"
        basis       = mom_info["basis"]
        basis_prev  = mom_info["basis_prev"]
        momentum    = mom_info["momentum"]

        sma_color = "yellow"
        if basis > basis_prev:
            sma_color = "blue"
        elif basis < basis_prev:
            sma_color = "red"

        mom_color = _momentum_to_color(momentum)
        mom_n_color = _momentum_to_color(mom_info["momentum_n"])

        band_up  = float(df["custom_sma_up"].iloc[-1])
        band_dn  = float(df["custom_sma_dn"].iloc[-1])
        trend_val = band_up if current_trend == 1 else band_dn

        return {
            "trend":          current_trend,
            "prev_trend":     int(df["custom_sma_trend"].iloc[-2]),
            "slope_pct":      round(mom_info["slope_pct"], 4),
            "momentum_pct":   round(mom_info["momentum_pct"], 4),
            "momentum_n_pct": round(mom_info["momentum_n_pct"], 4),
            "is_sideway":     current_trend == 0,
            "plots": [
                {
                    "name": "trend",
                    "value": float(trend_val),
                    "color": trend_color,
                    "style": "circles",
                    "linewidth": 1,
                },
                {
                    "name": "SMA",
                    "value": float(basis) if not np.isnan(basis) else None,
                    "color": sma_color,
                    "style": "line",
                    "linewidth": 2,
                },
                {
                    "name": "SMA-1",
                    "value": float(basis) if not np.isnan(basis) else None,
                    "color": mom_color,
                    "style": "cross",
                    "linewidth": 3,
                    "tooltip": momentum,
                },
                {
                    "name": f"SMA-{self.momentum_n}",
                    "value": float(basis) if not np.isnan(basis) else None,
                    "color": mom_n_color,
                    "style": "cross",
                    "linewidth": 5,
                    "tooltip": (
                        f"[{self.momentum_n}p] {mom_info['momentum_n']} "
                        f"({mom_info['momentum_n_pct']:.4f}%)"
                    ),
                },
            ],
            "bands": {
                "band_up": float(band_up) if not np.isnan(band_up) else None,
                "band_dn": float(band_dn) if not np.isnan(band_dn) else None,
            },
        }

    @staticmethod
    def _to_dataframe(ohlcv_data: list) -> pd.DataFrame:
        """Chuyen list OHLCV sang DataFrame voi kieu float.

        Args:
            ohlcv_data: List [[ts_ms, o, h, l, c, v], ...].

        Returns:
            DataFrame voi columns [timestamp, open, high, low, close, volume].
        """
        df = pd.DataFrame(
            ohlcv_data,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        return df.astype({
            "open": float, "high": float, "low": float,
            "close": float, "volume": float,
        })


# ── Module-level helper ───────────────────────────────────────────────────────

def _momentum_to_color(momentum_state: str) -> str:
    """Chuyen momentum state string sang color string cho dashboard.

    Args:
        momentum_state: Gia tri tu custom_sma_momentum column
                        (vd: "blue", "red", "orange", ...).

    Returns:
        Color string tuong ung.
    """
    color_map = {
        "red":    "red",
        "orange": "orange",
        "blue":   "blue",
        "green":  "green",
        "purple": "purple",
    }
    state_lower = momentum_state.lower()
    for key, color in color_map.items():
        if key in state_lower:
            return color
    return "yellow"
