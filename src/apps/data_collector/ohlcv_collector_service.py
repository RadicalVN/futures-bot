"""
ohlcv_collector_service.py — App thu thập dữ liệu nến OHLCV định kỳ.

Chạy mỗi 60 giây, quét song song tất cả (strategy, symbol, timeframe)
mà các Bot đang yêu cầu, fetch nến mới từ Binance và upsert vào DB.

Thiết kế:
    - Tái sử dụng ``src.data.ohlcv_service.incremental_update()`` — không
      viết lại logic upsert hay pagination.
    - ``asyncio.gather`` với ``return_exceptions=True``: 1 symbol lỗi
      không làm sập cả vòng quét.
    - Lọc dataset theo lag: chỉ update khi data đã cũ hơn nửa timeframe,
      tránh gọi API thừa cho nến 1h/4h/1d.
    - Exchange dùng public endpoint (không cần API key) — OHLCV là public data.
    - Redis Lock do BaseScheduler xử lý — không implement thêm ở đây.

Luồng xử lý mỗi vòng quét (run_once):
    1. Query DB → lấy danh sách active datasets (strategy, symbol, tf)
    2. Tạo exchange public connection (1 lần, dùng chung)
    3. Lọc dataset cần update theo lag threshold
    4. asyncio.gather song song tất cả dataset
    5. Log tổng kết: OK / lỗi / nến mới
    6. Đóng exchange connection
"""
import asyncio
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from src.core.scheduler import JobConfig, SchedulerRegistry
from src.data.ohlcv_service import (
    get_active_datasets,
    get_data_range,
    incremental_update,
)

# ── Hằng số cấu hình ─────────────────────────────────────────────────────────

_SCAN_INTERVAL_SECONDS: int = 60
"""Tần suất quét (giây). Đủ cho nến 1m và 5m."""

_LOCK_TTL_SECONDS: int = 55
"""TTL Redis lock — nhỏ hơn interval để tránh overlap."""

_JOB_ID: str = "ohlcv_data_collector"
"""ID duy nhất của job trong SchedulerRegistry."""

_LAG_RATIO: float = 0.5
"""Chỉ update dataset khi lag > timeframe * _LAG_RATIO.
Ví dụ: tf=1h (3600s) → chỉ update khi lag > 1800s.
Tránh gọi API thừa cho nến dài."""

_MAX_CONCURRENT_FETCHES: int = 10
"""Số lượng dataset được fetch đồng thời tối đa.
Giới hạn bằng asyncio.Semaphore để tránh bị Binance rate-limit
khi có nhiều cặp tiền (vd: 100+ symbols).
Giá trị 10 = cân bằng giữa tốc độ và an toàn với public endpoint."""

# Mapping timeframe string → số giây
_TF_SECONDS: dict[str, int] = {
    "1m":  60,
    "3m":  180,
    "5m":  300,
    "15m": 900,
    "30m": 1800,
    "1h":  3600,
    "2h":  7200,
    "4h":  14400,
    "6h":  21600,
    "8h":  28800,
    "12h": 43200,
    "1d":  86400,
    "3d":  259200,
    "1w":  604800,
}


# ── Dataset key ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DatasetKey:
    """Định danh duy nhất cho một dataset OHLCV.

    Attributes:
        strategy_name: Tên chiến lược (vd: "sma_macd_cross").
        symbol: Symbol dạng BTCUSDT (không có dấu /).
        timeframe: Timeframe (vd: "5m", "1h").
    """
    strategy_name: str
    symbol:        str
    timeframe:     str


# ── Lag filter ────────────────────────────────────────────────────────────────

def _tf_to_seconds(timeframe: str) -> int:
    """Chuyển timeframe string sang số giây.

    Args:
        timeframe: Chuỗi timeframe (vd: "5m", "1h", "1d").

    Returns:
        Số giây tương ứng. Fallback về 300 (5m) nếu không nhận ra.
    """
    return _TF_SECONDS.get(timeframe, 300)


