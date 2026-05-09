"""
strategies.py — FastAPI router cho Strategy Manifest API.

Cung cap thong tin schema cua tung strategy de Dashboard tu dong
render form nhap tham so — khong can hardcode field nao trong frontend.

Endpoints:
    GET /api/strategies/manifests    → Danh sach tat ca strategy kem schema
    GET /api/strategies/{name}       → Manifest cua 1 strategy cu the
"""
from fastapi import APIRouter, HTTPException

from src.strategies.factory import StrategyFactory

router = APIRouter(prefix="/api/strategies", tags=["Strategies"])


@router.get("/manifests")
async def list_strategy_manifests() -> list[dict]:
    """Tra ve danh sach tat ca strategy da dang ky kem PARAMETERS_SCHEMA.

    Frontend dung endpoint nay de render dropdown chon strategy va
    tu dong hien thi form nhap tham so tuong ung.

    Returns:
        List[dict] moi phan tu gom:
            - ``name`` (str): STRATEGY_NAME dinh danh duy nhat.
            - ``parameters_schema`` (dict): JSON Schema (Draft-7 subset)
              mo ta cac tham so. Rong ``{}`` neu strategy chua khai bao.

    Example response:
        [
            {
                "name": "adts",
                "parameters_schema": {
                    "type": "object",
                    "properties": {
                        "timeframe": {"type": "string", "default": "5m", ...},
                        "adx_threshold": {"type": "number", "default": 20.0, ...}
                    }
                }
            },
            {
                "name": "ma_macd",
                "parameters_schema": { ... }
            }
        ]
    """
    return StrategyFactory.list_manifests()


@router.get("/{name}")
async def get_strategy_manifest(name: str) -> dict:
    """Tra ve manifest cua mot strategy cu the theo ten.

    Args:
        name: STRATEGY_NAME cua strategy (vd: "adts", "ma_macd", "custom_sma").

    Returns:
        Dict gom:
            - ``name`` (str): STRATEGY_NAME.
            - ``parameters_schema`` (dict): JSON Schema mo ta tham so.

    Raises:
        HTTPException 404: Neu strategy khong ton tai trong registry.

    Example response:
        {
            "name": "adts",
            "parameters_schema": {
                "type": "object",
                "properties": {
                    "timeframe": {
                        "type": "string",
                        "title": "Timeframe",
                        "default": "5m",
                        "enum": ["1m", "3m", "5m", "15m", "30m", "1h", "4h"],
                        "ui:widget": "select"
                    },
                    "adx_threshold": {
                        "type": "number",
                        "title": "ADX Threshold (Shield)",
                        "default": 20.0,
                        "minimum": 5.0,
                        "maximum": 60.0,
                        "ui:widget": "number"
                    }
                }
            }
        }
    """
    if not StrategyFactory.exists(name):
        available = StrategyFactory.list_names()
        raise HTTPException(
            status_code=404,
            detail=(
                f"Strategy '{name}' khong ton tai. "
                f"Cac strategy hien co: {available}"
            ),
        )

    return StrategyFactory.get_strategy_manifest(name)
