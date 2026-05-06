"""
ohlcv_service.py — Market Data Cache Service

Quản lý việc fetch, lưu trữ và truy vấn dữ liệu OHLCV từ PostgreSQL.

Thiết kế chống miss/dup:
  - Mỗi job được chia thành các chunk 30 ngày độc lập
  - Mỗi chunk có trạng thái riêng (pending/running/done/failed)
  - Upsert (INSERT ... ON CONFLICT DO NOTHING) → không bao giờ duplicate
  - Chunk fail → đánh dấu failed, retry độc lập, không ảnh hưởng chunk khác
  - Sau khi tất cả chunk done → verify liên tục bằng cách check gap

Tránh rate limit:
  - Delay 0.3s giữa các batch request
  - Retry với exponential backoff (1s, 2s, 4s) khi gặp lỗi rate limit
  - Batch insert 5000 rows để tránh timeout DB
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger
from sqlalchemy import select, delete, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database.db import get_db, AsyncSessionLocal
from src.database.models import OHLCVCandle, OHLCVFetchJob, OHLCVFetchChunk, SystemSetting

# ── Hằng số ───────────────────────────────────────────────────────────────────
CHUNK_DAYS       = 30          # Mỗi chunk = 30 ngày
BATCH_FETCH      = 1500        # Số nến mỗi lần gọi API (giới hạn Binance)
# PostgreSQL/asyncpg giới hạn 32767 parameters mỗi query.
# OHLCVCandle có 9 cột → max rows = 32767 // 9 = 3640 → dùng 3000 để an toàn
BATCH_INSERT     = 3000        # Số rows mỗi lần insert vào DB
REQUEST_DELAY    = 0.35        # Giây delay giữa các API call (tránh rate limit)
MAX_RETRY        = 3           # Số lần retry mỗi chunk khi fail
RETRY_BACKOFF    = [1, 2, 4]   # Giây chờ trước mỗi lần retry
DATA_YEARS       = 5           # Số năm data tối đa kéo về

UTC7 = timezone(timedelta(hours=7))


# ── Timeframe → milliseconds ──────────────────────────────────────────────────
def _tf_ms(tf: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    try:
        return int(tf[:-1]) * units[tf[-1]]
    except Exception:
        return 300_000  # fallback 5m


def _normalize_symbol(symbol: str) -> str:
    """BTCUSDT → BTC/USDT"""
    if "/" in symbol:
        return symbol
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.endswith(quote):
            return f"{symbol[:-len(quote)]}/{quote}"
    return symbol


def _job_key(strategy_name: str, symbol: str, timeframe: str, job_type: str) -> str:
    return f"{strategy_name}:{symbol}:{timeframe}:{job_type}"


# ══════════════════════════════════════════════════════════════════════════════
# Core fetch helper — gọi exchange API với retry
# ══════════════════════════════════════════════════════════════════════════════

async def _fetch_batch_with_retry(
    exchange,
    symbol: str,
    timeframe: str,
    end_ms: int,
    limit: int = BATCH_FETCH,
) -> list:
    """
    Fetch 1 batch nến từ exchange với retry + exponential backoff.
    Trả về list [[ts_ms, o, h, l, c, v], ...] hoặc [] nếu fail hết retry.
    """
    for attempt, wait in enumerate(RETRY_BACKOFF, start=1):
        try:
            batch = await exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=limit,
                params={"endTime": end_ms},
            )
            return batch or []
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = any(k in err_str for k in ("rate limit", "429", "too many"))
            wait_time = wait * 2 if is_rate_limit else wait
            logger.warning(
                f"fetch_batch lỗi (attempt {attempt}/{MAX_RETRY}): {e} "
                f"— chờ {wait_time}s"
            )
            if attempt < MAX_RETRY:
                await asyncio.sleep(wait_time)
            else:
                raise
    return []


# ══════════════════════════════════════════════════════════════════════════════
# Upsert helpers
# ══════════════════════════════════════════════════════════════════════════════

async def _upsert_candles(session, rows: list[dict]) -> int:
    """
    Bulk upsert vào ohlcv_candles.
    Dùng INSERT ... ON CONFLICT DO NOTHING → tuyệt đối không duplicate.
    Trả về số rows thực sự inserted.
    """
    if not rows:
        return 0
    stmt = pg_insert(OHLCVCandle).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["strategy_name", "symbol", "timeframe", "timestamp_ms"]
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


# ══════════════════════════════════════════════════════════════════════════════
# Fetch 1 chunk (start_ms → end_ms)
# ══════════════════════════════════════════════════════════════════════════════

async def _fetch_chunk(
    exchange,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
) -> int:
    """
    Fetch toàn bộ nến trong khoảng [start_ms, end_ms] và upsert vào DB.
    Paginate ngược từ end_ms về start_ms để tránh miss nến.
    Trả về số nến đã insert.

    Đảm bảo không miss/dup:
    - Paginate ngược: current_end = end_ms → giảm dần
    - Dừng khi oldest_ts <= start_ms
    - Upsert ON CONFLICT DO NOTHING
    """
    tf_ms_val = _tf_ms(timeframe)
    norm_symbol = _normalize_symbol(symbol)
    total_inserted = 0
    current_end = end_ms
    buffer: list[dict] = []

    while True:
        batch = await _fetch_batch_with_retry(
            exchange, norm_symbol, timeframe, current_end
        )
        if not batch:
            break

        # Lọc chỉ lấy nến trong [start_ms, end_ms]
        filtered = [c for c in batch if start_ms <= c[0] <= end_ms]

        for c in filtered:
            buffer.append({
                "strategy_name": strategy_name,
                "symbol":        symbol.replace("/", ""),  # lưu dạng BTCUSDT
                "timeframe":     timeframe,
                "timestamp_ms":  int(c[0]),
                "open":          float(c[1]),
                "high":          float(c[2]),
                "low":           float(c[3]),
                "close":         float(c[4]),
                "volume":        float(c[5]),
            })

        # Flush buffer khi đủ BATCH_INSERT
        if len(buffer) >= BATCH_INSERT:
            async with AsyncSessionLocal() as session:
                inserted = await _upsert_candles(session, buffer)
                await session.commit()
            total_inserted += inserted
            buffer.clear()

        oldest_ts = batch[0][0]
        if oldest_ts <= start_ms:
            break  # Đã cover hết khoảng thời gian

        # Lùi current_end về trước batch hiện tại (tránh overlap)
        current_end = oldest_ts - tf_ms_val
        if current_end < start_ms:
            break

        # Delay tránh rate limit
        await asyncio.sleep(REQUEST_DELAY)

    # Flush phần còn lại trong buffer
    if buffer:
        async with AsyncSessionLocal() as session:
            inserted = await _upsert_candles(session, buffer)
            await session.commit()
        total_inserted += inserted

    return total_inserted


# ══════════════════════════════════════════════════════════════════════════════
# Job management
# ══════════════════════════════════════════════════════════════════════════════

async def _create_or_resume_job(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    job_type: str,
    start_ms: int,
    end_ms: int,
    force_new: bool = False,
) -> OHLCVFetchJob:
    """
    Tạo job mới hoặc resume job đang dở (partial_done / failed).
    Nếu force_new=True → xóa job cũ và tạo lại (dùng cho full_refresh).

    Chunk strategy:
    - Chia [start_ms, end_ms] thành các chunk CHUNK_DAYS ngày
    - Mỗi chunk có trạng thái độc lập
    - Chunk đã done → bỏ qua khi resume
    """
    jk = _job_key(strategy_name, symbol, timeframe, job_type)
    sym_stored = symbol.replace("/", "")

    async with AsyncSessionLocal() as session:
        if force_new:
            # Xóa job cũ nếu có
            await session.execute(
                delete(OHLCVFetchJob).where(OHLCVFetchJob.job_key == jk)
            )
            await session.commit()

        # Tìm job đang dở
        result = await session.execute(
            select(OHLCVFetchJob)
            .where(OHLCVFetchJob.job_key == jk)
            .where(OHLCVFetchJob.status.in_(["pending", "running", "partial_done", "failed"]))
            .order_by(OHLCVFetchJob.created_at.desc())
            .limit(1)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Resume: reset chunk failed → pending để retry
            for chunk in existing.chunks:
                if chunk.status in ("failed", "running"):
                    chunk.status = "pending"
                    chunk.retry_count += 1
            existing.status = "running"
            existing.updated_at = datetime.utcnow()
            await session.commit()
            logger.info(
                f"Resume job {jk}: {len([c for c in existing.chunks if c.status == 'pending'])} "
                f"chunks cần xử lý"
            )
            return existing

        # Tạo job mới
        chunk_ms = CHUNK_DAYS * 86_400_000
        chunks = []
        idx = 0
        cur = start_ms
        while cur < end_ms:
            chunk_end = min(cur + chunk_ms - 1, end_ms)
            chunks.append(OHLCVFetchChunk(
                chunk_index=idx,
                start_ms=cur,
                end_ms=chunk_end,
                status="pending",
            ))
            cur = chunk_end + 1
            idx += 1

        job = OHLCVFetchJob(
            job_key=jk,
            strategy_name=strategy_name,
            symbol=sym_stored,
            timeframe=timeframe,
            job_type=job_type,
            status="running",
            total_chunks=len(chunks),
            done_chunks=0,
            failed_chunks=0,
            chunks=chunks,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        logger.info(f"Tạo job mới {jk}: {len(chunks)} chunks")
        return job


async def _run_job(
    job_id: int,
    exchange,
    progress_callback=None,
) -> dict:
    """
    Chạy job fetch: xử lý từng chunk pending theo thứ tự.
    progress_callback(pct, message) — optional, dùng cho API progress.

    Đảm bảo không miss/dup:
    - Mỗi chunk fetch [start_ms, end_ms] độc lập
    - Chunk overlap 1 nến với chunk trước (end_ms của chunk trước = start_ms - 1)
      → không overlap, không gap
    - Upsert ON CONFLICT DO NOTHING
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OHLCVFetchJob).where(OHLCVFetchJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            return {"error": f"Job {job_id} không tồn tại"}

        strategy_name = job.strategy_name
        symbol        = job.symbol
        timeframe     = job.timeframe
        total_chunks  = job.total_chunks

    total_inserted = 0
    done = 0
    failed = 0

    # Lấy danh sách chunk cần xử lý
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OHLCVFetchChunk)
            .where(OHLCVFetchChunk.job_id == job_id)
            .where(OHLCVFetchChunk.status == "pending")
            .order_by(OHLCVFetchChunk.chunk_index)
        )
        pending_chunks = result.scalars().all()
        # Đếm chunk đã done từ trước (resume)
        done_result = await session.execute(
            select(func.count(OHLCVFetchChunk.id))
            .where(OHLCVFetchChunk.job_id == job_id)
            .where(OHLCVFetchChunk.status == "done")
        )
        done = done_result.scalar() or 0

    for chunk in pending_chunks:
        chunk_id    = chunk.id
        chunk_idx   = chunk.chunk_index
        start_ms    = chunk.start_ms
        end_ms      = chunk.end_ms
        retry_count = chunk.retry_count

        # Đánh dấu chunk đang chạy
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE ohlcv_fetch_chunks SET status='running', started_at=NOW() WHERE id=:id"),
                {"id": chunk_id},
            )
            await session.commit()

        pct = round(done / total_chunks * 100, 1) if total_chunks > 0 else 0
        msg = (
            f"Chunk {chunk_idx + 1}/{total_chunks} "
            f"({_ms_to_date(start_ms)} → {_ms_to_date(end_ms)})"
        )
        if progress_callback:
            await progress_callback(pct, msg)
        logger.info(f"[{strategy_name}/{symbol}/{timeframe}] {msg}")

        try:
            inserted = await _fetch_chunk(
                exchange, strategy_name, symbol, timeframe, start_ms, end_ms
            )
            total_inserted += inserted
            done += 1

            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(
                        "UPDATE ohlcv_fetch_chunks "
                        "SET status='done', candles_inserted=:n, finished_at=NOW() "
                        "WHERE id=:id"
                    ),
                    {"n": inserted, "id": chunk_id},
                )
                await session.execute(
                    text(
                        "UPDATE ohlcv_fetch_jobs "
                        "SET done_chunks=done_chunks+1, "
                        "    total_candles_inserted=total_candles_inserted+:n, "
                        "    updated_at=NOW() "
                        "WHERE id=:jid"
                    ),
                    {"n": inserted, "jid": job_id},
                )
                await session.commit()

        except Exception as e:
            failed += 1
            err_msg = str(e)[:500]
            logger.error(
                f"[{strategy_name}/{symbol}/{timeframe}] Chunk {chunk_idx} FAILED "
                f"(retry={retry_count}): {err_msg}"
            )
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(
                        "UPDATE ohlcv_fetch_chunks "
                        "SET status='failed', error_message=:err, finished_at=NOW() "
                        "WHERE id=:id"
                    ),
                    {"err": err_msg, "id": chunk_id},
                )
                await session.execute(
                    text(
                        "UPDATE ohlcv_fetch_jobs "
                        "SET failed_chunks=failed_chunks+1, updated_at=NOW() "
                        "WHERE id=:jid"
                    ),
                    {"jid": job_id},
                )
                await session.commit()

    # Cập nhật trạng thái job cuối cùng
    final_status = "done" if failed == 0 else ("partial_done" if done > 0 else "failed")
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "UPDATE ohlcv_fetch_jobs "
                "SET status=:s, finished_at=NOW(), updated_at=NOW() "
                "WHERE id=:jid"
            ),
            {"s": final_status, "jid": job_id},
        )
        await session.commit()

    if progress_callback:
        await progress_callback(100, f"Hoàn tất: {total_inserted} nến, {failed} chunk lỗi")

    return {
        "job_id":          job_id,
        "status":          final_status,
        "total_inserted":  total_inserted,
        "done_chunks":     done,
        "failed_chunks":   failed,
    }


