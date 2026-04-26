from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from src.database.db import get_db
from src.database.models import ExchangeAccount
from src.dashboard.schemas import AccountCreate

router = APIRouter(prefix="/api/accounts", tags=["Accounts"])

@router.get("")
async def get_accounts():
    async with get_db() as db:
        result = await db.execute(select(ExchangeAccount).where(ExchangeAccount.is_active == True))
        return [acc.to_dict() for acc in result.scalars().all()]

@router.post("")
async def create_account(acc_in: AccountCreate):
    async with get_db() as db:
        acc = ExchangeAccount(
            name=acc_in.name,
            api_key=acc_in.api_key,
            api_secret=acc_in.api_secret,
            mode=acc_in.mode
        )
        db.add(acc)
        await db.commit()
        return {"success": True, "id": acc.id}