def _needs_update(lag_hours: Optional[float], timeframe: str) -> bool:
    """Kiểm tra dataset có cần update không dựa trên lag hiện tại.

    Chỉ update khi lag > timeframe * _LAG_RATIO để tránh gọi API thừa.
    Dataset chưa có data (lag_hours=None) luôn cần update.

    Args:
        lag_hours: Số giờ kể từ nến cuối cùng. None nếu chưa có data.
        timeframe: Timeframe của dataset.

    Returns:
        True nếu cần update, False nếu data còn mới.
    """
    if lag_hours is None:
        return True  # Chưa có data → luôn cần fetch

    tf_seconds   = _tf_to_seconds(timeframe)
    lag_seconds  = lag_hours * 3600
    threshold    = tf_seconds * _LAG_RATIO
    return lag_seconds > threshold


# ── Per-dataset update ────────────────────────────────────────────────────────

async def _update_one_dataset(
    dataset: DatasetKey,
    exchange,
) -> dict:
    """Thực hiện incremental update cho 1 dataset.

    Wrapper mỏng quanh ``ohlcv_service.incremental_update()``.
    Bắt exception và trả về dict kết quả thay vì raise — để
    ``asyncio.gather`` với ``return_exceptions=True`` xử lý đúng.

    Args:
        dataset: DatasetKey xác định dataset cần update.
        exchange: BinanceExchange instance đã connect (dùng chung).

    Returns:
        Dict kết quả: {"status", "total_inserted", "strategy_name",
        "symbol", "timeframe"}.
    """
    try:
        result = await incremental_update(
            strategy_name=dataset.strategy_name,
            symbol=dataset.symbol,
            timeframe=dataset.timeframe,
            exchange=exchange,
        )
        inserted = result.get("total_inserted", 0)
        status   = result.get("status", "done")

        if inserted > 0:
            logger.info(
                f"[DataCollector] {dataset.strategy_name}/{dataset.symbol}"
                f"/{dataset.timeframe}: +{inserted} nen moi ({status})"
            )
        else:
            logger.debug(
                f"[DataCollector] {dataset.strategy_name}/{dataset.symbol}"
                f"/{dataset.timeframe}: up-to-date"
            )

        return {
            "strategy_name": dataset.strategy_name,
            "symbol":        dataset.symbol,
            "timeframe":     dataset.timeframe,
            "status":        status,
            "total_inserted": inserted,
        }

    except Exception as exc:
        logger.error(
            f"[DataCollector] LOI {dataset.strategy_name}/{dataset.symbol}"
            f"/{dataset.timeframe}: {type(exc).__name__}: {exc}"
        )
        raise  # Re-raise để gather ghi nhận là Exception


# ── Dataset loader ────────────────────────────────────────────────────────────

async def _load_datasets_needing_update() -> list[DatasetKey]:
    """Query DB để lấy danh sách dataset cần update trong vòng quét này.

    Bước 1: Lấy tất cả active datasets từ Bot DB.
    Bước 2: Kiểm tra lag của từng dataset.
    Bước 3: Lọc chỉ giữ dataset có lag > threshold.

    Returns:
        Danh sách DatasetKey cần fetch trong vòng quét này.
    """
    try:
        raw_datasets = await get_active_datasets()
    except Exception as exc:
        logger.error(f"[DataCollector] Khong the load active datasets: {exc}")
        return []

    if not raw_datasets:
        logger.debug("[DataCollector] Khong co dataset nao can theo doi.")
        return []

    # Kiểm tra lag song song cho tất cả dataset
    lag_tasks = [
        get_data_range(
            strategy_name=ds["strategy_name"],
            symbol=ds["symbol"],
            timeframe=ds["timeframe"],
        )
        for ds in raw_datasets
    ]
    lag_results = await asyncio.gather(*lag_tasks, return_exceptions=True)

    datasets_to_update: list[DatasetKey] = []
    for ds, lag_result in zip(raw_datasets, lag_results):
        if isinstance(lag_result, Exception):
            # Lỗi khi check lag → vẫn update để an toàn
            logger.warning(
                f"[DataCollector] Khong check duoc lag "
                f"{ds['strategy_name']}/{ds['symbol']}/{ds['timeframe']}: "
                f"{lag_result} — van update"
            )
            datasets_to_update.append(DatasetKey(
                strategy_name=ds["strategy_name"],
                symbol=ds["symbol"],
                timeframe=ds["timeframe"],
            ))
            continue

        lag_hours = lag_result.get("lag_hours")
        if _needs_update(lag_hours, ds["timeframe"]):
            datasets_to_update.append(DatasetKey(
                strategy_name=ds["strategy_name"],
                symbol=ds["symbol"],
                timeframe=ds["timeframe"],
            ))

    return datasets_to_update