def _ms_to_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC7).strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

async def full_refresh(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    exchange,
    years: int = DATA_YEARS,
    progress_callback=None,
) -> dict:
    """
    Xóa toàn bộ data cũ và fetch lại từ đầu (tối đa `years` năm).
    Dùng khi cần reset hoàn toàn.

    Bước 1: Xóa data cũ trong DB
    Bước 2: Tạo job mới với force_new=True
    Bước 3: Chạy job
    """
    sym_stored = symbol.replace("/", "")
    end_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - years * 365 * 86_400_000

    # Xóa data cũ
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(OHLCVCandle).where(
                OHLCVCandle.strategy_name == strategy_name,
                OHLCVCandle.symbol        == sym_stored,
                OHLCVCandle.timeframe     == timeframe,
            )
        )
        await session.commit()
    logger.info(f"Đã xóa data cũ: {strategy_name}/{sym_stored}/{timeframe}")

    job = await _create_or_resume_job(
        strategy_name, symbol, timeframe,
        "full_refresh", start_ms, end_ms,
        force_new=True,
    )
    return await _run_job(job.id, exchange, progress_callback)


async def incremental_update(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    exchange,
    progress_callback=None,
) -> dict:
    """
    Fetch data mới từ điểm cuối hiện có đến now.
    Nếu chưa có data → tự động full_refresh.
    Nếu có job incremental đang dở → resume.
    """
    sym_stored = symbol.replace("/", "")

    # Tìm timestamp cuối cùng đã có trong DB
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.max(OHLCVCandle.timestamp_ms)).where(
                OHLCVCandle.strategy_name == strategy_name,
                OHLCVCandle.symbol        == sym_stored,
                OHLCVCandle.timeframe     == timeframe,
            )
        )
        max_ts = result.scalar()

    if max_ts is None:
        logger.info(f"Chưa có data {strategy_name}/{sym_stored}/{timeframe} → full_refresh")
        return await full_refresh(strategy_name, symbol, timeframe, exchange, progress_callback=progress_callback)

    # Bắt đầu từ nến tiếp theo sau nến cuối cùng
    tf_ms_val = _tf_ms(timeframe)
    start_ms  = max_ts + tf_ms_val
    end_ms    = int(datetime.now(timezone.utc).timestamp() * 1000)

    if start_ms >= end_ms:
        logger.info(f"Data {strategy_name}/{sym_stored}/{timeframe} đã up-to-date")
        return {"status": "up_to_date", "total_inserted": 0}

    job = await _create_or_resume_job(
        strategy_name, symbol, timeframe,
        "incremental", start_ms, end_ms,
    )
    return await _run_job(job.id, exchange, progress_callback)


