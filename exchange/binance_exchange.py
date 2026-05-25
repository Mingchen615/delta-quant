"""
币安交易所实现
基于ccxt的异步接口，支持合约交易
"""

import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

from loguru import logger

from exchange.base_exchange import (
    BaseExchange, Ticker, OrderBook, Kline,
    AccountBalance, Position, Order, OrderParams,
)
from config import (
    BINANCE_API_KEY, BINANCE_API_SECRET,
    USE_PROXY, PROXY_URL, LIVE_TRADE,
)


class BinanceExchange(BaseExchange):
    """币安交易所实现 - 基于ccxt"""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
    ):
        super().__init__()
        self._api_key = api_key or BINANCE_API_KEY
        self._api_secret = api_secret or BINANCE_API_SECRET
        self._exchange = None
        self._rate_limit = asyncio.Semaphore(10)
        self._force_live = False  # 强制使用主网（验证凭证时）

    @property
    def exchange_name(self) -> str:
        return "binance"

    @property
    def supported_symbols(self) -> List[str]:
        return [
            "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT",
            "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT",
            "DOT/USDT", "LINK/USDT", "MATIC/USDT", "UNI/USDT",
        ]

    def _get_exchange(self):
        """懒加载ccxt实例"""
        if self._exchange is None:
            import ccxt.async_support as ccxt

            config = {
                "apiKey": self._api_key,
                "secret": self._api_secret,
                "enableRateLimit": True,
            }

            if USE_PROXY:
                config["aiohttp_proxy"] = PROXY_URL
                config["proxies"] = {
                    "http": PROXY_URL,
                    "https": PROXY_URL,
                }

            if LIVE_TRADE or self._force_live:
                config["options"] = {
                    "defaultType": "swap",
                    "fetchMarkets": ["spot"],  # 只加载spot市场避免margin端点被墙
                }
                # 国内使用 binance.me 域名直连
                config["urls"] = {
                    "api": {
                        "public": "https://api.binance.me/api/v3",
                        "private": "https://api.binance.me/api/v3",
                        "v1": "https://api.binance.me/api/v1",
                        "sapi": "https://api.binance.me/sapi/v1",
                        "sapiV2": "https://api.binance.me/sapi/v2",
                        "sapiV3": "https://api.binance.me/sapi/v3",
                        "sapiV4": "https://api.binance.me/sapi/v4",
                        "fapiPublic": "https://fapi.binance.me/fapi/v1",
                        "fapiPublicDelivery": "https://dapi.binance.me/dapi/v1",
                        "fapiPrivate": "https://fapi.binance.me/fapi/v1",
                        "fapiPrivateV2": "https://fapi.binance.me/fapi/v2",
                        "dapiPublic": "https://dapi.binance.me/dapi/v1",
                        "dapiPrivate": "https://dapi.binance.me/dapi/v1",
                    }
                }
            else:
                config["testnet"] = True
                config["options"] = {
                    "defaultType": "spot",
                    "fetchMarkets": ["spot"],
                }

            self._exchange = ccxt.binance(config)
        return self._exchange

    async def _call(self, func, *args, **kwargs):
        """限速调用"""
        async with self._rate_limit:
            return await func(*args, **kwargs)

    # --- 连接管理 ---

    async def connect(self) -> bool:
        try:
            ex = self._get_exchange()
            await self._call(ex.load_markets)
            self._connected = True
            logger.info("[币安] 连接成功")
            return True
        except Exception as e:
            logger.error(f"[币安] 连接失败: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
        self._connected = False
        logger.info("[币安] 已断开连接")

    async def check_connection(self) -> bool:
        try:
            ex = self._get_exchange()
            await self._call(ex.fetch_time)
            return True
        except Exception:
            return False

    # --- 账户 ---

    async def get_balance(self) -> AccountBalance:
        ex = self._get_exchange()
        balance = await self._call(ex.fetch_balance)
        usdt = balance.get("USDT", {})
        return AccountBalance(
            total=float(usdt.get("total", 0)),
            free=float(usdt.get("free", 0)),
            used=float(usdt.get("used", 0)),
            unrealized_pnl=float(balance.get("info", {}).get("totalUnrealizedProfit", 0)),
        )

    async def get_positions(self) -> List[Position]:
        ex = self._get_exchange()
        positions = await self._call(ex.fetch_positions)
        result = []
        for p in positions:
            contracts = abs(float(p.get("contracts", 0)))
            if contracts == 0:
                continue
            result.append(Position(
                symbol=p["symbol"],
                side=p.get("side", "long"),
                contracts=contracts,
                entry_price=float(p.get("entryPrice", 0)),
                mark_price=float(p.get("markPrice", 0)),
                unrealized_pnl=float(p.get("unrealizedPnl", 0)),
                leverage=int(p.get("leverage", 20)),
                margin_mode=p.get("marginMode", "cross"),
                liquidation_price=(
                    float(p["liquidationPrice"]) if p.get("liquidationPrice") else None
                ),
                timestamp=datetime.now(),
            ))
        return result

    # --- 行情 ---

    async def get_ticker(self, symbol: str) -> Ticker:
        ex = self._get_exchange()
        t = await self._call(ex.fetch_ticker, symbol)
        return Ticker(
            symbol=symbol,
            last=float(t["last"]),
            bid=float(t.get("bid", 0)),
            ask=float(t.get("ask", 0)),
            high=float(t.get("high", 0)),
            low=float(t.get("low", 0)),
            volume=float(t.get("baseVolume", 0)),
            quote_volume=float(t.get("quoteVolume", 0)),
            timestamp=datetime.now(),
        )

    async def get_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        ex = self._get_exchange()
        ob = await self._call(ex.fetch_order_book, symbol, limit)
        return OrderBook(
            symbol=symbol,
            bids=[(float(b[0]), float(b[1])) for b in ob.get("bids", [])],
            asks=[(float(a[0]), float(a[1])) for a in ob.get("asks", [])],
            timestamp=datetime.now(),
        )

    async def get_klines(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> List[Kline]:
        ex = self._get_exchange()
        ohlcv = await self._call(ex.fetch_ohlcv, symbol, timeframe, limit=limit)
        return [
            Kline(
                symbol=symbol,
                timestamp=datetime.fromtimestamp(c[0] / 1000),
                open=float(c[1]),
                high=float(c[2]),
                low=float(c[3]),
                close=float(c[4]),
                volume=float(c[5]),
                quote_volume=0,
                timeframe=timeframe,
            )
            for c in ohlcv
        ]

    # --- 交易 ---

    async def create_order(self, params: OrderParams) -> Order:
        ex = self._get_exchange()

        # 设置杠杆
        await self.set_leverage(params.symbol, params.leverage)
        # 设置保证金模式
        await self.set_margin_mode(params.symbol, params.margin_mode)

        order = await self._call(
            ex.create_order,
            symbol=params.symbol,
            type=params.order_type,
            side=params.side,
            amount=params.amount,
            price=params.price,
        )

        return Order(
            order_id=str(order["id"]),
            exchange="binance",
            symbol=params.symbol,
            side=order["side"],
            order_type=order.get("type", params.order_type),
            amount=float(order.get("amount", params.amount)),
            price=float(order.get("price", 0) or 0),
            status=order.get("status", "open"),
            filled=float(order.get("filled", 0)),
            average=float(order.get("average", 0) or 0),
            fee=float(order.get("fee", {}).get("cost", 0)),
            timestamp=datetime.now(),
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        try:
            ex = self._get_exchange()
            await self._call(ex.cancel_order, order_id, symbol)
            return True
        except Exception as e:
            logger.error(f"[币安] 撤单失败: {e}")
            return False

    async def get_order(self, order_id: str, symbol: str) -> Order:
        ex = self._get_exchange()
        o = await self._call(ex.fetch_order, order_id, symbol)
        return Order(
            order_id=str(o["id"]),
            exchange="binance",
            symbol=symbol,
            side=o["side"],
            order_type=o.get("type", "market"),
            amount=float(o.get("amount", 0)),
            price=float(o.get("price", 0) or 0),
            status=o.get("status", "open"),
            filled=float(o.get("filled", 0)),
            average=float(o.get("average", 0) or 0),
            fee=float(o.get("fee", {}).get("cost", 0)),
            timestamp=datetime.now(),
        )

    # --- 杠杆 ---

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            ex = self._get_exchange()
            await self._call(ex.set_leverage, leverage, symbol)
            return True
        except Exception as e:
            logger.warning(f"[币安] 设置杠杆失败: {e}")
            return False

    async def set_margin_mode(self, symbol: str, mode: str) -> bool:
        try:
            ex = self._get_exchange()
            await self._call(ex.set_margin_mode, mode, symbol)
            return True
        except Exception as e:
            logger.warning(f"[币安] 设置保证金模式失败: {e}")
            return False

    # --- 扫码接入 ---

    def generate_qr_url(self) -> str:
        return "https://www.binance.com/zh-CN/my/settings/api-management"

    async def verify_credentials(self) -> bool:
        try:
            await self.get_balance()
            return True
        except Exception as e:
            logger.error(f"[币安] 验证失败: {e}")
            return False
