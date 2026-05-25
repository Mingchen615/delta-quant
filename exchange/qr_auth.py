"""
扫码授权管理
生成QR Code，引导用户创建API Key
"""

import base64
from io import BytesIO
from typing import Optional

from loguru import logger

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False
    logger.warning("[扫码授权] qrcode库未安装，QR Code功能不可用")

from exchange.base_exchange import BaseExchange
from exchange.credentials import credential_manager


# 交易所API创建页面URL
EXCHANGE_API_URLS = {
    "binance": "https://www.binance.com/zh-CN/my/settings/api-management",
    "okx": "https://www.okx.com/account/my-api",
}


class QRAuthManager:
    """扫码授权管理器"""

    def generate_qr_base64(self, exchange_name: str) -> Optional[str]:
        """
        生成QR Code的base64编码

        Args:
            exchange_name: "binance" / "okx"

        Returns:
            base64编码的PNG图片，失败返回None
        """
        if not HAS_QRCODE:
            logger.error("[扫码授权] qrcode库未安装")
            return None

        url = EXCHANGE_API_URLS.get(exchange_name)
        if not url:
            logger.error(f"[扫码授权] 不支持的交易所: {exchange_name}")
            return None

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()

    def print_qr_terminal(self, exchange_name: str):
        """
        在终端打印QR Code

        Args:
            exchange_name: "binance" / "okx"
        """
        if not HAS_QRCODE:
            print(f"[扫码授权] 请手动访问: {EXCHANGE_API_URLS.get(exchange_name, '未知')}")
            return

        url = EXCHANGE_API_URLS.get(exchange_name)
        if not url:
            print(f"[扫码授权] 不支持的交易所: {exchange_name}")
            return

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make()
        qr.print_ascii(invert=True)

    async def connect_exchange(
        self,
        exchange: BaseExchange,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
    ) -> tuple[bool, str]:
        """
        验证并连接交易所（直接HTTP请求验证，绕过ccxt的load_markets）

        Returns:
            (成功与否, 错误信息或成功信息)
        """
        import hashlib
        import hmac
        import time
        import aiohttp

        exchange_name = exchange.exchange_name

        try:
            if exchange_name == "binance":
                balance_total = await self._verify_binance(api_key, api_secret)
            elif exchange_name == "okx":
                balance_total = await self._verify_okx(api_key, api_secret, passphrase)
            else:
                return False, f"不支持的交易所: {exchange_name}"
        except Exception as e:
            err_msg = str(e)
            if "-2015" in err_msg or "Invalid API" in err_msg:
                return False, "API Key无效或权限不足，请检查：1)Key是否正确 2)是否勾选了现货/合约交易权限 3)IP白名单设置"
            elif "-2008" in err_msg or "Invalid Api-Key" in err_msg:
                return False, "API Key格式错误"
            elif "password" in err_msg.lower() or "passphrase" in err_msg.lower():
                return False, "Passphrase错误"
            else:
                return False, f"验证失败: {err_msg[:200]}"

        # 设置凭证到exchange对象
        exchange._api_key = api_key
        exchange._api_secret = api_secret
        if passphrase and hasattr(exchange, "_passphrase"):
            exchange._passphrase = passphrase
        exchange._exchange = None
        exchange._connected = True

        # 加密存储凭证
        creds = {
            "api_key": api_key,
            "api_secret": api_secret,
        }
        if passphrase:
            creds["passphrase"] = passphrase

        credential_manager.save_credentials(exchange_name, creds)

        # 异步初始化ccxt实例（加载市场数据）
        try:
            await exchange.connect()
        except Exception as e:
            logger.warning(f"[扫码授权] {exchange_name} connect()警告: {e}")

        logger.info(f"[扫码授权] {exchange_name} 连接成功, 余额: ${balance_total:.2f}")
        return True, f"接入成功! 余额: ${balance_total:.2f}"

    async def _verify_binance(self, api_key: str, api_secret: str) -> float:
        """用同步ccxt验证币安API Key"""
        import ccxt

        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
            'proxies': {
                'http': 'http://127.0.0.1:7890',
                'https': 'http://127.0.0.1:7890',
            },
        })

        balance = exchange.fetch_balance()
        usdt = float(balance.get('USDT', {}).get('total', 0))
        return usdt

    async def _verify_okx(self, api_key: str, api_secret: str, passphrase: str) -> float:
        """用同步ccxt验证OKX API Key（参考okx-chan-theory-trader）"""
        import ccxt

        config = {
            'apiKey': api_key,
            'secret': api_secret,
            'password': passphrase,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
            'proxies': {
                'http': 'http://127.0.0.1:7890',
                'https': 'http://127.0.0.1:7890',
            },
        }

        exchange = ccxt.okx(config)

        balance = exchange.fetch_balance()
        usdt = float(balance.get('USDT', {}).get('total', 0))
        return usdt

    def get_instructions(self, exchange_name: str) -> str:
        """获取接入指引"""
        url = EXCHANGE_API_URLS.get(exchange_name, "")
        if exchange_name == "binance":
            return (
                f"1. 扫描QR Code或访问: {url}\n"
                "2. 在币安App内创建新的API Key\n"
                "3. 权限勾选: 现货交易 + 合约交易 + 只读\n"
                "4. 不要勾选: 提现权限\n"
                "5. 创建后将 API Key 和 Secret 粘贴到下方"
            )
        elif exchange_name == "okx":
            return (
                f"1. 扫描QR Code或访问: {url}\n"
                "2. 在欧易App内创建新的API Key\n"
                "3. 权限勾选: 交易 + 只读\n"
                "4. 不要勾选: 提现权限\n"
                "5. 创建后将 API Key、Secret 和 Passphrase 粘贴到下方"
            )
        return "不支持的交易所"


# 全局实例
qr_auth_manager = QRAuthManager()
