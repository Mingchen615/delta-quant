"""
欧易(OKX)交易所实现
基于ccxt的异步接口，支持永续合约
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
    OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE,
    PROXY_URL,
)


class OKXExchange(BaseExchange):
    """欧易交易所实现 - 基于ccxt"""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
    ):
        super().__init__()
        self._api_key = api_key or OKX_API_KEY
        self._api_secret = api_secret or OKX_API_SECRET
        self._passphrase = passphrase or OKX_PASSPHRASE
        self._exchange = None
        self._rate_limit = asyncio.Semaphore(10)

    @property
    def exchange_name(self) -> str:
        return "okx"

    @property
    def supported_symbols(self) -> List[str]:
        return [
            "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
            "XRP/USDT:USDT", "DOGE/USDT:USDT", "ADA/USDT:USDT",
            "AVAX/USDT:USDT", "DOT/USDT:USDT", "LINK/USDT:USDT",
        ]

    def _get_exchange(self):
        """懒加载ccxt实例 - 不带API Key（Key在load_markets后设置）"""
        if self._exchange is None:
            import ccxt.async_support as ccxt

            # 不带API Key创建实例，避免load_markets访问认证端点
            config = {
                "enableRateLimit": True,
                "options": {
                    "defaultType": "swap",
                },
            }

            # OKX从大陆访问必须走代理
            config["aiohttp_proxy"] = PROXY_URL
            config["proxies"] = {
                "http": PROXY_URL,
                "https": PROXY_URL,
            }

            self._exchange = ccxt.okx(config)
        return self._exchange

    def _set_api_keys(self):
        """设置API Key到exchange实例（load_markets后调用）"""
        if self._exchange and self._api_key:
            self._exchange.apiKey = self._api_key
            self._exchange.secret = self._api_secret
            self._exchange.password = self._passphrase

    async def _get_exchange_async(self):
        """获取ccxt实例，先加载市场再设置Key"""
        if self._exchange is None:
            ex = self._get_exchange()
            await ex.load_markets()
            logger.debug("[OKX] 市场数据加载完成")
            self._set_api_keys()
            return ex
        return self._exchange

    async def _call(self, func, *args, **kwargs):
        """限速调用"""
        async with self._rate_limit:
            return await func(*args, **kwargs)

    # --- 连接管理 ---

    async def connect(self) -> bool:
        try:
            await self._get_exchange_async()
            self._connected = True
            logger.info("[OKX] 连接成功")
            return True
        except Exception as e:
            logger.error(f"[OKX] 连接失败: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
        self._connected = False
        logger.info("[OKX] 已断开连接")

    async def check_connection(self) -> bool:
        try:
            ex = await self._get_exchange_async()
            await self._call(ex.fetch_time)
            return True
        except Exception:
            return False

    # --- 账户 ---

    async def get_balance(self) -> AccountBalance:
        ex = await self._get_exchange_async()
        balance = await self._call(ex.fetch_balance)
        usdt = balance.get("USDT", {})
        return AccountBalance(
            total=float(usdt.get("total", 0)),
            free=float(usdt.get("free", 0)),
            used=float(usdt.get("used", 0)),
            unrealized_pnl=float(balance.get("info", {}).get("totalUnrealizedProfit", 0)),
        )

    async def get_positions(self) -> List[Position]:
        ex = await self._get_exchange_async()
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
        ex = await self._get_exchange_async()
        try:
            t = await self._call(ex.fetch_ticker, symbol)
        except Exception as e:
            logger.error(f"[OKX] fetch_ticker失败 {symbol}: {e}")
            raise
        def safe_float(v, default=0.0):
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        return Ticker(
            symbol=symbol,
            last=safe_float(t.get("last")),
            bid=safe_float(t.get("bid")),
            ask=safe_float(t.get("ask")),
            high=safe_float(t.get("high")),
            low=safe_float(t.get("low")),
            volume=safe_float(t.get("baseVolume")),
            quote_volume=safe_float(t.get("quoteVolume")),
            timestamp=datetime.now(),
        )

    async def get_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        ex = await self._get_exchange_async()
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
        ex = await self._get_exchange_async()
        try:
            ohlcv = await self._call(ex.fetch_ohlcv, symbol, timeframe, limit=limit)
        except Exception as e:
            logger.error(f"[OKX] fetch_ohlcv失败 {symbol} {timeframe}: {e}")
            raise
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
        ex = await self._get_exchange_async()

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
            exchange="okx",
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
            ex = await self._get_exchange_async()
            await self._call(ex.cancel_order, order_id, symbol)
            return True
        except Exception as e:
            logger.error(f"[OKX] 撤单失败: {e}")
            return False

    async def get_order(self, order_id: str, symbol: str) -> Order:
        ex = await self._get_exchange_async()
        o = await self._call(ex.fetch_order, order_id, symbol)
        return Order(
            order_id=str(o["id"]),
            exchange="okx",
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
            ex = await self._get_exchange_async()
            await self._call(ex.set_leverage, leverage, symbol, params={
                "mgnMode": "cross",
            })
            return True
        except Exception as e:
            logger.warning(f"[OKX] 设置杠杆失败: {e}")
            return False

    async def set_margin_mode(self, symbol: str, mode: str) -> bool:
        try:
            ex = await self._get_exchange_async()
            await self._call(ex.set_margin_mode, mode, symbol)
            return True
        except Exception as e:
            logger.warning(f"[OKX] 设置保证金模式失败: {e}")
            return False

    # --- 扫码接入 ---

    def generate_qr_url(self) -> str:
        return "https://www.okx.com/account/my-api"

    async def verify_credentials(self) -> bool:
        try:
            await self.get_balance()
            return True
        except Exception as e:
            logger.error(f"[OKX] 验证失败: {e}")
            return False
