"""
test_adts_emergency_exit_2phase.py — Kiểm thử Emergency Exit 2 Giai Đoạn.

Mô phỏng 3 kịch bản:
  1. Giai đoạn 1 → Giai đoạn 2 (vi phạm 2 nến liên tiếp)
  2. Giai đoạn 1 → Recovery (vi phạm rồi phục hồi)
  3. Backward-compat: from_dict() với dict cũ không có emergency_triggered

Chạy: venv\Scripts\python.exe scripts/test_adts_emergency_exit_2phase.py
"""
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime

sys.path.insert(0, ".")

from src.strategies.adts_strategy import (
    ADTSStrategy,
    _CalibrationResult,
    _OrderState,
    _ShieldState,
)
from src.data.indicators import ADTSSnapshot


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_strategy() -> ADTSStrategy:
    return ADTSStrategy({
        "emergency_adx_threshold": 20.0,
        "emergency_close_pct":     0.5,
        "tp2_trail_atr_mult":      2.0,
        "adx_threshold":           20.0,
    })


def _make_order_state(amount: float = 0.1) -> _OrderState:
    return _OrderState(
        symbol="BTC/USDT",
        side="long",
        entry_price=95000.0,
        amount_total=amount,
        amount_remaining=amount,
        stop_loss=93575.0,
        take_profit_1=96710.0,
        take_profit_2_trail=93000.0,
        atr_at_entry=950.0,
    )


def _make_calibration() -> _CalibrationResult:
    return _CalibrationResult(
        calibrated_at=datetime.utcnow(),
        base_atr=1000.0,
        sideway_threshold=0.04,   # BBWidth phải > 0.04 để không emergency
        min_slope=0.00001,
        d1_candles_used=220,
    )


def _make_snap(adx: float = 15.0, bb_width: float = 0.03) -> ADTSSnapshot:
    """Tạo snapshot với ADX thấp (< 20) → kích hoạt emergency."""
    return ADTSSnapshot(
        close=94000.0, high=94500.0, low=93500.0,
        atr=950.0, adx=adx, bb_width=bb_width,
        ema20=94200.0, ema20_slope=10.0, ema200=90000.0,
        close_prev=93800.0, ema20_prev=94100.0,
    )


def _make_shield(adx_ok: bool = True) -> _ShieldState:
    return _ShieldState(
        adx=15.0, bb_width=0.03, ema20_slope=10.0,
        adx_ok=adx_ok, bbwidth_ok=True, slope_ok=True,
    )


# ── Test 1: Giai đoạn 1 → Giai đoạn 2 ───────────────────────────────────────

async def test_phase1_then_phase2() -> None:
    print("\n" + "="*60)
    print("TEST 1: Giai đoạn 1 → Giai đoạn 2 (vi phạm 2 nến liên tiếp)")
    print("="*60)

    strategy    = _make_strategy()
    order_state = _make_order_state(amount=0.1)
    calibration = _make_calibration()
    shield      = _make_shield()

    # Nến 1: ADX = 15 < 20 → Emergency Giai đoạn 1
    snap_n1 = _make_snap(adx=15.0)
    assert not order_state.emergency_triggered, "Ban đầu phải False"

    signal_1 = strategy._check_emergency_exit(
        "BTC/USDT", snap_n1, order_state, calibration, shield
    )

    assert signal_1 is not None, "Phải có signal Giai đoạn 1"
    assert signal_1.signal == "close_long"
    assert signal_1.metadata["partial_close"] is True
    assert signal_1.metadata["full_close"] is False
    assert signal_1.metadata["partial_pct"] == 0.5
    assert order_state.emergency_triggered is True, "Phải set emergency_triggered=True"
    assert order_state.amount_remaining == 0.05, (
        f"amount_remaining phải = 0.05 (50% còn lại), got {order_state.amount_remaining}"
    )
    assert "Giai đoạn 1/2" in signal_1.reason
    print(f"  ✅ Giai đoạn 1: signal={signal_1.signal}, partial_pct={signal_1.metadata['partial_pct']}")
    print(f"  ✅ emergency_triggered = {order_state.emergency_triggered}")
    print(f"  ✅ amount_remaining    = {order_state.amount_remaining} (50% còn lại)")

    # Nến 2: ADX vẫn = 15 < 20 → Emergency Giai đoạn 2
    snap_n2 = _make_snap(adx=15.0)
    signal_2 = strategy._check_emergency_exit(
        "BTC/USDT", snap_n2, order_state, calibration, shield
    )

    assert signal_2 is not None, "Phải có signal Giai đoạn 2"
    assert signal_2.signal == "close_long"
    assert signal_2.metadata["partial_close"] is False
    assert signal_2.metadata["full_close"] is True
    assert "Giai đoạn 2/2" in signal_2.reason
    print(f"  ✅ Giai đoạn 2: signal={signal_2.signal}, full_close={signal_2.metadata['full_close']}")
    assert "100%" in signal_2.reason or "còn lại" in signal_2.reason
    print(f"  ✅ Reason chứa thông tin đóng 100%: '{signal_2.reason[:80]}...'")
    print("  → PASS")


# ── Test 2: Giai đoạn 1 → Recovery ──────────────────────────────────────────

