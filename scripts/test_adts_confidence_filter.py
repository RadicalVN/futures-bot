"""
test_adts_confidence_filter.py — Kiểm thử Confidence Score Filter [ADTS-006].

Mô phỏng 4 trường hợp:
  Case A: ADX=22, threshold=20 → confidence=0.54 → bị chặn (min_confidence=0.6)
  Case B: ADX=30, threshold=20 → confidence=0.70 → được vào lệnh
  Case C: min_confidence=0.5 (tắt filter) → luôn vào lệnh
  Case D: confidence ghi đúng vào metadata và StrategySignal.confidence

Chạy: venv\Scripts\python.exe scripts/test_adts_confidence_filter.py
"""
import asyncio
import sys
from datetime import datetime

sys.path.insert(0, ".")

from src.strategies.adts_strategy import ADTSStrategy, _CalibrationResult, _ShieldState
from src.data.indicators import ADTSSnapshot


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_strategy(min_confidence: float = 0.6, adx_threshold: float = 20.0) -> ADTSStrategy:
    return ADTSStrategy({
        "adx_threshold":   adx_threshold,
        "min_confidence":  min_confidence,
        "sl_atr_mult":     1.5,
        "hard_sl_pct":     0.03,
        "tp1_rr":          1.2,
        "tp1_close_pct":   0.5,
        "tp2_trail_atr_mult": 2.0,
    })


def _make_snap(adx: float, close: float = 95000.0) -> ADTSSnapshot:
    """Tạo snapshot với ADX tùy chỉnh, giá trên EMA20 và EMA200 (điều kiện LONG)."""
    return ADTSSnapshot(
        close=close,
        high=close + 100,
        low=close - 100,
        atr=950.0,
        adx=adx,
        bb_width=0.05,
        ema20=close - 50.0,    # close > ema20 → điều kiện LONG
        ema20_slope=10.0,       # slope > 0 → điều kiện LONG
        ema200=close - 5000.0,  # close > ema200 → điều kiện LONG
        close_prev=close - 20,
        ema20_prev=close - 60,
    )


def _make_calibration() -> _CalibrationResult:
    return _CalibrationResult(
        calibrated_at=datetime.utcnow(),
        base_atr=1000.0,
        sideway_threshold=0.03,
        min_slope=0.00001,
        d1_candles_used=220,
    )


def _make_shield_pass() -> _ShieldState:
    """Shield PASS — tất cả 3 điều kiện đều thỏa."""
    return _ShieldState(
        adx=25.0, bb_width=0.05, ema20_slope=10.0,
        adx_ok=True, bbwidth_ok=True, slope_ok=True,
    )


# ── Test Cases ────────────────────────────────────────────────────────────────

async def test_case_a_blocked() -> None:
    """Case A: ADX=22, threshold=20 → confidence≈0.54 → bị chặn."""
    print("\n" + "="*60)
    print("CASE A: ADX=22, threshold=20 → confidence≈0.54 → BỊ CHẶN")
    print("="*60)

    strategy    = _make_strategy(min_confidence=0.6, adx_threshold=20.0)
    snap        = _make_snap(adx=22.0)
    calibration = _make_calibration()
    shield      = _make_shield_pass()

    # Xác nhận confidence tính đúng
    confidence = strategy._calc_confidence(snap)
    expected   = round(0.5 + min((22.0 - 20.0) / 25.0, 1.0) * 0.5, 2)
    assert abs(confidence - expected) < 1e-9, f"confidence={confidence}, expected={expected}"
    assert confidence < 0.6, f"Confidence {confidence} phải < 0.6"
    print(f"  ✅ _calc_confidence(ADX=22) = {confidence:.2f} (< 0.60)")

    # Gọi _check_entry — phải trả về None
    signal = strategy._check_entry("BTC/USDT", snap, shield, calibration)
    assert signal is None, f"Phải bị chặn (signal=None), got signal={signal}"
    print(f"  ✅ _check_entry() = None (bị chặn đúng)")
    print("  → PASS")