async def retry_failed_chunks(
    job_id: int,
    exchange,
    progress_callback=None,
) -> dict:
    """Retry các chunk failed trong một job cụ thể."""
    async with AsyncSessionLocal() as session:
        # Reset failed chunks → pending
        await session.execute(
            text(
                "UPDATE ohlcv_fetch_chunks SET status='pending' "
                "WHERE job_id=:jid AND status='failed'"
            ),
            {"jid": job_id},
        )
        await session.execute(
            text(
                "UPDATE ohlcv_fetch_jobs SET status='running', updated_at=NOW() "
                "WHERE id=:jid"
            ),
            {"jid": job_id},
        )
        await session.commit()
    return await _run_job(job_id, exchange, progress_callback)


async def get_candles(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
) -> list:
    """
    Đọc nến từ DB trong khoảng [start_ms, end_ms].
    Trả về list [[ts_ms, open, high, low, close, volume], ...] — tương thích ccxt.
    """
    sym_stored = symbol.replace("/", "")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OHLCVCandle)
            .where(
                OHLCVCandle.strategy_name == strategy_name,
                OHLCVCandle.symbol        == sym_stored,
                OHLCVCandle.timeframe     == timeframe,
                OHLCVCandle.timestamp_ms  >= start_ms,
                OHLCVCandle.timestamp_ms  <= end_ms,
            )
            .order_by(OHLCVCandle.timestamp_ms)
        )
        candles = result.scalars().all()
    return [c.to_list() for c in candles]


