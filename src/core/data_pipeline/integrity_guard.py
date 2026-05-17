from datetime import datetime, timezone, timedelta

from src.core.data_pipeline.schemas import (
    Candle1m, 
    ResampledCandle, 
    AdapterConfig, 
    IntegrityCheckResult, 
    IntegrityStatus, 
    HealGapEvent
)

class DataIntegrityGuard:
    """Chốt chặn kiểm dịch dữ liệu trước khi nến được đẩy vào hệ thống chiến lược (Strategy).
    
    Đảm bảo dữ liệu không bị khuyết (Gap), đủ số lượng warmup, và không chứa
    bất thường gây flash-crash (Outlier). Áp dụng mô hình Fail-Fast.
    """

    def validate(
        self, 
        candles_1m: list[Candle1m], 
        resampled_candles: list[ResampledCandle], 
        strategy_config: dict, 
        adapter_config: AdapterConfig
    ) -> IntegrityCheckResult:
        """Hàm điều phối chính kiểm tra tính toàn vẹn của dữ liệu theo luồng Fail-Fast.

        Thực thi tuần tự 3 chốt chặn: Gap -> Warmup -> Outlier.

        Args:
            candles_1m (list[Candle1m]): Dữ liệu nến 1m nguyên tử (dùng để check gap).
            resampled_candles (list[ResampledCandle]): Dữ liệu nến đã gộp (dùng để check warmup/outlier).
            strategy_config (dict): Cấu hình chiến lược chứa 'min_candles_required'.
            adapter_config (AdapterConfig): Cấu hình adapter chứa ngưỡng 'outlier_threshold'.

        Returns:
            IntegrityCheckResult: Kết quả kiểm định, chứa HealGapEvent nếu phát hiện Gap.
        """
        symbol = candles_1m[0].symbol if candles_1m else "UNKNOWN"
        checked_at = datetime.now(timezone.utc)

        # 0. Kiểm tra tập dữ liệu rỗng
        if not candles_1m or not resampled_candles:
            return IntegrityCheckResult(
                is_valid=False,
                status=IntegrityStatus.BLOCK_WARMUP,
                reason="Tập dữ liệu đầu vào rỗng.",
                symbol=symbol,
                checked_at=checked_at
            )

        # 1. Phòng tuyến 1: Kiểm tra Gap trên nến nguyên tử 1m
        gap_event = self._check_gap(candles_1m)
        if gap_event:
            return IntegrityCheckResult(
                is_valid=False,
                status=IntegrityStatus.BLOCK_GAP,
                reason="Phát hiện đứt gãy dữ liệu (Missing Candles).",
                symbol=symbol,
                checked_at=checked_at,
                heal_event=gap_event
            )

        # 2. Phòng tuyến 2: Check Warmup
        warmup_error = self._check_warmup(resampled_candles, strategy_config)
        if warmup_error:
            return IntegrityCheckResult(
                is_valid=False,
                status=IntegrityStatus.BLOCK_WARMUP,
                reason=warmup_error,
                symbol=symbol,
                checked_at=checked_at
            )

        # 3. Phòng tuyến 3: Check Outlier
        outlier_error = self._check_outlier(resampled_candles, adapter_config)
        if outlier_error:
            return IntegrityCheckResult(
                is_valid=False,
                status=IntegrityStatus.BLOCK_OUTLIER,
                reason=outlier_error,
                symbol=symbol,
                checked_at=checked_at
            )

        return IntegrityCheckResult(
            is_valid=True,
            status=IntegrityStatus.PASS,
            symbol=symbol,
            checked_at=checked_at
        )

    def _check_gap(self, candles_1m: list[Candle1m]) -> HealGapEvent | None:
        """Quét mảng nến 1m để phát hiện khoảng trống thời gian bất thường.

        Args:
            candles_1m (list[Candle1m]): Danh sách nến 1m nguyên tử.

        Returns:
            HealGapEvent | None: Sự kiện tự chữa lành chứa gap_start và gap_end nếu phát hiện Gap.
        """
        sorted_candles = sorted(candles_1m, key=lambda c: c.open_time)
        for i in range(1, len(sorted_candles)):
            current = sorted_candles[i]
            previous = sorted_candles[i-1]
            
            delta = abs((current.open_time - previous.open_time).total_seconds())
            if delta > 90:
                return HealGapEvent(
                    symbol=current.symbol,
                    gap_start=previous.open_time + timedelta(minutes=1),
                    gap_end=current.open_time - timedelta(minutes=1),
                    attempt_no=1
                )
        return None

    def _check_warmup(self, resampled_candles: list[ResampledCandle], strategy_config: dict) -> str | None:
        """Kiểm định số lượng nến để đảm bảo Strategy có đủ lịch sử khởi tạo Indicator.

        Args:
            resampled_candles (list[ResampledCandle]): Danh sách nến đã gộp.
            strategy_config (dict): Cấu hình chứa 'min_candles_required'.

        Returns:
            str | None: Chuỗi lý do lỗi nếu vi phạm, None nếu an toàn.
        """
        min_required = strategy_config.get("min_candles_required", 200)
        available = len(resampled_candles)
        if available < min_required:
            symbol = resampled_candles[0].symbol
            return f"[INTEGRITY:WARMUP] symbol={symbol} available={available} required={min_required}"
        return None

    def _check_outlier(self, resampled_candles: list[ResampledCandle], adapter_config: AdapterConfig) -> str | None:
        """Kiểm định biến động nến cuối cùng để phát hiện Flash Crash hoặc nhiễu.

        Args:
            resampled_candles (list[ResampledCandle]): Danh sách nến đã gộp.
            adapter_config (AdapterConfig): Cấu hình chứa ngưỡng 'outlier_threshold'.

        Returns:
            str | None: Chuỗi lý do lỗi nếu vi phạm, None nếu an toàn.
        """
        candle = resampled_candles[-1]
        threshold = adapter_config.outlier_threshold
        
        body_volatility = abs(candle.close - candle.open) / candle.open
        if body_volatility > threshold:
            return f"[INTEGRITY:OUTLIER] Body volatility {body_volatility:.2%} exceeds threshold {threshold:.2%}"
            
        wick_volatility = (candle.high / candle.low) - 1
        if wick_volatility > threshold * 2:
            return f"[INTEGRITY:OUTLIER] Wick volatility {wick_volatility:.2%} exceeds threshold {threshold * 2:.2%}"
            
        return None
