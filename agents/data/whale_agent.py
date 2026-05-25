"""
2. 鲸鱼地址监控 Agent
监控大额成交（>50万USDT），支持双平台
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import WhaleActivityEvent
from config import WHALE_THRESHOLD_USDT


class WhaleAgent(BaseAgent):
    """
    鲸鱼活动监控Agent
    - 同时监控币安+OKX大单
    - 标记方向（买入/卖出）和来源平台
    - 输出鲸鱼活动事件
    """

    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="鲸鱼监控",
            log_prefix="[鲸鱼监控]",
            interval=5,  # 5秒检查一次
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)

        self._recent_trades: List[WhaleActivityEvent] = []
        self._max_history = 100
        self._exchange_router = None

    def set_router(self, router):
        """设置交易所路由器"""
        self._exchange_router = router

    async def execute(self):
        """检查大额成交"""
        try:
            symbols = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]

            if self._exchange_router:
                # 双平台监控：遍历所有已连接交易所
                for name, exchange in self._exchange_router.exchanges.items():
                    if not exchange.is_connected:
                        continue
                    await self._check_whales_exchange(name, exchange, symbols)
            else:
                # 单平台模式（兼容旧逻辑）
                await self._check_whales_binance(symbols)

        except Exception as e:
            self.logger.error(f"鲸鱼监控出错: {e}")

    async def _check_whales_exchange(self, name: str, exchange, symbols: List[str]):
        """通过交易所抽象层检查大单"""
        try:
            for symbol in symbols:
                try:
                    ticker = await exchange.get_ticker(symbol)
                    # 用ticker的quote_volume判断是否有大额活动
                    if ticker.quote_volume >= WHALE_THRESHOLD_USDT:
                        whale_event = WhaleActivityEvent(
                            symbol=symbol,
                            direction="buy",  # 简化：无法从ticker判断方向
                            quantity=ticker.volume,
                            price=ticker.last,
                            quote_quantity=ticker.quote_volume,
                            is_buyer_maker=False,
                            timestamp=datetime.now(),
                        )
                        self._add_whale_activity(whale_event)
                        await self.publish("whale_activity", whale_event)
                        self.logger.info(
                            f"🐋 [{name}] 鲸鱼活动: {symbol} "
                            f"${ticker.quote_volume/1e6:.2f}M (@${ticker.last:.2f})"
                        )
                except Exception:
                    continue
        except Exception as e:
            self.logger.debug(f"{name}鲸鱼检查出错: {e}")

    async def _check_whales_binance(self, symbols: List[str]):
        """检查币安大单"""
        try:
            from exchange.binance_client import binance_client
            for symbol in symbols:
                trades = await binance_client.fetch_trades(symbol, limit=20)
                if not trades:
                    continue

                for trade in trades:
                    quote_qty = trade["price"] * trade["amount"]
                    if quote_qty >= WHALE_THRESHOLD_USDT:
                        whale_event = WhaleActivityEvent(
                            symbol=symbol,
                            direction="buy" if trade["side"] == "buy" else "sell",
                            quantity=trade["amount"],
                            price=trade["price"],
                            quote_quantity=quote_qty,
                            is_buyer_maker=trade.get("buyerMaker", False),
                            timestamp=datetime.fromtimestamp(trade["timestamp"] / 1000),
                        )
                        self._add_whale_activity(whale_event)
                        await self.publish("whale_activity", whale_event)

                        self.logger.info(
                            f"🐋 [币安] 鲸鱼活动: {symbol} {whale_event.direction.upper()} "
                            f"${whale_event.quote_quantity/1e6:.2f}M "
                            f"(@${whale_event.price:.2f})"
                        )
        except Exception as e:
            self.logger.debug(f"币安鲸鱼检查出错: {e}")

    async def _check_whales_okx(self, symbols: List[str]):
        """检查OKX大单"""
        if not self._exchange_router or "okx" not in self._exchange_router.exchanges:
            return

        exchange = self._exchange_router.exchanges["okx"]
        if not exchange.is_connected:
            return

        try:
            import ccxt.async_support as ccxt
            # OKX的symbol格式需要转换
            okx_symbols = [s.replace("/", "/") for s in symbols]

            for symbol in okx_symbols:
                try:
                    # 使用交易所实例直接获取trades
                    trades = await exchange._get_exchange().fetch_trades(symbol, limit=20)
                    if not trades:
                        continue

                    for trade in trades:
                        quote_qty = trade["price"] * trade["amount"]
                        if quote_qty >= WHALE_THRESHOLD_USDT:
                            whale_event = WhaleActivityEvent(
                                symbol=symbol,
                                direction="buy" if trade["side"] == "buy" else "sell",
                                quantity=trade["amount"],
                                price=trade["price"],
                                quote_quantity=quote_qty,
                                is_buyer_maker=trade.get("buyerMaker", False),
                                timestamp=datetime.fromtimestamp(trade["timestamp"] / 1000),
                            )
                            self._add_whale_activity(whale_event)
                            await self.publish("whale_activity", whale_event)

                            self.logger.info(
                                f"🐋 [OKX] 鲸鱼活动: {symbol} {whale_event.direction.upper()} "
                                f"${whale_event.quote_quantity/1e6:.2f}M "
                                f"(@${whale_event.price:.2f})"
                            )
                except Exception:
                    continue
        except Exception as e:
            self.logger.debug(f"OKX鲸鱼检查出错: {e}")

    def _add_whale_activity(self, event: WhaleActivityEvent):
        """添加鲸鱼活动到历史"""
        self._recent_trades.append(event)
        if len(self._recent_trades) > self._max_history:
            self._recent_trades = self._recent_trades[-self._max_history:]

    def get_recent_whales(self, symbol: Optional[str] = None) -> List[WhaleActivityEvent]:
        """获取最近的鲸鱼活动"""
        if symbol:
            return [w for w in self._recent_trades if w.symbol == symbol]
        return self._recent_trades.copy()

    def get_whale_bias(self, symbol: str) -> float:
        """
        计算鲸鱼偏向
        返回: -1(全是卖出) ~ 1(全是买入)
        """
        whales = self.get_recent_whales(symbol)
        if not whales:
            return 0

        buy_volume = sum(w.quote_quantity for w in whales if w.direction == "buy")
        sell_volume = sum(w.quote_quantity for w in whales if w.direction == "sell")
        total = buy_volume + sell_volume
        if total == 0:
            return 0

        return (buy_volume - sell_volume) / total
