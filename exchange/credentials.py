"""
API Key加密存储
AES-256加密，PBKDF2密钥派生
"""

import os
import base64
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    logger.warning("[凭证管理] cryptography未安装，加密存储不可用")

from config import PROJECT_ROOT, MASTER_PASSWORD


CREDENTIALS_FILE = PROJECT_ROOT / ".env.credentials"
SALT = b"delta-quant-v9-salt"


class CredentialManager:
    """API Key加密存储管理器"""

    def __init__(self, master_password: str = ""):
        self._password = master_password or MASTER_PASSWORD
        self._fernet = None

        if HAS_CRYPTO and self._password:
            self._init_crypto()

    def _init_crypto(self):
        """初始化加密"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=SALT,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self._password.encode()))
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """加密字符串"""
        if not self._fernet:
            return plaintext
        return "enc:" + self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """解密字符串"""
        if not ciphertext.startswith("enc:"):
            return ciphertext
        if not self._fernet:
            return ciphertext[4:]
        return self._fernet.decrypt(ciphertext[4:].encode()).decode()

    def save_credentials(self, platform: str, credentials: Dict[str, str]):
        """
        保存凭证到 .env.credentials

        Args:
            platform: "binance" / "okx"
            credentials: {"api_key": "xxx", "api_secret": "yyy", ...}
        """
        existing = self._load_file()
        prefix = platform.upper() + "_"

        # 更新或新增
        for key, value in credentials.items():
            env_key = f"{prefix}{key.upper()}"
            existing[env_key] = self.encrypt(value)

        # 写回文件
        self._write_file(existing)
        logger.info(f"[凭证管理] {platform} 凭证已保存")

    def load_credentials(self, platform: str) -> Dict[str, str]:
        """
        读取并解密凭证

        Args:
            platform: "binance" / "okx"

        Returns:
            {"api_key": "xxx", "api_secret": "yyy", ...}
        """
        all_creds = self._load_file()
        prefix = platform.upper() + "_"
        result = {}

        for key, value in all_creds.items():
            if key.startswith(prefix):
                short_key = key[len(prefix):].lower()
                result[short_key] = self.decrypt(value)

        return result

    def has_credentials(self, platform: str) -> bool:
        """检查是否有某平台的凭证"""
        creds = self.load_credentials(platform)
        if platform == "binance":
            return bool(creds.get("api_key") and creds.get("api_secret"))
        elif platform == "okx":
            return bool(
                creds.get("api_key")
                and creds.get("api_secret")
                and creds.get("passphrase")
            )
        return False

    def delete_credentials(self, platform: str):
        """删除某平台的凭证"""
        existing = self._load_file()
        prefix = platform.upper() + "_"
        keys_to_delete = [k for k in existing if k.startswith(prefix)]
        for k in keys_to_delete:
            del existing[k]
        self._write_file(existing)
        logger.info(f"[凭证管理] {platform} 凭证已删除")

    def _load_file(self) -> Dict[str, str]:
        """读取凭证文件"""
        creds = {}
        if not CREDENTIALS_FILE.exists():
            return creds
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    creds[key.strip()] = value.strip()
        return creds

    def _write_file(self, creds: Dict[str, str]):
        """写入凭证文件"""
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            f.write("# Delta Quant v9.0 - 加密凭证文件\n")
            f.write("# 请勿手动编辑，由系统管理\n\n")
            for key, value in sorted(creds.items()):
                f.write(f"{key}={value}\n")


# 全局实例
credential_manager = CredentialManager()
