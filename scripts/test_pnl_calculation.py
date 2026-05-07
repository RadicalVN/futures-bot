"""
test_pnl_calculation.py — Unit test cho _calculate_realized_pnl.

Chay: venv\\Scripts\\python.exe scripts/test_pnl_calculation.py
"""
import sys
sys.path.insert(0, ".")

from src.apps.monitoring.exit_monitor_service import _calculate_realized_pnl, PnlResult

FEE_RATE = 0.0005  # 0.05% taker


# ── Mock Trade ────────────────────────────────────────────────────────────────

class MockTrade:
    """Minimal mock của Trade ORM để test không cần DB."""
    def __init__(self, trade_id: int, price: float, amount: float, signal_type: str):
        self.id          = trade_id
        self.price       = price
        self.amount      = amount
        self.signal_type = signal_type
        self.symbol      = "BTCUSDT"


# ── Test cases ────────────────────────────────────────────────────────────────

def test_tier1_long_win():
    """Tầng 1: Exchange trả về realizedPnl + commission — LONG thắng."""
    trade = MockTrade(1, price=90_000.0, amount=0.01, signal_type="long")
    order = {
        "average": 95_000.0,
        "info": {
            "realizedPnl": "50.0",    # gross = (95000-90000)*0.01 = 50
            "commission":  "-4.725",  # fee_exit = 95000*0.01*0.0005 = 0.475 (exchange dùng số khác)
        },
    }
    result = _calculate_realized_pnl(order, trade, current_price=95_000.0, fee_rate=FEE_RATE)

    assert result.source == "exchange", f"Expected 'exchange', got {result.source!r}"
    assert result.gross_pnl == 50.0,    f"gross_pnl: {result.gross_pnl}"
    assert result.close_price == 95_000.0

    # fee_entry = 90000 * 0.01 * 0.0005 = 0.45
    expected_fee_entry = round(90_000.0 * 0.01 * FEE_RATE, 6)
    assert abs(result.fee_entry - expected_fee_entry) < 1e-6, \
        f"fee_entry: {result.fee_entry} vs expected {expected_fee_entry}"

    # fee_exit = 4.725 (từ exchange commission)
    assert result.fee_exit == 4.725, f"fee_exit: {result.fee_exit}"

    # net_pnl = 50 - 0.45 - 4.725 = 44.825
    expected_net = round(50.0 - expected_fee_entry - 4.725, 6)
    assert abs(result.net_pnl - expected_net) < 1e-6, \
        f"net_pnl: {result.net_pnl} vs expected {expected_net}"

    print(f"[OK] Tier1 LONG WIN  | Gross={result.gross_pnl:+.4f} | "
          f"Fee(e+x)={result.fee_entry:.4f}+{result.fee_exit:.4f}={result.total_fee:.4f} | "
          f"Net={result.net_pnl:+.4f} | [{result.source}]")


def test_tier1_short_loss():
    """Tầng 1: Exchange trả về realizedPnl âm — SHORT thua."""
    trade = MockTrade(2, price=90_000.0, amount=0.01, signal_type="short")
    order = {
        "average": 92_000.0,
        "info": {
            "realizedPnl": "-20.0",   # gross = (90000-92000)*0.01 = -20
            "commission":  "-0.46",
        },
    }
    result = _calculate_realized_pnl(order, trade, current_price=92_000.0, fee_rate=FEE_RATE)

    assert result.source == "exchange"
    assert result.gross_pnl == -20.0
    assert result.net_pnl < result.gross_pnl, "net_pnl phai nho hon gross_pnl (da tru phi)"

    print(f"[OK] Tier1 SHORT LOSS| Gross={result.gross_pnl:+.4f} | "
          f"Fee(e+x)={result.fee_entry:.4f}+{result.fee_exit:.4f}={result.total_fee:.4f} | "
          f"Net={result.net_pnl:+.4f} | [{result.source}]")


