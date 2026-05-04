"""
market_data.py — API Router cho Market Data Cache

Endpoints:
  GET  /api/market-data/status          → Trạng thái data của tất cả active datasets
  GET  /api/market-data/datasets        → Danh sách active datasets
  POST /api/market-data/refresh         → Tạo job refresh (full hoặc incremental)
  GET  /api/market-data/jobs            → Danh sách jobs gần nhất
  GET  /api/market-data/jobs/{job_id}   → Chi tiết job + chunks
  POST /api/market-data/jobs/{job_id}/retry → Retry các chunk failed
  POST /api/market-data/refresh-all     → Incremental update tất cả active datasets
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from loguru import logger

from src.data import ohlcv_service
from src.core.exchange import create_exchange_from_env

router = APIRouter(prefix="/api/market-data", tags=["Market Data"])

# ── In-memory job progress store ──────────────────────────────────────────────
# job_key → {"status", "progress", "message", "result", "error"}
_refresh_jobs: dict = {}


# ── Request models ────────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    strategy_name: str
    symbol: str
    timeframe: str
    full_refresh: bool = False   # True = xóa hết + kéo lại 5 năm


class RefreshAllRequest(BaseModel):
    full_refresh: bool = False


# ── Helper: tạo exchange ──────────────────────────────────────────────────────

async def _make_exchange():
    try:
        exchange = create_exchange_from_env()
        await exchange.connect()
        return exchange
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Không thể kết nối exchange: {e}")


# ── Background task runner ────────────────────────────────────────────────────

async def _bg_refresh(
    job_key: str,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    full_refresh: bool,
):
    """Background task: chạy refresh 1 dataset, cập nhật _refresh_jobs."""
    _refresh_jobs[job_key] = {
        "status": "running", "progress": 0,
        "message": "Đang kết nối exchange...",
        "result": None, "error": None,
    }

    exchange = None
    try:
        exchange = create_exchange_from_env()
        await exchange.connect()

        async def _progress(pct: float, msg: str):
            _refresh_jobs[job_key]["progress"] = pct
            _refresh_jobs[job_key]["message"]  = msg

        if full_refresh:
            result = await ohlcv_service.full_refresh(
                strategy_name, symbol, timeframe, exchange,
                progress_callback=_progress,
            )
        else:
            result = await ohlcv_service.incremental_update(
                strategy_name, symbol, timeframe, exchange,
                progress_callback=_progress,
            )

        _refresh_jobs[job_key].update({
            "status":   "done",
            "progress": 100,
            "message":  f"Hoàn tất: {result.get('total_inserted', 0)} nến mới",
            "result":   result,
        })

    except Exception as e:
        logger.error(f"[market_data] refresh job {job_key} lỗi: {e}")
        _refresh_jobs[job_key].update({
            "status":  "error",
            "message": str(e),
            "error":   str(e),
        })
    finally:
        if exchange:
            try:
                await exchange.close()
            except Exception:
                pass


async def _bg_refresh_all(job_key: str, full_refresh: bool):
    """Background task: incremental/full refresh tất cả active datasets."""
    _refresh_jobs[job_key] = {
        "status": "running", "progress": 0,
        "message": "Đang lấy danh sách datasets...",
        "result": None, "error": None,
    }

    exchange = None
    try:
        datasets = await ohlcv_service.get_active_datasets()
        if not datasets:
            _refresh_jobs[job_key].update({
                "status": "done", "progress": 100,
                "message": "Không có dataset nào cần cập nhật",
                "result": {"datasets": 0},
            })
            return

        exchange = create_exchange_from_env()
        await exchange.connect()

        total   = len(datasets)
        success = 0
        failed  = 0

        for idx, ds in enumerate(datasets):
            strategy = ds["strategy_name"]
            symbol   = ds["symbol"]
            tf       = ds["timeframe"]
            base_pct = round(idx / total * 100, 1)

            async def _progress(pct: float, msg: str, _base=base_pct, _total=total):
                overall = _base + pct / _total
                _refresh_jobs[job_key]["progress"] = round(overall, 1)
                _refresh_jobs[job_key]["message"]  = f"[{strategy}/{symbol}/{tf}] {msg}"

            try:
                if full_refresh:
                    await ohlcv_service.full_refresh(
                        strategy, symbol, tf, exchange,
                        progress_callback=_progress,
                    )
                else:
                    await ohlcv_service.incremental_update(
                        strategy, symbol, tf, exchange,
                        progress_callback=_progress,
                    )
                success += 1
            except Exception as e:
                logger.error(f"[market_data] refresh_all {strategy}/{symbol}/{tf}: {e}")
                failed += 1

        _refresh_jobs[job_key].update({
            "status":   "done",
            "progress": 100,
            "message":  f"Hoàn tất: {success}/{total} datasets OK, {failed} lỗi",
            "result":   {"success": success, "failed": failed, "total": total},
        })

    except Exception as e:
        logger.error(f"[market_data] refresh_all job {job_key} lỗi: {e}")
        _refresh_jobs[job_key].update({
            "status":  "error",
            "message": str(e),
            "error":   str(e),
        })
    finally:
        if exchange:
            try:
                await exchange.close()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/status")
async def get_status():
    """
    Trả về trạng thái data của tất cả active datasets.
    Bao gồm: số nến, ngày đầu, ngày cuối, lag (giờ).
    """
    datasets = await ohlcv_service.get_active_datasets()
    result = []
    for ds in datasets:
        info = await ohlcv_service.get_data_range(
            ds["strategy_name"], ds["symbol"], ds["timeframe"]
        )
        result.append({**ds, **info})
    return result


@router.get("/datasets")
async def get_datasets():
    """Danh sách active datasets (detect từ bots)."""
    return await ohlcv_service.get_active_datasets()


@router.post("/refresh")
async def refresh_dataset(req: RefreshRequest, background_tasks: BackgroundTasks):
    """
    Tạo job refresh cho 1 dataset.
    Trả về job_key để poll tiến độ.
    """
    job_key = f"{req.strategy_name}:{req.symbol}:{req.timeframe}:{uuid.uuid4().hex[:8]}"
    background_tasks.add_task(
        _bg_refresh,
        job_key, req.strategy_name, req.symbol, req.timeframe, req.full_refresh,
    )
    return {"job_key": job_key, "message": "Job đã được tạo"}


@router.get("/refresh/{job_key}")
async def get_refresh_progress(job_key: str):
    """Poll tiến độ của job refresh."""
    # job_key có thể chứa dấu : nên cần encode khi gọi từ client
    job = _refresh_jobs.get(job_key)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_key}' không tồn tại")
    return job


@router.post("/refresh-all")
async def refresh_all(req: RefreshAllRequest, background_tasks: BackgroundTasks):
    """Incremental (hoặc full) refresh tất cả active datasets."""
    job_key = f"refresh_all:{uuid.uuid4().hex[:8]}"
    background_tasks.add_task(_bg_refresh_all, job_key, req.full_refresh)
    return {"job_key": job_key, "message": "Job refresh-all đã được tạo"}


@router.get("/jobs")
async def list_jobs(limit: int = 50):
    """Danh sách fetch jobs gần nhất (từ DB)."""
    return await ohlcv_service.get_all_jobs(limit)


@router.get("/jobs/{job_id}")
async def get_job(job_id: int):
    """Chi tiết job kèm danh sách chunks."""
    detail = await ohlcv_service.get_job_detail(job_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Job {job_id} không tồn tại")
    return detail


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int, background_tasks: BackgroundTasks):
    """Retry các chunk failed trong job."""
    detail = await ohlcv_service.get_job_detail(job_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Job {job_id} không tồn tại")

    job_key = f"retry:{job_id}:{uuid.uuid4().hex[:8]}"
    _refresh_jobs[job_key] = {
        "status": "running", "progress": 0,
        "message": "Đang retry chunks failed...",
        "result": None, "error": None,
    }

    async def _bg_retry():
        exchange = None
        try:
            exchange = create_exchange_from_env()
            await exchange.connect()

            async def _progress(pct: float, msg: str):
                _refresh_jobs[job_key]["progress"] = pct
                _refresh_jobs[job_key]["message"]  = msg

            result = await ohlcv_service.retry_failed_chunks(job_id, exchange, _progress)
            _refresh_jobs[job_key].update({
                "status": "done", "progress": 100,
                "message": f"Retry hoàn tất: {result.get('total_inserted', 0)} nến",
                "result": result,
            })
        except Exception as e:
            _refresh_jobs[job_key].update({
                "status": "error", "message": str(e), "error": str(e),
            })
        finally:
            if exchange:
                try:
                    await exchange.close()
                except Exception:
                    pass

    background_tasks.add_task(_bg_retry)
    return {"job_key": job_key, "message": "Retry job đã được tạo"}
