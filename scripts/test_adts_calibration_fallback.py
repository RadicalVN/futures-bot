"""
test_adts_calibration_fallback.py — Kiểm thử nhanh cơ chế 3 tầng Fallback của ADTS Calibration.

Chạy: venv\Scripts\python.exe scripts/test_adts_calibration_fallback.py
"""
import asyncio
import sys
from datetime import datetime, timedelta

# ── Setup path ────────────────────────────────────────────────────────────────
sys.path.insert(0, ".")

from src.strategies.adts_strategy import ADTSStrategy, _CalibrationResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_strategy() -> ADTSStrategy:
    """Tạo ADTSStrategy với config mặc định."""
    return ADTSStrategy({})


def _make_minimal_ohlcv(n: int = 10) -> list:
    """Tạo dữ liệu OHLCV tối thiểu (quá ít để calibrate thành công)."""
    base_ts = int(datetime(2026, 5, 1).timestamp() * 1000)
    return [
        [base_ts + i * 300_000, 95000.0, 95100.0, 94900.0, 95050.0, 100.0]
        for i in range(n)
    ]


# ── Test cases ────────────────────────────────────────────────────────────────

async def test_tầng_3_hardcoded_default() -> None:
    """Tầng 3: Không có calibration cũ + dữ liệu quá ít → hardcoded default."""
    print("\n" + "="*60)
    print("TEST 1: Tầng 3 — Hardcoded Default")
    print("="*60)

    strategy = _make_strategy()
    assert strategy._calibration is None, "Ban đầu phải là None"

    # Dữ liệu quá ít (10 nến) → không thể resample D1 đủ
    tiny_ohlcv = _make_minimal_ohlcv(10)
    result = await strategy._ensure_calibration(tiny_ohlcv, "BTC/USDT")

    assert result is not None, "Phải trả về _CalibrationResult, không phải None"
    assert result.is_hardcoded_default, "Phải là hardcoded default (d1_candles_used=0)"
    assert result.d1_candles_used == 0
    assert result.sideway_threshold == 0.0
    assert result.min_slope == 1e-9
    assert result.base_atr == 0.0
    assert not result.is_stale, "Hardcoded default vừa tạo không được stale ngay"

    print(f"  ✅ is_hardcoded_default = {result.is_hardcoded_default}")
    print(f"  ✅ d1_candles_used      = {result.d1_candles_used}")
    print(f"  ✅ sideway_threshold    = {result.sideway_threshold}")
    print(f"  ✅ min_slope            = {result.min_slope}")
    print(f"  ✅ base_atr             = {result.base_atr}")
    print(f"  ✅ is_stale             = {result.is_stale}")
    print("  → PASS")


async def test_tầng_2_stale_fallback() -> None:
    """Tầng 2: Có calibration cũ (stale) + dữ liệu mới quá ít → dùng calibration cũ."""
    print("\n" + "="*60)
    print("TEST 2: Tầng 2 — Stale Fallback")
    print("="*60)

    strategy = _make_strategy()

    # Inject calibration cũ (30 giờ trước → stale)
    old_calibration = _CalibrationResult(
        calibrated_at=datetime.utcnow() - timedelta(hours=30),
        base_atr=1500.0,
        sideway_threshold=0.045,
        min_slope=0.000012,
        d1_candles_used=220,
    )
    strategy._calibration = old_calibration
    assert old_calibration.is_stale, "Calibration cũ phải là stale"
    assert not old_calibration.is_hardcoded_default

    # Dữ liệu quá ít → không thể tính calibration mới
    tiny_ohlcv = _make_minimal_ohlcv(10)
    result = await strategy._ensure_calibration(tiny_ohlcv, "BTC/USDT")

    assert result is not None
    assert result is old_calibration, "Phải trả về đúng object calibration cũ"
    assert result.base_atr == 1500.0
    assert result.sideway_threshold == 0.045
    assert result.d1_candles_used == 220
    assert not result.is_hardcoded_default

    print(f"  ✅ Trả về calibration cũ (base_atr={result.base_atr})")
    print(f"  ✅ is_stale             = {result.is_stale}")
    print(f"  ✅ is_hardcoded_default = {result.is_hardcoded_default}")
    print(f"  ✅ age_hours            ≈ {result.age_hours:.1f}h")
    print("  → PASS")


