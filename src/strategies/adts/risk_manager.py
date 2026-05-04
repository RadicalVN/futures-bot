"""
adts/risk_manager.py — Quản trị rủi ro & Position Sizing cho ADTS

Dynamic Position Sizing:
  - Rủi ro cố định 1% tài khoản mỗi lệnh
  - Khối lượng = Risk_USDT / (SL_distance * contract_value)

Adaptive SL/TP:
  - SL  = 1.5 × ATR (dynamic)
  - TP1 = Entry ± (SL_distance × 1.2)  → chốt 50%
  - TP2 = Trailing Stop 2.0 × ATR

Emergency Exit:
  - ADX < 20 hoặc BBWidth < Sideway_Threshold → đóng 50% còn lại

Logging: Risk → sizing → SL/TP calculation
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from .models import ADTSConfig, PositionPlanADTS


def calculate_position_plan(
    balance_usdt: float,
    entry_price: float,
    side: str,
    atr: float,
    symbol: str,
    config: ADTSConfig,
    contract_size: float = 1.0,
    min_amount: float = 0.001,
    amount_precision: int = 3,
) -> Optional[PositionPlanADTS]:
    """
    Tính toán kế hoạch vào lệnh đầy đủ theo ADTS risk model.

    Args:
        balance_usdt: Số dư USDT tự do
        entry_price: Giá vào lệnh dự kiến
        side: "long" hoặc "short"
        atr: ATR hiện tại (intraday timeframe)
        symbol: Symbol giao dịch
        config: ADTSConfig
        contract_size: Kích thước 1 contract (mặc định 1.0 cho USDT-M)
        min_amount: Số lượng tối thiểu
        amount_precision: Độ chính xác số lượng

    Returns:
        PositionPlanADTS hoặc None nếu không hợp lệ
    """
    tag = f"[RiskManager][{symbol}]"

    if balance_usdt <= 0:
        logger.error(f"{tag} Số dư USDT = 0, không thể tạo lệnh")
        return None

    if atr <= 0:
        logger.error(f"{tag} ATR không hợp lệ: {atr}")
        return None

    # ── Bước 1: Tính Stop Loss distance ──────────────────────────────────────
    atr_sl_distance  = config.sl_atr_mult * atr          # SL động: 1.5 × ATR
    hard_sl_distance = entry_price * config.hard_sl_pct  # Hard SL: 3% giá entry

    # Lấy mức nào gần entry hơn (tighter) để bảo vệ vốn tốt hơn
    sl_distance = min(atr_sl_distance, hard_sl_distance)
    sl_source   = "ATR" if atr_sl_distance <= hard_sl_distance else "Hard"

    if side == "long":
        stop_loss = entry_price - sl_distance
    else:
        stop_loss = entry_price + sl_distance

    logger.debug(
        f"{tag} ATR_SL={atr_sl_distance:.4f} | Hard_SL={hard_sl_distance:.4f} "
        f"→ dùng {sl_source}_SL={sl_distance:.4f} → SL={stop_loss:.4f}"
    )

    # ── Bước 2: Dynamic Position Sizing (1% risk) ─────────────────────────────
    risk_usdt = balance_usdt * config.risk_pct  # 1% tài khoản
    # amount = risk_usdt / (sl_distance * contract_size)
    # Với USDT-M futures: contract_size = 1 coin, giá trị = amount * entry_price
    # Nhưng risk thực = amount * sl_distance (không tính leverage vì isolated margin)
    amount = risk_usdt / (sl_distance * contract_size)
    amount = round(amount, amount_precision)

    logger.debug(
        f"{tag} Risk = {config.risk_pct*100:.1f}% × ${balance_usdt:.2f} = ${risk_usdt:.2f} "
        f"→ Amount = ${risk_usdt:.2f} / {sl_distance:.4f} = {amount:.{amount_precision}f}"
    )

    if amount < min_amount:
        logger.warning(
            f"{tag} Amount {amount} < min_amount {min_amount}. "
            f"Số dư quá nhỏ hoặc ATR quá lớn."
        )
        return None

    # ── Bước 3: TP1 = R:R 1:1.2 (chốt 50%) ──────────────────────────────────
    tp1_distance = sl_distance * config.tp1_rr  # 1.2 × SL_distance
    if side == "long":
        take_profit_1 = entry_price + tp1_distance
    else:
        take_profit_1 = entry_price - tp1_distance

    logger.debug(
        f"{tag} TP1 = entry ± {tp1_distance:.4f} (R:R 1:{config.tp1_rr}) = {take_profit_1:.4f}"
    )

    # ── Bước 4: TP2 Trailing Stop khởi tạo = 2.0 × ATR ──────────────────────
    tp2_trail_distance = config.tp2_trail_atr_mult * atr
    if side == "long":
        tp2_initial = entry_price - tp2_trail_distance  # Trailing bắt đầu dưới entry
    else:
        tp2_initial = entry_price + tp2_trail_distance

    logger.info(
        f"{tag} Kế hoạch {side.upper()} | "
        f"Entry={entry_price:.4f} | "
        f"SL={stop_loss:.4f} (-{sl_distance:.4f}, {sl_source}) | "
        f"TP1={take_profit_1:.4f} (+{tp1_distance:.4f}) | "
        f"TP2_Trail_Init={tp2_initial:.4f} | "
        f"Amount={amount} | Risk=${risk_usdt:.2f}"
    )

    return PositionPlanADTS(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        amount=amount,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2_initial_trail=tp2_initial,
        atr=atr,
        risk_usdt=risk_usdt,
        leverage=config.leverage,
    )


def check_emergency_exit(
    adx: float,
    bb_width: float,
    sideway_threshold: float,
    config: ADTSConfig,
) -> tuple[bool, str]:
    """
    Kiểm tra điều kiện Emergency Exit.

    Kích hoạt khi:
      - ADX đột ngột cắt xuống dưới 20, HOẶC
      - BBWidth thu hẹp dưới Sideway_Threshold

    Returns:
        (should_emergency_exit: bool, reason: str)
    """
    if adx < config.emergency_adx_threshold:
        return (
            True,
            f"🚨 Emergency Exit: ADX={adx:.1f} < {config.emergency_adx_threshold} (xu hướng suy yếu)",
        )

    if bb_width < sideway_threshold:
        return (
            True,
            f"🚨 Emergency Exit: BBWidth={bb_width:.5f} < Threshold={sideway_threshold:.5f} (thị trường nén lại)",
        )

    return False, ""
