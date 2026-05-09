"""
factory.py — StrategyFactory: Auto-Discovery & Registry.

Tự động quét đệ quy toàn bộ folder ``src/strategies/`` bằng
``pkgutil.walk_packages``, tìm mọi class kế thừa ``BaseStrategy``
có ``STRATEGY_NAME`` không rỗng, và build registry tập trung.

Nguyên tắc Zero-Core-Edit:
    Thêm strategy mới = tạo 1 file .py trong src/strategies/ (hoặc subfolder).
    Factory tự phát hiện khi khởi động — không cần sửa file nào khác.

Cách dùng:
    from src.strategies.factory import StrategyFactory

    # Tạo instance
    strategy = StrategyFactory.create("sma_macd_cross_v7", bot_params)

    # Lấy class (để gọi classmethod mà không cần instance)
    cls = StrategyFactory.get_strategy_class("adts")
    lookback = cls.get_required_lookback(bot_params)

    # Liệt kê tất cả strategy đã đăng ký
    names = StrategyFactory.list_names()
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from typing import Optional, Type

from loguru import logger

from src.strategies.base_strategy import BaseStrategy

# ── Internal registry ─────────────────────────────────────────────────────────
# Được build 1 lần khi module được import lần đầu.
# Key: STRATEGY_NAME (str), Value: class (subclass of BaseStrategy)
_REGISTRY: dict[str, Type[BaseStrategy]] = {}

# Flag để tránh scan nhiều lần
_REGISTRY_BUILT: bool = False


# ── Scanner ───────────────────────────────────────────────────────────────────

def _build_registry() -> None:
    """Quét đệ quy src/strategies/ và đăng ký tất cả strategy hợp lệ.

    Dùng ``pkgutil.walk_packages`` để tìm mọi module trong package
    ``src.strategies``, bao gồm cả file lẻ (ma_macd.py) và module
    trong subfolder (adts/strategy.py).

    Một class được đăng ký khi thỏa mãn đồng thời:
    1. Là subclass của BaseStrategy (không phải BaseStrategy chính nó).
    2. Có ``STRATEGY_NAME`` là string không rỗng.
    3. Không phải abstract class.

    Ghi đè an toàn: nếu 2 class có cùng STRATEGY_NAME, class được load
    sau sẽ ghi đè và log WARNING.
    """
    global _REGISTRY_BUILT

    if _REGISTRY_BUILT:
        return

    # Lấy package object của src.strategies
    import src.strategies as _strategies_pkg
    pkg_path = _strategies_pkg.__path__
    pkg_prefix = _strategies_pkg.__name__ + "."

    # walk_packages quét đệ quy: onerror=None để bỏ qua module lỗi import
    for module_info in pkgutil.walk_packages(
        path=pkg_path,
        prefix=pkg_prefix,
        onerror=_on_import_error,
    ):
        module_name = module_info.name

        # Bỏ qua factory.py chính nó và base_strategy.py để tránh circular
        if module_name in (
            "src.strategies.factory",
            "src.strategies.base_strategy",
        ):
            continue

        # Bỏ qua các module helper trong adts/ (không chứa strategy class)
        _SKIP_SUFFIXES = (
            ".config", ".models", ".indicators",
            ".risk_manager", ".scanner",
        )
        if any(module_name.endswith(s) for s in _SKIP_SUFFIXES):
            continue

        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            logger.warning(
                f"[StrategyFactory] Không thể import module '{module_name}': "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        # Tìm tất cả class trong module thỏa điều kiện
        for attr_name in dir(module):
            obj = getattr(module, attr_name, None)
            if not _is_valid_strategy_class(obj):
                continue

            name = obj.STRATEGY_NAME
            if name in _REGISTRY:
                logger.warning(
                    f"[StrategyFactory] STRATEGY_NAME '{name}' bị trùng: "
                    f"{_REGISTRY[name].__module__}.{_REGISTRY[name].__name__} "
                    f"bị ghi đè bởi "
                    f"{obj.__module__}.{obj.__name__}"
                )
            _REGISTRY[name] = obj
            logger.debug(
                f"[StrategyFactory] Đã đăng ký: '{name}' "
                f"← {obj.__module__}.{obj.__name__}"
            )

    _REGISTRY_BUILT = True
    logger.info(
        f"[StrategyFactory] Registry hoàn tất: "
        f"{len(_REGISTRY)} strategy(s) — {sorted(_REGISTRY.keys())}"
    )


def _is_valid_strategy_class(obj: object) -> bool:
    """Kiểm tra obj có phải strategy class hợp lệ để đăng ký không.

    Args:
        obj: Bất kỳ object nào từ dir(module).

    Returns:
        True nếu obj là subclass của BaseStrategy, có STRATEGY_NAME không rỗng,
        và không phải abstract class.
    """
    if not inspect.isclass(obj):
        return False
    if obj is BaseStrategy:
        return False
    if not issubclass(obj, BaseStrategy):
        return False
    # Bỏ qua abstract class (class chưa implement analyze)
    if inspect.isabstract(obj):
        return False
    # STRATEGY_NAME phải là string không rỗng
    name = getattr(obj, "STRATEGY_NAME", "")
    if not isinstance(name, str) or not name.strip():
        return False
    return True


def _on_import_error(module_name: str) -> None:
    """Callback khi pkgutil không thể import một module.

    Args:
        module_name: Tên module gây lỗi.
    """
    logger.debug(
        f"[StrategyFactory] pkgutil không thể scan module: '{module_name}'"
    )


# ── Public API ────────────────────────────────────────────────────────────────

class StrategyFactory:
    """Factory tập trung để tạo và tra cứu strategy instances.

    Tất cả methods đều là static/class methods — không cần khởi tạo instance.
    Registry được build tự động khi lần đầu gọi bất kỳ method nào.

    Example:
        # Tạo instance strategy
        strategy = StrategyFactory.create("sma_macd_cross_v7", bot_params)

        # Lấy lookback mà không cần instance
        cls = StrategyFactory.get_strategy_class("adts")
        lookback = cls.get_required_lookback(bot_params)

        # Kiểm tra strategy có tồn tại không
        if StrategyFactory.exists("my_new_strategy"):
            ...
    """

    @staticmethod
    def _ensure_registry() -> None:
        """Đảm bảo registry đã được build trước khi dùng."""
        if not _REGISTRY_BUILT:
            _build_registry()

    @staticmethod
    def create(name: str, config: dict) -> BaseStrategy:
        """Tạo instance của strategy theo tên.

        Thay thế toàn bộ chuỗi if/elif trong BotEngine.initialize().

        Args:
            name: STRATEGY_NAME của strategy (vd: "sma_macd_cross_v7").
            config: Dict tham số từ Bot.parameters.

        Returns:
            Instance của strategy tương ứng.

        Raises:
            ValueError: Nếu strategy_name không tồn tại trong registry.

        Example:
            strategy = StrategyFactory.create("adts", {"leverage": 5})
        """
        StrategyFactory._ensure_registry()

        cls = _REGISTRY.get(name)
        if cls is None:
            available = sorted(_REGISTRY.keys())
            raise ValueError(
                f"Strategy '{name}' khong ton tai trong registry. "
                f"Cac strategy da dang ky: {available}"
            )

        return cls(config)

    @staticmethod
    def get_strategy_class(name: str) -> Type[BaseStrategy]:
        """Lấy class của strategy theo tên (không tạo instance).

        Dùng để gọi @classmethod như ``get_required_lookback()``
        mà không cần khởi tạo instance đầy đủ.

        Args:
            name: STRATEGY_NAME của strategy.

        Returns:
            Class (không phải instance) của strategy.

        Raises:
            ValueError: Nếu strategy_name không tồn tại.

        Example:
            cls = StrategyFactory.get_strategy_class("sma_macd_cross")
            lookback = cls.get_required_lookback({"macd_signal_length": 500})
        """
        StrategyFactory._ensure_registry()

        cls = _REGISTRY.get(name)
        if cls is None:
            available = sorted(_REGISTRY.keys())
            raise ValueError(
                f"Strategy '{name}' khong ton tai trong registry. "
                f"Cac strategy da dang ky: {available}"
            )

        return cls

    @staticmethod
    def exists(name: str) -> bool:
        """Kiểm tra strategy có tồn tại trong registry không.

        Args:
            name: STRATEGY_NAME cần kiểm tra.

        Returns:
            True nếu strategy đã được đăng ký.
        """
        StrategyFactory._ensure_registry()
        return name in _REGISTRY

    @staticmethod
    def list_names() -> list[str]:
        """Trả về danh sách tên tất cả strategy đã đăng ký, sắp xếp theo alphabet.

        Dùng cho Dashboard API để hiển thị danh sách strategy cho user chọn.

        Returns:
            List[str] các STRATEGY_NAME đã đăng ký.
        """
        StrategyFactory._ensure_registry()
        return sorted(_REGISTRY.keys())

    @staticmethod
    def get_registry_snapshot() -> dict[str, str]:
        """Trả về snapshot của registry dạng {name: class_path}.

        Dùng cho debugging và health check.

        Returns:
            Dict ánh xạ STRATEGY_NAME → "module.ClassName".
        """
        StrategyFactory._ensure_registry()
        return {
            name: f"{cls.__module__}.{cls.__name__}"
            for name, cls in sorted(_REGISTRY.items())
        }

    @staticmethod
    def reset_registry() -> None:
        """Reset registry về trạng thái ban đầu.

        CHỈ dùng trong unit test để tái khởi tạo giữa các test case.
        KHÔNG dùng trong production code.
        """
        global _REGISTRY, _REGISTRY_BUILT
        _REGISTRY.clear()
        _REGISTRY_BUILT = False
        logger.debug("[StrategyFactory] Registry da duoc reset.")
