"""
migrate_api_keys.py — Mã hóa lại API Key/Secret plain text trong Database.

Script này quét toàn bộ bảng ``exchange_accounts``, phát hiện các record
có api_key / api_secret đang là plain text (chưa mã hóa), và mã hóa lại
bằng VaultService.

Điều kiện chạy:
    - Biến môi trường ``VAULT_ENCRYPTION_KEY`` phải được cấu hình trong .env.
    - DATABASE_URL phải trỏ đúng đến database đang dùng.

Cách chạy:
    python scripts/migrate_api_keys.py

    # Chạy dry-run (chỉ xem, không ghi):
    python scripts/migrate_api_keys.py --dry-run

Idempotent: Các record đã mã hóa (Fernet token) sẽ được bỏ qua, không xử lý lại.
"""
import asyncio
import argparse
import sys
import os

# Thêm project root vào sys.path để import được src.*
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import ExchangeAccount
from src.core.security import VaultService


async def migrate_api_keys(dry_run: bool = False) -> None:
    """Quét và mã hóa các API key/secret đang là plain text.

    Args:
        dry_run: Nếu True, chỉ in ra các record sẽ bị ảnh hưởng mà không ghi DB.

    Raises:
        RuntimeError: Nếu ``VAULT_ENCRYPTION_KEY`` chưa được cấu hình.
        Exception: Nếu kết nối database thất bại.
    """
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("❌ DATABASE_URL chưa được cấu hình trong .env")

    # Validate VAULT_ENCRYPTION_KEY sớm trước khi kết nối DB
    VaultService.encrypt_string("__vault_key_check__")
    logger.info("✅ VAULT_ENCRYPTION_KEY hợp lệ.")

    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    migrated_count = 0
    skipped_count = 0
    error_count = 0

    async with async_session() as session:
        result = await session.execute(select(ExchangeAccount))
        accounts: list[ExchangeAccount] = result.scalars().all()

        logger.info(f"🔍 Tìm thấy {len(accounts)} ExchangeAccount(s) trong DB.")

        for account in accounts:
            needs_migration = _check_needs_migration(account)

            if not needs_migration:
                logger.info(f"  ⏭️  Account id={account.id} ({account.name}): đã mã hóa, bỏ qua.")
                skipped_count += 1
                continue

            logger.info(f"  🔐 Account id={account.id} ({account.name}): cần mã hóa.")

            if dry_run:
                logger.info(f"     [DRY-RUN] Sẽ mã hóa api_key và api_secret.")
                migrated_count += 1
                continue

            success = await _encrypt_account_keys(session, account)
            if success:
                migrated_count += 1
            else:
                error_count += 1

        if not dry_run:
            await session.commit()
            logger.info("💾 Đã commit thay đổi vào database.")

    await engine.dispose()

    _print_summary(migrated_count, skipped_count, error_count, dry_run)


def _check_needs_migration(account: ExchangeAccount) -> bool:
    """Kiểm tra xem account có cần migrate không.

    Args:
        account: ORM model ExchangeAccount cần kiểm tra.

    Returns:
        True nếu api_key hoặc api_secret chưa được mã hóa.
    """
    api_key_plain = account.api_key and not VaultService.is_encrypted(account.api_key)
    api_secret_plain = account.api_secret and not VaultService.is_encrypted(account.api_secret)
    return bool(api_key_plain or api_secret_plain)


async def _encrypt_account_keys(session: AsyncSession, account: ExchangeAccount) -> bool:
    """Mã hóa api_key và api_secret của một account.

    Args:
        session: AsyncSession đang active.
        account: ORM model ExchangeAccount cần mã hóa.

    Returns:
        True nếu mã hóa thành công, False nếu có lỗi.
    """
    try:
        if account.api_key and not VaultService.is_encrypted(account.api_key):
            account.api_key = VaultService.encrypt_string(account.api_key)
            logger.info(f"     ✅ Đã mã hóa api_key.")

        if account.api_secret and not VaultService.is_encrypted(account.api_secret):
            account.api_secret = VaultService.encrypt_string(account.api_secret)
            logger.info(f"     ✅ Đã mã hóa api_secret.")

        session.add(account)
        return True

    except Exception as exc:
        logger.error(
            f"     ❌ Lỗi khi mã hóa account id={account.id}: {exc}",
            exc_info=True,
        )
        return False


def _print_summary(migrated: int, skipped: int, errors: int, dry_run: bool) -> None:
    """In tóm tắt kết quả migration.

    Args:
        migrated: Số account đã được mã hóa (hoặc sẽ được mã hóa nếu dry-run).
        skipped: Số account đã mã hóa trước đó, bỏ qua.
        errors: Số account gặp lỗi.
        dry_run: True nếu đang ở chế độ dry-run.
    """
    mode_label = "[DRY-RUN] " if dry_run else ""
    logger.info("─" * 50)
    logger.info(f"📊 {mode_label}Kết quả Migration:")
    logger.info(f"   Đã mã hóa : {migrated}")
    logger.info(f"   Bỏ qua    : {skipped} (đã mã hóa trước đó)")
    logger.info(f"   Lỗi       : {errors}")
    logger.info("─" * 50)

    if errors > 0:
        logger.warning(f"⚠️  Có {errors} account gặp lỗi. Kiểm tra log ở trên để biết chi tiết.")
    elif dry_run:
        logger.info(f"ℹ️  Dry-run hoàn tất. Chạy lại không có --dry-run để áp dụng thay đổi.")
    else:
        logger.info("🎉 Migration hoàn tất thành công!")


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Namespace với thuộc tính ``dry_run``.
    """
    parser = argparse.ArgumentParser(
        description="Mã hóa lại API Key/Secret plain text trong Database."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ xem các record sẽ bị ảnh hưởng, không ghi vào DB.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(migrate_api_keys(dry_run=args.dry_run))
