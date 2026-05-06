"""
vault.py — VaultService: Mã hóa / Giải mã chuỗi nhạy cảm
Sử dụng Fernet (AES-128-CBC + HMAC-SHA256) từ thư viện cryptography.

Yêu cầu biến môi trường:
    VAULT_ENCRYPTION_KEY: Fernet key hợp lệ (base64-encoded 32 bytes).
    Tạo key mới bằng: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger


class VaultService:
    """Dịch vụ mã hóa / giải mã chuỗi nhạy cảm (API Key, Secret, ...).

    Sử dụng thuật toán Fernet (symmetric encryption):
    - AES-128-CBC để mã hóa dữ liệu.
    - HMAC-SHA256 để xác thực tính toàn vẹn.

    Key được đọc từ biến môi trường ``VAULT_ENCRYPTION_KEY``.
    Nếu key không tồn tại hoặc không hợp lệ, các phương thức sẽ raise ``RuntimeError``.
    """

    _ENV_KEY_NAME: str = "VAULT_ENCRYPTION_KEY"

    @staticmethod
    def _get_fernet() -> Fernet:
        """Khởi tạo Fernet instance từ biến môi trường.

        Returns:
            Fernet instance đã được khởi tạo với key từ env.

        Raises:
            RuntimeError: Nếu ``VAULT_ENCRYPTION_KEY`` chưa được cấu hình
                hoặc giá trị không phải Fernet key hợp lệ.
        """
        raw_key = os.getenv(VaultService._ENV_KEY_NAME, "")
        if not raw_key:
            raise RuntimeError(
                f"❌ Biến môi trường '{VaultService._ENV_KEY_NAME}' chưa được cấu hình.\n"
                "Tạo key mới bằng lệnh:\n"
                "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
                f"Sau đó thêm vào file .env: {VaultService._ENV_KEY_NAME}=<key>"
            )
        try:
            return Fernet(raw_key.encode())
        except (ValueError, Exception) as exc:
            raise RuntimeError(
                f"❌ Giá trị '{VaultService._ENV_KEY_NAME}' không phải Fernet key hợp lệ: {exc}"
            ) from exc

    @staticmethod
    def encrypt_string(plain_text: str) -> str:
        """Mã hóa một chuỗi plain text thành ciphertext.

        Args:
            plain_text: Chuỗi cần mã hóa (vd: API key, secret).

        Returns:
            Chuỗi ciphertext dạng UTF-8 string (Fernet token).

        Raises:
            RuntimeError: Nếu ``VAULT_ENCRYPTION_KEY`` không hợp lệ.
            ValueError: Nếu ``plain_text`` là chuỗi rỗng.

        Example:
            >>> import os
            >>> from cryptography.fernet import Fernet
            >>> os.environ["VAULT_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
            >>> cipher = VaultService.encrypt_string("my_api_key_123")
            >>> assert cipher != "my_api_key_123"
            >>> assert len(cipher) > 0
        """
        if not plain_text:
            raise ValueError("plain_text không được là chuỗi rỗng.")

        fernet = VaultService._get_fernet()
        cipher_bytes = fernet.encrypt(plain_text.encode("utf-8"))
        return cipher_bytes.decode("utf-8")

    @staticmethod
    def decrypt_string(cipher_text: str) -> str:
        """Giải mã một chuỗi ciphertext về plain text.

        Args:
            cipher_text: Chuỗi ciphertext (Fernet token) cần giải mã.

        Returns:
            Chuỗi plain text gốc.

        Raises:
            RuntimeError: Nếu ``VAULT_ENCRYPTION_KEY`` không hợp lệ.
            ValueError: Nếu ``cipher_text`` là chuỗi rỗng hoặc không thể giải mã
                (sai key, dữ liệu bị hỏng, hoặc là plain text chưa mã hóa).

        Example:
            >>> import os
            >>> from cryptography.fernet import Fernet
            >>> os.environ["VAULT_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
            >>> cipher = VaultService.encrypt_string("my_secret_456")
            >>> plain = VaultService.decrypt_string(cipher)
            >>> assert plain == "my_secret_456"
        """
        if not cipher_text:
            raise ValueError("cipher_text không được là chuỗi rỗng.")

        fernet = VaultService._get_fernet()
        try:
            plain_bytes = fernet.decrypt(cipher_text.encode("utf-8"))
            return plain_bytes.decode("utf-8")
        except InvalidToken as exc:
            logger.error(
                "VaultService.decrypt_string thất bại: token không hợp lệ. "
                "Kiểm tra VAULT_ENCRYPTION_KEY hoặc dữ liệu có thể là plain text chưa mã hóa."
            )
            raise ValueError(
                "Không thể giải mã: token không hợp lệ hoặc sai key. "
                "Dữ liệu có thể là plain text chưa được mã hóa — hãy chạy migrate_api_keys.py."
            ) from exc

    @staticmethod
    def validate_key() -> None:
        """Kiểm tra ``VAULT_ENCRYPTION_KEY`` hợp lệ ngay khi khởi động.

        Dùng cho startup validation — gọi sớm trong ``main.py`` để fail-fast
        thay vì để lỗi xuất hiện muộn khi bot cần decrypt lần đầu.

        Raises:
            RuntimeError: Nếu ``VAULT_ENCRYPTION_KEY`` chưa được cấu hình
                hoặc giá trị không phải Fernet key hợp lệ.

        Example:
            >>> # Trong main.py, gọi trước khi khởi động BotManager:
            >>> VaultService.validate_key()  # Raise RuntimeError nếu key thiếu/sai
            >>> logger.info("VaultService ready.")
        """
        VaultService._get_fernet()
        logger.info("✅ VaultService: VAULT_ENCRYPTION_KEY hợp lệ.")

    @staticmethod
    def is_encrypted(value: str) -> bool:
        """Kiểm tra nhanh xem một chuỗi có phải Fernet token hay không.

        Không đảm bảo 100% chính xác, chỉ dùng để heuristic check
        trước khi quyết định có cần mã hóa lại không (dùng trong migration).

        Args:
            value: Chuỗi cần kiểm tra.

        Returns:
            True nếu trông giống Fernet token (bắt đầu bằng ``gAAAAA``), False nếu không.

        Example:
            >>> VaultService.is_encrypted("gAAAAAbcdef...")
            True
            >>> VaultService.is_encrypted("plain_api_key")
            False
        """
        return value.startswith("gAAAAA")