# ── Exchange factory ──────────────────────────────────────────────────────────

async def _create_public_exchange():
    """Tạo exchange connection dùng public endpoint (không cần API key).

    OHLCV là public data — không cần authenticate.
    Dùng ``create_exchange_from_env()`` để lấy mode/endpoint config,
    nhưng exchange chỉ gọi public endpoints (fetch_ohlcv).

    Returns:
        BinanceExchange instance đã connect.

    Raises:
        Exception: Nếu không thể kết nối exchange.
    """
    from src.core.exchange import create_exchange_from_env
    exchange = create_exchange_from_env()
    await exchange.connect()
    return exchange


# ── Result summarizer ─────────────────────────────────────────────────────────

def _summarize_results(
    datasets:  list[DatasetKey],
    results:   list,
) -> tuple[int, int, int]:
    """Tổng hợp kết quả từ asyncio.gather và log tổng kết.

    Args:
        datasets: Danh sách dataset đã được xử lý.
        results: Kết quả từ gather (có thể là dict hoặc Exception).

    Returns:
        Tuple (ok_count, error_count, total_inserted).
    """
    ok_count       = 0
    error_count    = 0
    total_inserted = 0

    for dataset, result in zip(datasets, results):
        if isinstance(result, Exception):
            error_count += 1
            logger.error(
                f"[DataCollector] gather exception "
                f"{dataset.strategy_name}/{dataset.symbol}/{dataset.timeframe}: "
                f"{type(result).__name__}: {result}"
            )
        else:
            ok_count       += 1
            total_inserted += result.get("total_inserted", 0)

    return ok_count, error_count, total_inserted


# ── Main service class ────────────────────────────────────────────────────────

