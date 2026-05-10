"""
analytics.py — Shared Performance Analytics Math Engine.

Module này chứa toàn bộ logic tính toán metrics thuần túy (pure functions),
không phụ thuộc vào DB hay exchange. Dùng chung cho:
  - src/apps/analytics/service.py  (Live Trading analytics)
  - src/core/backtest_engine.py    (Backtest analytics)

Đảm bảo math của Backtest và Live Trading là một — không duplicate.

Public API:
    calc_trade_metrics(pnl_list, durations_hours) -> TradeMetrics
    calc_max_drawdown_from_pnl(pnl_list)          -> float
    calc_sharpe_ratio(daily_returns)               -> float
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ── Output Dataclass ──────────────────────────────────────────────────────────

@dataclass
class TradeMetrics:
    """Kết quả tính toán metrics từ danh sách lệnh.

    Attributes:
        total_trades: Tổng số lệnh đã đóng.
        winning_trades: Số lệnh thắng (pnl > 0).
        losing_trades: Số lệnh thua (pnl < 0).
        win_rate_pct: Tỷ lệ thắng (0.0 - 100.0).
        net_pnl: Tổng PnL ròng (USDT).
        gross_profit: Tổng tiền thắng (USDT, luôn dương).
        gross_loss: Tổng tiền thua (USDT, luôn dương).
        profit_factor: gross_profit / gross_loss. None nếu không có lệnh thua.
        max_drawdown: Độ sụt giảm lớn nhất (USDT, luôn dương).
        avg_duration_hours: Thời gian giữ lệnh trung bình (giờ).
        best_trade: PnL cao nhất (USDT).
        worst_trade: PnL thấp nhất (USDT).
        sharpe_ratio: Sharpe Ratio annualized. None nếu không đủ dữ liệu.
        total_commission: Tổng phí giao dịch (USDT).
    """
    total_trades:       int
    winning_trades:     int
    losing_trades:      int
    win_rate_pct:       float
    net_pnl:            float
    gross_profit:       float
    gross_loss:         float
    profit_factor:      Optional[float]
    max_drawdown:       float
    avg_duration_hours: float
    best_trade:         float
    worst_trade:        float
    sharpe_ratio:       Optional[float]
    total_commission:   float

    def to_dict(self) -> dict:
        """Chuyển sang dict JSON-serializable cho API response.

        Returns:
            Dict chứa tất cả chỉ số.
        """
        return {
            "total_trades":       self.total_trades,
            "winning_trades":     self.winning_trades,
            "losing_trades":      self.losing_trades,
            "win_rate_pct":       self.win_rate_pct,
            "net_pnl":            self.net_pnl,
            "gross_profit":       self.gross_profit,
            "gross_loss":         self.gross_loss,
            "profit_factor":      self.profit_factor,
            "max_drawdown":       self.max_drawdown,
            "avg_duration_hours": self.avg_duration_hours,
            "best_trade":         self.best_trade,
            "worst_trade":        self.worst_trade,
            "sharpe_ratio":       self.sharpe_ratio,
            "total_commission":   self.total_commission,
        }


# ── Pure Math Functions ───────────────────────────────────────────────────────

def calc_trade_metrics(
    pnl_list:         list[float],
    durations_hours:  list[float],
    commission_list:  Optional[list[float]] = None,
    equity_curve:     Optional[list[float]] = None,
) -> TradeMetrics:
    """Tính toán đầy đủ các chỉ số hiệu suất từ danh sách PnL.

    Hàm thuần túy (pure function) — không đọc DB, không gọi I/O.
    Dùng chung cho cả Backtest và Live Trading analytics.

    Args:
        pnl_list: Danh sách PnL ròng từng lệnh (USDT). Có thể âm.
        durations_hours: Thời gian giữ lệnh tương ứng (giờ).
        commission_list: Phí giao dịch từng lệnh (USDT, luôn dương).
            None = không tính commission.
        equity_curve: Danh sách equity tại từng nến để tính MDD chính xác.
            None = tính MDD từ pnl_list (kém chính xác hơn).

    Returns:
        TradeMetrics với đầy đủ chỉ số.
    """
    if not pnl_list:
        return _empty_metrics()

    total    = len(pnl_list)
    wins     = sum(1 for p in pnl_list if p > 0)
    losses   = sum(1 for p in pnl_list if p < 0)
    win_rate = round(wins / total * 100, 2) if total > 0 else 0.0

    net_pnl      = round(sum(pnl_list), 4)
    gross_profit = round(sum(p for p in pnl_list if p > 0), 4)
    gross_loss   = round(abs(sum(p for p in pnl_list if p < 0)), 4)
    profit_factor = _safe_divide(gross_profit, gross_loss)

    if equity_curve:
        max_dd = calc_max_drawdown_from_equity(equity_curve)
    else:
        max_dd = calc_max_drawdown_from_pnl(pnl_list)

    avg_dur = round(sum(durations_hours) / len(durations_hours), 2) if durations_hours else 0.0
    best    = round(max(pnl_list), 4)
    worst   = round(min(pnl_list), 4)

    sharpe = calc_sharpe_ratio(_pnl_to_daily_returns(pnl_list)) if len(pnl_list) >= 5 else None

    total_comm = round(sum(commission_list), 4) if commission_list else 0.0

    return TradeMetrics(
        total_trades=total,
        winning_trades=wins,
        losing_trades=losses,
        win_rate_pct=win_rate,
        net_pnl=net_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        avg_duration_hours=avg_dur,
        best_trade=best,
        worst_trade=worst,
        sharpe_ratio=sharpe,
        total_commission=total_comm,
    )


def calc_max_drawdown_from_pnl(pnl_list: list[float]) -> float:
    """Tính Max Drawdown từ danh sách PnL lệnh (equity curve method).

    Thuật toán: xây dựng equity curve tích lũy → peak tracking.

    Args:
        pnl_list: Danh sách PnL ròng từng lệnh theo thứ tự thời gian.

    Returns:
        Max drawdown (USDT, luôn dương). 0.0 nếu không có lệnh.
    """
    if not pnl_list:
        return 0.0

    equity = 0.0
    peak   = 0.0
    max_dd = 0.0

    for pnl in pnl_list:
        equity += pnl
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return round(max_dd, 4)


def calc_max_drawdown_from_equity(equity_curve: list[float]) -> float:
    """Tính Max Drawdown từ equity curve (chính xác hơn — bao gồm unrealized).

    Dùng khi có dense equity curve từ backtest (ghi nhận tại mỗi nến).

    Args:
        equity_curve: Danh sách giá trị equity tại từng nến.

    Returns:
        Max drawdown (USDT, luôn dương). 0.0 nếu rỗng.
    """
    if not equity_curve:
        return 0.0

    peak   = equity_curve[0]
    max_dd = 0.0

    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd

    return round(max_dd, 4)


def calc_sharpe_ratio(daily_returns: list[float]) -> Optional[float]:
    """Tính Sharpe Ratio annualized (risk-free rate = 0).

    Công thức: mean(returns) / std(returns) * sqrt(252).

    Args:
        daily_returns: Danh sách lợi nhuận hàng ngày (%).

    Returns:
        Sharpe Ratio (2 chữ số thập phân), hoặc None nếu không đủ dữ liệu.
    """
    if len(daily_returns) < 2:
        return None

    n    = len(daily_returns)
    mean = sum(daily_returns) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)
    std  = math.sqrt(variance)

    if std == 0:
        return None

    return round(mean / std * math.sqrt(252), 2)


# ── Internal Helpers ──────────────────────────────────────────────────────────

def _safe_divide(numerator: float, denominator: float) -> Optional[float]:
    """Chia an toàn — trả về None nếu mẫu số bằng 0.

    Args:
        numerator: Tử số.
        denominator: Mẫu số.

    Returns:
        Kết quả chia (2 chữ số thập phân), hoặc None.
    """
    if denominator == 0:
        return None
    return round(numerator / denominator, 2)


def _pnl_to_daily_returns(pnl_list: list[float]) -> list[float]:
    """Chuyển danh sách PnL lệnh sang daily returns (%).

    Giả định mỗi lệnh là 1 "ngày" để tính Sharpe đơn giản.
    Chuẩn hóa theo initial_equity = 10000 USDT.

    Args:
        pnl_list: Danh sách PnL ròng từng lệnh.

    Returns:
        Danh sách daily returns (%).
    """
    base = 10000.0
    return [p / base * 100 for p in pnl_list]


def _empty_metrics() -> TradeMetrics:
    """Trả về TradeMetrics rỗng khi không có lệnh nào.

    Returns:
        TradeMetrics với tất cả giá trị bằng 0 / None.
    """
    return TradeMetrics(
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        win_rate_pct=0.0,
        net_pnl=0.0,
        gross_profit=0.0,
        gross_loss=0.0,
        profit_factor=None,
        max_drawdown=0.0,
        avg_duration_hours=0.0,
        best_trade=0.0,
        worst_trade=0.0,
        sharpe_ratio=None,
        total_commission=0.0,
    )