async def test_phase1_then_recovery() -> None:
    print("\n" + "="*60)
    print("TEST 2: Giai đoạn 1 → Recovery (Shield phục hồi)")
    print("="*60)

    strategy    = _make_strategy()
    order_state = _make_order_state(amount=0.1)
    calibration = _make_calibration()
    shield      = _make_shield()

    # Nến 1: Emergency Giai đoạn 1
    snap_n1 = _make_snap(adx=15.0)
    signal_1 = strategy._check_emergency_exit(
        "BTC/USDT", snap_n1, order_state, calibration, shield
    )
    assert signal_1 is not None
    assert order_state.emergency_triggered is True
    assert order_state.amount_remaining == 0.05
    print(f"  ✅ Giai đoạn 1 xong: emergency_triggered={order_state.emergency_triggered}, remaining={order_state.amount_remaining}")

    # Nến 2: ADX phục hồi = 25 > 20 → Recovery
    snap_n2 = _make_snap(adx=25.0, bb_width=0.05)  # cả ADX và BBWidth đều OK
    signal_2 = strategy._check_emergency_exit(
        "BTC/USDT", snap_n2, order_state, calibration, shield
    )

    assert signal_2 is None, "Recovery không được tạo signal đóng lệnh"
    assert order_state.emergency_triggered is False, "Phải reset emergency_triggered=False"
    assert order_state.amount_remaining == 0.05, "amount_remaining không được thay đổi khi recovery"
    print(f"  ✅ Recovery: signal=None, emergency_triggered={order_state.emergency_triggered}")
    print(f"  ✅ amount_remaining vẫn = {order_state.amount_remaining} (giữ nguyên 50%)")
    print("  → PASS")


# ── Test 3: Backward-compat from_dict() ──────────────────────────────────────

async def test_backward_compat_from_dict() -> None:
    print("\n" + "="*60)
    print("TEST 3: Backward-compat — from_dict() với dict cũ (không có emergency_triggered)")
    print("="*60)

    # Dict cũ từ v1.1 (trước khi thêm emergency_triggered)
    old_dict = {
        "symbol":              "BTC/USDT",
        "side":                "long",
        "entry_price":         95000.0,
        "amount_total":        0.1,
        "amount_remaining":    0.1,
        "stop_loss":           93575.0,
        "take_profit_1":       96710.0,
        "take_profit_2_trail": 93000.0,
        "atr_at_entry":        950.0,
        "tp1_hit":             False,
        "sl_moved_to_entry":   False,
        # Không có "emergency_triggered"
        "opened_at":           "2026-05-10T10:00:00",
    }

    restored = _OrderState.from_dict(old_dict)
    assert restored.emergency_triggered is False, (
        f"Backward-compat: emergency_triggered phải default=False, got {restored.emergency_triggered}"
    )
    assert restored.amount_remaining == 0.1
    assert restored.entry_price == 95000.0
    print(f"  ✅ emergency_triggered = {restored.emergency_triggered} (default False)")
    print(f"  ✅ Các field khác restore đúng: entry={restored.entry_price}, remaining={restored.amount_remaining}")
    print("  → PASS")


# ── Test 4: to_dict/from_dict round-trip với emergency_triggered=True ─────────

async def test_roundtrip_with_emergency_triggered() -> None:
    print("\n" + "="*60)
    print("TEST 4: to_dict/from_dict round-trip với emergency_triggered=True")
    print("="*60)

    state = _make_order_state(amount=0.1)
    state.emergency_triggered = True
    state.amount_remaining    = 0.05  # sau Giai đoạn 1

    d = state.to_dict()
    assert d["emergency_triggered"] is True
    assert d["amount_remaining"] == 0.05

    restored = _OrderState.from_dict(d)
    assert restored.emergency_triggered is True
    assert restored.amount_remaining == 0.05
    print(f"  ✅ to_dict: emergency_triggered={d['emergency_triggered']}, amount_remaining={d['amount_remaining']}")
    print(f"  ✅ from_dict: emergency_triggered={restored.emergency_triggered}, amount_remaining={restored.amount_remaining}")
    print("  → PASS")


# ── Test 5: PnL accuracy — amount_remaining chính xác sau Giai đoạn 1 ────────

async def test_pnl_accuracy() -> None:
    print("\n" + "="*60)
    print("TEST 5: PnL Accuracy — amount_remaining chính xác cho Giai đoạn 2")
    print("="*60)

    strategy    = _make_strategy()
    calibration = _make_calibration()
    shield      = _make_shield()

    # Test với amount không tròn để kiểm tra precision
    order_state = _make_order_state(amount=0.073)
    snap        = _make_snap(adx=15.0)

    strategy._check_emergency_exit("BTC/USDT", snap, order_state, calibration, shield)

    expected_remaining = 0.073 * 0.5  # = 0.0365
    assert abs(order_state.amount_remaining - expected_remaining) < 1e-10, (
        f"amount_remaining phải = {expected_remaining}, got {order_state.amount_remaining}"
    )
    print(f"  ✅ amount_total    = 0.073")
    print(f"  ✅ emergency_close = 50% → đóng {0.073 * 0.5:.4f}")
    print(f"  ✅ amount_remaining = {order_state.amount_remaining:.4f} (chính xác cho Giai đoạn 2)")
    print("  → PASS")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n🧪 ADTS Emergency Exit 2 Giai Đoạn — Test Suite")
    print("=" * 60)

    await test_phase1_then_phase2()
    await test_phase1_then_recovery()
    await test_backward_compat_from_dict()
    await test_roundtrip_with_emergency_triggered()
    await test_pnl_accuracy()

    print("\n" + "="*60)
    print("✅ Tất cả 5 tests PASSED")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