async def test_case_b_allowed() -> None:
    """Case B: ADX=30, threshold=20 → confidence=0.70 → được vào lệnh."""
    print("\n" + "="*60)
    print("CASE B: ADX=30, threshold=20 → confidence=0.70 → ĐƯỢC VÀO LỆNH")
    print("="*60)

    strategy    = _make_strategy(min_confidence=0.6, adx_threshold=20.0)
    snap        = _make_snap(adx=30.0)
    calibration = _make_calibration()
    shield      = _make_shield_pass()

    # Xác nhận confidence tính đúng
    confidence = strategy._calc_confidence(snap)
    expected   = round(0.5 + min((30.0 - 20.0) / 25.0, 1.0) * 0.5, 2)
    assert abs(confidence - expected) < 1e-9, f"confidence={confidence}, expected={expected}"
    assert confidence >= 0.6, f"Confidence {confidence} phải >= 0.6"
    print(f"  ✅ _calc_confidence(ADX=30) = {confidence:.2f} (>= 0.60)")

    # Gọi _check_entry — phải trả về signal
    signal = strategy._check_entry("BTC/USDT", snap, shield, calibration)
    assert signal is not None, "Phải có signal (không bị chặn)"
    assert signal.signal == "long", f"Phải là LONG, got {signal.signal}"
    assert signal.confidence == confidence, (
        f"StrategySignal.confidence={signal.confidence} phải = {confidence}"
    )
    assert signal.metadata.get("confidence") == confidence, (
        f"metadata['confidence']={signal.metadata.get('confidence')} phải = {confidence}"
    )
    print(f"  ✅ _check_entry() = signal.signal='{signal.signal}'")
    print(f"  ✅ StrategySignal.confidence = {signal.confidence:.2f}")
    print(f"  ✅ metadata['confidence']    = {signal.metadata['confidence']:.2f}")
    print("  → PASS")


async def test_case_c_filter_disabled() -> None:
    """Case C: min_confidence=0.5 (tắt filter) → luôn vào lệnh dù ADX thấp."""
    print("\n" + "="*60)
    print("CASE C: min_confidence=0.5 (tắt filter) → LUÔN VÀO LỆNH")
    print("="*60)

    strategy    = _make_strategy(min_confidence=0.5, adx_threshold=20.0)
    snap        = _make_snap(adx=20.1)  # ADX vừa vượt threshold → confidence ≈ 0.50
    calibration = _make_calibration()
    shield      = _make_shield_pass()

    confidence = strategy._calc_confidence(snap)
    print(f"  ✅ _calc_confidence(ADX=20.1) = {confidence:.2f}")

    signal = strategy._check_entry("BTC/USDT", snap, shield, calibration)
    assert signal is not None, "Phải có signal khi min_confidence=0.5"
    print(f"  ✅ _check_entry() = signal.signal='{signal.signal}' (không bị chặn)")
    print("  → PASS")


async def test_case_d_metadata_integrity() -> None:
    """Case D: confidence ghi đúng vào cả StrategySignal.confidence và metadata."""
    print("\n" + "="*60)
    print("CASE D: Metadata integrity — confidence trong signal và metadata khớp nhau")
    print("="*60)

    strategy    = _make_strategy(min_confidence=0.5)  # tắt filter để luôn có signal
    snap        = _make_snap(adx=35.0)
    calibration = _make_calibration()
    shield      = _make_shield_pass()

    signal = strategy._check_entry("BTC/USDT", snap, shield, calibration)
    assert signal is not None

    expected_conf = strategy._calc_confidence(snap)
    assert signal.confidence == expected_conf, (
        f"StrategySignal.confidence={signal.confidence} != expected={expected_conf}"
    )
    assert signal.metadata.get("confidence") == expected_conf, (
        f"metadata['confidence']={signal.metadata.get('confidence')} != expected={expected_conf}"
    )
    # Đảm bảo confidence cũng có trong metadata cùng với các field khác
    assert "entry_price" in signal.metadata
    assert "stop_loss" in signal.metadata
    assert "confidence" in signal.metadata
    print(f"  ✅ StrategySignal.confidence = {signal.confidence:.2f}")
    print(f"  ✅ metadata['confidence']    = {signal.metadata['confidence']:.2f}")
    print(f"  ✅ Các field metadata khác vẫn đầy đủ: entry_price, stop_loss, ...")
    print("  → PASS")


async def test_confidence_formula() -> None:
    """Kiểm tra công thức _calc_confidence với nhiều giá trị ADX."""
    print("\n" + "="*60)
    print("TEST: Công thức _calc_confidence(ADX)")
    print("="*60)

    strategy = _make_strategy(adx_threshold=20.0)
    cases = [
        (20.0, 0.50),   # ADX = threshold → min confidence
        (22.0, 0.54),   # ADX = threshold + 2
        (30.0, 0.70),   # ADX = threshold + 10
        (45.0, 1.00),   # ADX = threshold + 25 → max confidence
        (60.0, 1.00),   # ADX > threshold + 25 → capped at 1.0
    ]
    for adx, expected in cases:
        snap = _make_snap(adx=adx)
        conf = strategy._calc_confidence(snap)
        assert abs(conf - expected) < 0.01, f"ADX={adx}: conf={conf:.2f}, expected={expected:.2f}"
        print(f"  ✅ ADX={adx:5.1f} → confidence={conf:.2f} (expected≈{expected:.2f})")
    print("  → PASS")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n🧪 ADTS Confidence Score Filter [ADTS-006] — Test Suite")
    print("=" * 60)

    await test_confidence_formula()
    await test_case_a_blocked()
    await test_case_b_allowed()
    await test_case_c_filter_disabled()
    await test_case_d_metadata_integrity()

    print("\n" + "="*60)
    print("✅ Tất cả tests PASSED")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