class OHLCVCollectorService:
    """Service thu thập dữ liệu nến OHLCV định kỳ — cross-strategy, cross-symbol.

    Được đăng ký vào SchedulerRegistry qua ``setup_data_collector_job()``.
    Mỗi vòng quét (run_once):
        1. Load active datasets từ Bot DB.
        2. Lọc dataset cần update theo lag threshold.
        3. Tạo exchange public connection.
        4. asyncio.gather song song tất cả dataset.
        5. Log tổng kết và đóng exchange.

    Redis Lock được xử lý bởi BaseScheduler — không implement thêm ở đây.
    """

    async def run_once(self) -> None:
        """Thực thi 1 vòng thu thập OHLCV cho tất cả active datasets.

        Được gọi bởi BaseScheduler mỗi 60 giây.
        Mọi exception đều được bắt và log — không để crash scheduler.
        """
        exchange = None
        try:
            await self._execute_collection_cycle()
        except Exception as exc:
            logger.error(
                f"[DataCollector] LOI vong quet: "
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            )

    async def _execute_collection_cycle(self) -> None:
        """Thực thi toàn bộ chu kỳ thu thập — tách ra để dễ test.

        Raises:
            Exception: Nếu không thể tạo exchange connection.
        """
        # Bước 1: Load datasets cần update
        datasets = await _load_datasets_needing_update()
        if not datasets:
            logger.debug("[DataCollector] Khong co dataset nao can update.")
            return

        logger.info(
            f"[DataCollector] Bat dau quet song song "
            f"{len(datasets)} dataset..."
        )

        # Bước 2: Tạo exchange (1 lần, dùng chung cho tất cả dataset)
        exchange = None
        try:
            exchange = await _create_public_exchange()
        except Exception as exc:
            logger.error(
                f"[DataCollector] Khong the ket noi exchange: "
                f"{type(exc).__name__}: {exc}"
            )
            return

        # Bước 3: Fetch song song tất cả dataset — có giới hạn concurrency
        try:
            # Semaphore giới hạn tối đa _MAX_CONCURRENT_FETCHES request đồng thời.
            # Với 100 symbols: chỉ 10 request chạy cùng lúc, 90 còn lại chờ slot.
            # Khi 1 slot giải phóng → request tiếp theo được phép chạy ngay (gối đầu).
            # Điều này tránh bị Binance đánh dấu spam trên public endpoint.
            semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)

            async def _guarded_update(dataset: DatasetKey) -> dict:
                """Wrapper bọc _update_one_dataset bằng semaphore.

                Acquire semaphore trước khi gọi API, release ngay sau khi xong.
                Đảm bảo tối đa _MAX_CONCURRENT_FETCHES request chạy đồng thời.

                Args:
                    dataset: DatasetKey cần update.

                Returns:
                    Kết quả từ _update_one_dataset.
                """
                async with semaphore:
                    return await _update_one_dataset(dataset, exchange)

            tasks = [_guarded_update(dataset) for dataset in datasets]
            # return_exceptions=True: 1 dataset lỗi không làm sập cả vòng quét
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Bước 4: Tổng kết
            ok_count, error_count, total_inserted = _summarize_results(
                datasets, results
            )
            logger.info(
                f"[DataCollector] Hoan tat: "
                f"{ok_count} OK | {error_count} loi | "
                f"+{total_inserted} nen moi"
            )

        finally:
            # Luôn đóng exchange dù có lỗi
            if exchange:
                try:
                    await exchange.close()
                except Exception as exc:
                    logger.debug(
                        f"[DataCollector] Loi dong exchange: {exc}"
                    )


# ── Job registration ──────────────────────────────────────────────────────────

def setup_data_collector_job(scheduler=None) -> None:
    """Đăng ký OHLCVCollectorService job vào SchedulerRegistry.

    Tạo 1 instance OHLCVCollectorService và đăng ký vào scheduler với:
    - Interval: 60 giây
    - Redis Lock TTL: 55 giây (< interval để tránh overlap)
    - Job ID: "ohlcv_data_collector"

    Nên được gọi trong ``main.py`` TRƯỚC khi ``scheduler.start()``.

    Args:
        scheduler: BaseScheduler instance. Nếu None, lấy từ SchedulerRegistry.get().

    Example:
        # main.py
        from src.apps.data_collector import setup_data_collector_job
        setup_data_collector_job(scheduler)
        await scheduler.start()
    """
    if scheduler is None:
        scheduler = SchedulerRegistry.get()

    service = OHLCVCollectorService()

    scheduler.add_job(
        JobConfig(
            job_id=_JOB_ID,
            func=service.run_once,
            trigger="interval",
            trigger_args={"seconds": _SCAN_INTERVAL_SECONDS},
            lock_ttl_seconds=_LOCK_TTL_SECONDS,
            max_retries=1,
            retry_delay_seconds=5.0,
            enabled=True,
        )
    )

    logger.info(
        f"[DataCollector] Job '{_JOB_ID}' da dang ky "
        f"| interval={_SCAN_INTERVAL_SECONDS}s "
        f"| lock_ttl={_LOCK_TTL_SECONDS}s"
    )