async def test_tầng_1_fresh_calibration() -> None:
    """Tầng 1: Đủ dữ liệu D1 → tính calibration mới thành công.

    Inject trực tiếp vào _run_calibration() với dữ liệu D1 đủ (≥224 nến),
    thay vì resample từ 5m (cần quá nhiều nến).
    """
    print("\n" + "="*60)
    print("TEST 3: Tầng 1 — Fresh Calibration (via _run_calibration)")
    print("="*60)

    strategy = _make_strategy()
    assert strategy._calibration is None

    # Tạo dữ liệu D1 đủ: 250 nến (> 224 = bbwidth_sma_period + atr_period + 10)
    import random
    random.seed(99)
    base_ts = int(datetime(2025, 1, 1).timestamp() * 1000)
    price = 50000.0
    d1_ohlcv = []
    for i in range(250):
        price += random.uniform(-1000, 1000)
        price = max(price, 10000.0)
        d1_ohlcv.append([
            base_ts + i * 86_400_000,  # 1 ngày = 86400s
            price,
            price + random.uniform(0, 2000),
            price - random.uniform(0, 2000),
            price + random.uniform(-500, 500),
            random.uniform(1000, 5000),
        ])

    # Gọi trực tiếp _run_calibration() để kiểm tra Tầng 1
    result = strategy._run_calibration(d1_ohlcv, "BTC/USDT")

    assert result is not None, "_run_calibration phải thành công với 250 nến D1"
    assert not result.is_hardcoded_default, "Phải là calibration thực, không phải hardcoded"
    assert result.d1_candles_used == 250
    assert result.base_atr > 0, "Base ATR phải dương"
    assert result.sideway_threshold > 0, "Sideway threshold phải dương"
    assert result.min_slope > 0, "Min slope phải dương"
    assert not result.is_stale, "Calibration mới không được stale"

    # Verify _ensure_calibration() cũng dùng kết quả này khi inject vào strategy
    strategy._calibration = result
    # Gọi lại với dữ liệu ít → fast path vì calibration còn hiệu lực
    tiny_ohlcv = _make_minimal_ohlcv(5)
    result2 = await strategy._ensure_calibration(tiny_ohlcv, "BTC/USDT")
    assert result2 is result, "Fast path phải trả về calibration đã inject"

    print(f"  ✅ d1_candles_used      = {result.d1_candles_used}")
    print(f"  ✅ base_atr             = {result.base_atr:.4f}")
    print(f"  ✅ sideway_threshold    = {result.sideway_threshold:.6f}")
    print(f"  ✅ min_slope            = {result.min_slope:.8f}")
    print(f"  ✅ is_hardcoded_default = {result.is_hardcoded_default}")
    print(f"  ✅ is_stale             = {result.is_stale}")
    print("  → PASS")


async def test_fast_path_không_tính_lại() -> None:
    """Fast path: calibration còn hiệu lực → không tính lại."""
    print("\n" + "="*60)
    print("TEST 4: Fast Path — Không tính lại khi còn hiệu lực")
    print("="*60)

    strategy = _make_strategy()

    # Inject calibration mới (1 giờ trước → chưa stale)
    fresh_calibration = _CalibrationResult(
        calibrated_at=datetime.utcnow() - timedelta(hours=1),
        base_atr=1200.0,
        sideway_threshold=0.038,
        min_slope=0.000009,
        d1_candles_used=215,
    )
    strategy._calibration = fresh_calibration
    assert not fresh_calibration.is_stale

    # Dù dữ liệu ít, vẫn phải trả về calibration cũ (fast path)
    tiny_ohlcv = _make_minimal_ohlcv(5)
    result = await strategy._ensure_calibration(tiny_ohlcv, "BTC/USDT")

    assert result is fresh_calibration, "Fast path phải trả về đúng object cũ"
    print(f"  ✅ Trả về calibration cũ (fast path, base_atr={result.base_atr})")
    print(f"  ✅ is_stale             = {result.is_stale}")
    print("  → PASS")


async def test_properties_CalibrationResult() -> None:
    """Kiểm tra các property mới của _CalibrationResult."""
    print("\n" + "="*60)
    print("TEST 5: _CalibrationResult properties")
    print("="*60)

    # Hardcoded default
    hc = ADTSStrategy._make_hardcoded_calibration()
    assert hc.is_hardcoded_default
    assert hc.d1_candles_used == 0
    assert hc.sideway_threshold == 0.0
    assert hc.min_slope == 1e-9
    assert not hc.is_stale
    print(f"  ✅ Hardcoded: is_hardcoded_default={hc.is_hardcoded_default}, min_slope={hc.min_slope}")

    # Normal calibration
    normal = _CalibrationResult(
        calibrated_at=datetime.utcnow() - timedelta(hours=2),
        base_atr=1000.0,
        sideway_threshold=0.04,
        min_slope=0.00001,
        d1_candles_used=210,
    )
    assert not normal.is_hardcoded_default
    assert not normal.is_stale
    assert 1.9 < normal.age_hours < 2.1
    print(f"  ✅ Normal: is_hardcoded_default={normal.is_hardcoded_default}, age_hours≈{normal.age_hours:.1f}h")

    # Stale calibration
    stale = _CalibrationResult(
        calibrated_at=datetime.utcnow() - timedelta(hours=30),
        base_atr=900.0,
        sideway_threshold=0.035,
        min_slope=0.000008,
        d1_candles_used=200,
    )
    assert stale.is_stale
    assert not stale.is_hardcoded_default
    print(f"  ✅ Stale: is_stale={stale.is_stale}, age_hours≈{stale.age_hours:.1f}h")
    print("  → PASS")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n🧪 ADTS Calibration Fallback — Test Suite")
    print("=" * 60)

    await test_properties_CalibrationResult()
    await test_tầng_3_hardcoded_default()
    await test_tầng_2_stale_fallback()
    await test_tầng_1_fresh_calibration()
    await test_fast_path_không_tính_lại()

    print("\n" + "="*60)
    print("✅ Tất cả tests PASSED")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