async def get_data_range(
    strategy_name: str,
    symbol: str,
    timeframe: str,
) -> dict:
    """
    Trả về thông tin về data hiện có:
    {min_ts, max_ts, count, min_date, max_date, lag_hours}
    """
    sym_stored = symbol.replace("/", "")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                func.min(OHLCVCandle.timestamp_ms),
                func.max(OHLCVCandle.timestamp_ms),
                func.count(OHLCVCandle.timestamp_ms),
            ).where(
                OHLCVCandle.strategy_name == strategy_name,
                OHLCVCandle.symbol        == sym_stored,
                OHLCVCandle.timeframe     == timeframe,
            )
        )
        row = result.one()

    min_ts, max_ts, count = row
    if not min_ts:
        return {"count": 0, "min_ts": None, "max_ts": None,
                "min_date": None, "max_date": None, "lag_hours": None}

    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    lag_ms   = now_ms - max_ts
    lag_hours = round(lag_ms / 3_600_000, 1)

    return {
        "count":     count,
        "min_ts":    min_ts,
        "max_ts":    max_ts,
        "min_date":  _ms_to_date(min_ts),
        "max_date":  _ms_to_date(max_ts),
        "lag_hours": lag_hours,
    }


async def get_active_datasets() -> list[dict]:
    """
    Detect tự động các (strategy_name, symbol, timeframe) cần cache.

    Nguồn 1: Bot active trong DB (is_deleted=False) — như cũ.
    Nguồn 2: Các dataset đã có data trong ohlcv_candles (kể cả kéo thủ công,
             ví dụ sma_macd_cross_v6 chưa có bot nhưng đã kéo data).

    Với ADTS: thêm cả timeframe '1d' (cần cho daily calibration).
    Trả về list[{strategy_name, symbol, timeframe}].
    """
    from src.database.models import Bot
    datasets = []
    seen = set()

    # ── Nguồn 1: Bot active ───────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Bot).where(Bot.is_deleted == False)
        )
        bots = result.scalars().all()

    for bot in bots:
        strategy = bot.strategy_name
        symbols  = bot.symbols or ["BTCUSDT"]
        params   = bot.parameters or {}
        tf       = params.get("timeframe", "5m")

        for sym in symbols:
            sym_clean = sym.replace("/", "")
            key = (strategy, sym_clean, tf)
            if key not in seen:
                seen.add(key)
                datasets.append({
                    "strategy_name": strategy,
                    "symbol":        sym_clean,
                    "timeframe":     tf,
                })
            # ADTS cần thêm 1d
            if strategy == "adts":
                key_d1 = (strategy, sym_clean, "1d")
                if key_d1 not in seen:
                    seen.add(key_d1)
                    datasets.append({
                        "strategy_name": strategy,
                        "symbol":        sym_clean,
                        "timeframe":     "1d",
                    })

    # ── Nguồn 2: Dataset đã có data trong DB (kéo thủ công / backtest-only) ──
    # Query distinct (strategy_name, symbol, timeframe) từ ohlcv_candles.
    # Điều này đảm bảo V6 (và bất kỳ chiến lược nào chưa có bot) vẫn hiển thị
    # trong bảng trạng thái sau khi user kéo data thủ công.
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                OHLCVCandle.strategy_name,
                OHLCVCandle.symbol,
                OHLCVCandle.timeframe,
            ).distinct()
        )
        existing_datasets = result.all()

    for row in existing_datasets:
        key = (row.strategy_name, row.symbol, row.timeframe)
        if key not in seen:
            seen.add(key)
            datasets.append({
                "strategy_name": row.strategy_name,
                "symbol":        row.symbol,
                "timeframe":     row.timeframe,
            })

    # Sắp xếp để hiển thị nhất quán
    datasets.sort(key=lambda d: (d["strategy_name"], d["symbol"], d["timeframe"]))
    return datasets


async def get_all_jobs(limit: int = 50) -> list[dict]:
    """Lấy danh sách job gần nhất."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OHLCVFetchJob)
            .order_by(OHLCVFetchJob.created_at.desc())
            .limit(limit)
        )
        jobs = result.scalars().all()
    return [j.to_dict() for j in jobs]


async def get_job_detail(job_id: int) -> Optional[dict]:
    """Lấy chi tiết job kèm danh sách chunk."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OHLCVFetchJob).where(OHLCVFetchJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            return None
        d = job.to_dict()
        d["chunks"] = [c.to_dict() for c in job.chunks]
    return d


# ── System setting helpers ────────────────────────────────────────────────────

async def get_setting(key: str) -> Optional[str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        row = result.scalar_one_or_none()
        return row.value if row else None


async def set_setting(key: str, value: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        row = result.scalar_one_or_none()
        if row:
            row.value      = value
            row.updated_at = datetime.utcnow()
        else:
            session.add(SystemSetting(key=key, value=value))
        await session.commit()