def test_tier2_manual_long():
    """Tầng 2: Exchange trả về realizedPnl=0 → tính thủ công — LONG."""
    trade = MockTrade(3, price=80_000.0, amount=0.1, signal_type="long")
    order = {
        "average": 85_000.0,
        "info": {"realizedPnl": "0", "commission": "0"},
    }
    result = _calculate_realized_pnl(order, trade, current_price=85_000.0, fee_rate=FEE_RATE)

    assert result.source == "manual", f"Expected 'manual', got {result.source!r}"

    # gross = (85000 - 80000) * 0.1 = 500
    assert abs(result.gross_pnl - 500.0) < 1e-4, f"gross_pnl: {result.gross_pnl}"

    # fee_entry = 80000 * 0.1 * 0.0005 = 4.0
    assert abs(result.fee_entry - 4.0) < 1e-6, f"fee_entry: {result.fee_entry}"

    # fee_exit = 85000 * 0.1 * 0.0005 = 4.25
    assert abs(result.fee_exit - 4.25) < 1e-6, f"fee_exit: {result.fee_exit}"

    # total_fee = 4.0 + 4.25 = 8.25
    assert abs(result.total_fee - 8.25) < 1e-6, f"total_fee: {result.total_fee}"

    # net_pnl = 500 - 8.25 = 491.75
    assert abs(result.net_pnl - 491.75) < 1e-4, f"net_pnl: {result.net_pnl}"

    print(f"[OK] Tier2 LONG WIN  | Gross={result.gross_pnl:+.4f} | "
          f"Fee(e+x)={result.fee_entry:.4f}+{result.fee_exit:.4f}={result.total_fee:.4f} | "
          f"Net={result.net_pnl:+.4f} | [{result.source}]")


def test_tier2_manual_short():
    """Tầng 2: Exchange trả về realizedPnl=None → tính thủ công — SHORT."""
    trade = MockTrade(4, price=100_000.0, amount=0.05, signal_type="short")
    order = {
        "average": 95_000.0,
        "info": {},  # không có realizedPnl
    }
    result = _calculate_realized_pnl(order, trade, current_price=95_000.0, fee_rate=FEE_RATE)

    assert result.source == "manual"

    # gross = (100000 - 95000) * 0.05 = 250
    assert abs(result.gross_pnl - 250.0) < 1e-4, f"gross_pnl: {result.gross_pnl}"

    # fee_entry = 100000 * 0.05 * 0.0005 = 2.5
    assert abs(result.fee_entry - 2.5) < 1e-6, f"fee_entry: {result.fee_entry}"

    # fee_exit = 95000 * 0.05 * 0.0005 = 2.375
    assert abs(result.fee_exit - 2.375) < 1e-6, f"fee_exit: {result.fee_exit}"

    # net_pnl = 250 - 2.5 - 2.375 = 245.125
    assert abs(result.net_pnl - 245.125) < 1e-4, f"net_pnl: {result.net_pnl}"

    print(f"[OK] Tier2 SHORT WIN | Gross={result.gross_pnl:+.4f} | "
          f"Fee(e+x)={result.fee_entry:.4f}+{result.fee_exit:.4f}={result.total_fee:.4f} | "
          f"Net={result.net_pnl:+.4f} | [{result.source}]")


def test_tier2_breakeven():
    """Tầng 2: Giá không đổi → gross=0, net âm do phí."""
    trade = MockTrade(5, price=50_000.0, amount=0.2, signal_type="long")
    order = {"average": 50_000.0, "info": {}}
    result = _calculate_realized_pnl(order, trade, current_price=50_000.0, fee_rate=FEE_RATE)

    assert result.source == "manual"
    assert result.gross_pnl == 0.0, f"gross_pnl: {result.gross_pnl}"
    assert result.net_pnl < 0, "net_pnl phai am khi hoa von (van phai tra phi)"

    # total_fee = (50000 + 50000) * 0.2 * 0.0005 = 10.0
    assert abs(result.total_fee - 10.0) < 1e-4, f"total_fee: {result.total_fee}"

    print(f"[OK] Tier2 BREAKEVEN | Gross={result.gross_pnl:+.4f} | "
          f"Fee(e+x)={result.fee_entry:.4f}+{result.fee_exit:.4f}={result.total_fee:.4f} | "
          f"Net={result.net_pnl:+.4f} | [{result.source}]")


