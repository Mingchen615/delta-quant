"""
币安API封装
基于ccxt的异步接口
支持testnet
"""

import asyncio
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from loguru import logger

from config import BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_TESTNET


class BinanceClient:
    """
    币安API客户端
    封装ccxt，提供异步交易接口
    """

    def __init__(
        self,
        api_key: str = BINANCE_API_KEY,
        api_secret: str = BINANCE_API_SECRET,
        testnet: bool = BINANCE_TESTNET,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.exchange = None  # 延迟初始化

        # 限速
        self._rate_limit = asyncio.Semaphore(10)

        logger.info(
            f"[币安客户端] 初始化完成, "
            f"API Key: {'已设置' if api_key else '未设置'}, "
            f"Testnet: {testnet}"
        )

    def _get_exchange(self):
        """懒加载获取ccxt exchange实例"""
        if self.exchange is None:
            import ccxt.async_support as ccxt

            config = {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},  # 永续合约
            }

            if self.testnet:
                config["testnet"] = True
                config["urls"] = {
                    "api": "https://testnet.binance.vision/api",
                    "ws": "wss://testnet.binance.vision/ws",
                }

            self.exchange = ccxt.binance(config)
        return self.exchange

    async def _rate_limited(self, func, *args, **kwargs):
        """限速包装"""
        async with self._rate_limit:
            return await asyncio.to_thread(func, *args, **kwargs)

    async def fetch_markets(self) -> List[Dict]:
        """获取交易对信息"""
        return await self._rate_limited(self._get_exchange().fetch_markets)

    async def fetch_ticker(self, symbol: str) -> Dict:
        """获取单个交易对行情"""
        return await self._rate_limited(self._get_exchange().fetch_ticker, symbol)

    async def fetch_tickers(self, symbols: Optional[List[str]] = None) -> Dict[str, Dict]:
        """获取多个交易对行情"""
        return await self._rate_limited(self._get_exchange().fetch_tickers, symbols)

    async def fetch_klines(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        since: Optional[int] = None,
    ) -> List[List[Any]]:
        """
        获取K线数据

        Returns:
            [[timestamp, open, high, low, close, volume], ...]
        """
        return await self._rate_limited(
            self._get_exchange().fetch_ohlcv,
            symbol, timeframe, since, limit
        )

    async def fetch_order_book(
        self,
        symbol: str,
        limit: int = 20
    ) -> Dict:
        """获取订单簿"""
        return await self._rate_limited(self._get_exchange().fetch_order_book, symbol, limit)

    async def fetch_agg_trades(
        self,
        symbol: str,
        limit: int = 50
    ) -> List[Dict]:
        """获取聚合成交"""
        return await self._rate_limited(self._get_exchange().fetch_agg_trades, symbol, None, limit)

    async def fetch_balance(self) -> Dict:
        """获取账户余额"""
        if not self.api_key:
            raise ValueError("API Key未设置，无法获取余额")
        return await self._rate_limited(self._get_exchange().fetch_balance)

    async def fetch_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """获取持仓"""
        if not self.api_key:
            raise ValueError("API Key未设置，无法获取持仓")
        positions = await self._rate_limited(self._get_exchange().fetch_positions)

        if symbol:
            positions = [p for p in positions if p.get("symbol") == symbol]

        return positions

    async def create_order(
        self,
        symbol: str,
        side: str,  # "buy" or "sell"
        order_type: str,  # "market", "limit"
        quantity: float,
        price: Optional[float] = None,
        leverage: int = 20,
    ) -> Dict:
        """
        创建订单

        Args:
            symbol: 交易对，如 "BTC/USDT"
            side: 买卖方向
            order_type: 订单类型
            quantity: 数量
            price: 价格（限价单）
            leverage: 杠杆

        Returns:
            订单信息
        """
        if not self.api_key:
            raise ValueError("API Key未设置，无法下单")

        # 设置杠杆
        await self.set_leverage(symbol, leverage)

        params = {}
        if order_type == "limit" and price:
            params["price"] = price

        return await self._rate_limited(
            self._get_exchange().create_order,
            symbol, order_type, side, quantity, price, params
        )

    async def cancel_order(self, order_id: str, symbol: str) -> Dict:
        """取消订单"""
        if not self.api_key:
            raise ValueError("API Key未设置，无法取消订单")
        return await self._rate_limited(self._get_exchange().cancel_order, order_id, symbol)

    async def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """设置杠杆"""
        if not self.api_key:
            logger.warning("[币安客户端] API Key未设置，跳过设置杠杆")
            return {}

        return await self._rate_limited(
            self._get_exchange().set_leverage,
            leverage, symbol
        )

    async def fetch_funding_rate(self, symbol: str) -> Dict:
        """获取资金费率"""
        return await self._rate_limited(self._get_exchange().fetch_funding_rate, symbol)

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """获取未完成订单"""
        if not self.api_key:
            return []
        return await self._rate_limited(self._get_exchange().fetch_open_orders, symbol)

    def get_symbol_format(self, base: str, quote: str = "USDT") -> str:
        """获取标准交易对格式"""
        return f"{base}/{quote}"

    def parse_symbol(self, symbol: str) -> Tuple[str, str]:
        """解析交易对"""
        # 统一格式：BTC/USDT -> (BTC, USDT)
        parts = symbol.replace("/", "").upper()

        if parts.endswith("USDT"):
            base = parts[:-4]
            quote = "USDT"
        elif parts.endswith("USD"):
            base = parts[:-3]
            quote = "USD"
        elif parts.endswith("BTC"):
            base = parts[:-3]
            quote = "BTC"
        else:
            base = parts
            quote = "USDT"

        return base, quote


# 全局客户端实例 - 延迟加载，不在模块导入时初始化exchange
binance_client = BinanceClient()