def test_tier3_fallback():
    """Tầng 3: Thiếu dữ liệu → fallback PnL=0."""
    trade = MockTrade(6, price=0.0, amount=0.0, signal_type="long")
    order = {"average": None, "info": {}}
    result = _calculate_realized_pnl(order, trade, current_price=0.0, fee_rate=FEE_RATE)

    assert result.source == "fallback", f"Expected 'fallback', got {result.source!r}"
    assert result.net_pnl == 0.0
    assert result.total_fee == 0.0

    print(f"[OK] Tier3 FALLBACK  | Net={result.net_pnl:+.4f} | [{result.source}]")


def test_custom_fee_rate():
    """Fee rate tùy chỉnh từ Bot.parameters (VIP account 0.02%)."""
    vip_fee_rate = 0.0002
    trade = MockTrade(7, price=60_000.0, amount=1.0, signal_type="long")
    order = {"average": 61_000.0, "info": {}}
    result = _calculate_realized_pnl(order, trade, current_price=61_000.0, fee_rate=vip_fee_rate)

    # fee_entry = 60000 * 1.0 * 0.0002 = 12.0
    # fee_exit  = 61000 * 1.0 * 0.0002 = 12.2
    # gross     = (61000 - 60000) * 1.0 = 1000
    # net       = 1000 - 12.0 - 12.2 = 975.8
    assert abs(result.fee_entry - 12.0) < 1e-6, f"fee_entry: {result.fee_entry}"
    assert abs(result.fee_exit  - 12.2) < 1e-6, f"fee_exit: {result.fee_exit}"
    assert abs(result.net_pnl   - 975.8) < 1e-4, f"net_pnl: {result.net_pnl}"

    print(f"[OK] Custom fee 0.02%| Gross={result.gross_pnl:+.4f} | "
          f"Fee(e+x)={result.fee_entry:.4f}+{result.fee_exit:.4f}={result.total_fee:.4f} | "
          f"Net={result.net_pnl:+.4f} | [{result.source}]")


def test_pnl_result_is_dataclass():
    """PnlResult là dataclass với đủ fields."""
    import dataclasses
    assert dataclasses.is_dataclass(PnlResult), "PnlResult phai la dataclass"
    fields = {f.name for f in dataclasses.fields(PnlResult)}
    required = {"gross_pnl", "fee_entry", "fee_exit", "total_fee", "net_pnl", "source", "close_price"}
    assert required.issubset(fields), f"Thieu fields: {required - fields}"
    print(f"[OK] PnlResult dataclass fields: {sorted(fields)}")


if __name__ == "__main__":
    print("=" * 60)
    print("  _calculate_realized_pnl — Unit Tests")
    print("=" * 60)
    print(f"  Fee rate default: {FEE_RATE} ({FEE_RATE*100:.3f}%)")
    print()

    try:
        test_pnl_result_is_dataclass()
        test_tier1_long_win()
        test_tier1_short_loss()
        test_tier2_manual_long()
        test_tier2_manual_short()
        test_tier2_breakeven()
        test_tier3_fallback()
        test_custom_fee_rate()

        print()
        print("=" * 60)
        print("  TAT CA 8 KIEM TRA PASS")
        print("=" * 60)
        sys.exit(0)

    except AssertionError as e:
        print(f"\n[FAIL] Assertion: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"\n[FAIL] Unexpected: {e}")
        traceback.print_exc()
        sys.exit(1)
