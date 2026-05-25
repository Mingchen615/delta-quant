"""
跨平台套利Agent
监控币安-OKX价差，发现套利机会
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import ArbitrageEvent
from config import ARBITRAGE_THRESHOLD, ARBITRAGE_INTERVAL, BINANCE_FEE_RATE, OKX_FEE_RATE


class ArbitrageAgent(BaseAgent):
    """
    跨平台套利Agent

    功能:
    - 每秒对比币安vs OKX同币对价差
    - 价差 > 阈值（手续费+滑点）触发套利事件
    - 记录套利统计
    """

    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="跨平台套利",
            log_prefix="[套利]",
            interval=ARBITRAGE_INTERVAL,
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)

        self._exchange_router = None
        self._symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        self._opportunities: List[ArbitrageEvent] = []
        self._total_opportunities = 0
        self._total_profit = 0.0

    def set_router(self, router):
        """设置交易所路由器"""
        self._exchange_router = router

    async def execute(self):
        """检查套利机会"""
        if not self._exchange_router:
            return

        available = self._exchange_router.available_exchanges
        if len(available) < 2:
            return

        for symbol in self._symbols:
            try:
                await self._check_arbitrage(symbol)
            except Exception as e:
                self.logger.debug(f"套利检查 {symbol} 出错: {e}")

    async def _check_arbitrage(self, symbol: str):
        """检查单个币对的套利机会"""
        exchanges = self._exchange_router.exchanges

        # 获取双平台价格
        prices = {}
        for name, exchange in exchanges.items():
            if not exchange.is_connected:
                continue
            try:
                ticker = await exchange.get_ticker(symbol)
                prices[name] = ticker
            except Exception:
                continue

        if len(prices) < 2:
            return

        # 计算价差
        names = list(prices.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                name_a, name_b = names[i], names[j]
                ticker_a, ticker_b = prices[name_a], prices[name_b]

                # 计算双向价差
                # A买B卖: B.bid - A.ask
                spread_a_buy_b_sell = ticker_b.bid - ticker_a.ask
                # B买A卖: A.bid - B.ask
                spread_b_buy_a_sell = ticker_a.bid - ticker_b.ask

                # 考虑手续费后的净利润
                fee_cost = (BINANCE_FEE_RATE + OKX_FEE_RATE) * ticker_a.last

                # A买B卖套利
                net_profit_a = spread_a_buy_b_sell - fee_cost
                if net_profit_a > ARBITRAGE_THRESHOLD * ticker_a.last:
                    event = ArbitrageEvent(
                        symbol=symbol,
                        buy_exchange=name_a,
                        sell_exchange=name_b,
                        buy_price=ticker_a.ask,
                        sell_price=ticker_b.bid,
                        spread=spread_a_buy_b_sell,
                        spread_pct=spread_a_buy_b_sell / ticker_a.last,
                        net_profit_pct=net_profit_a / ticker_a.last,
                        timestamp=datetime.now(),
                    )
                    await self._publish_opportunity(event)

                # B买A卖套利
                net_profit_b = spread_b_buy_a_sell - fee_cost
                if net_profit_b > ARBITRAGE_THRESHOLD * ticker_a.last:
                    event = ArbitrageEvent(
                        symbol=symbol,
                        buy_exchange=name_b,
                        sell_exchange=name_a,
                        buy_price=ticker_b.ask,
                        sell_price=ticker_a.bid,
                        spread=spread_b_buy_a_sell,
                        spread_pct=spread_b_buy_a_sell / ticker_a.last,
                        net_profit_pct=net_profit_b / ticker_a.last,
                        timestamp=datetime.now(),
                    )
                    await self._publish_opportunity(event)

    async def _publish_opportunity(self, event: ArbitrageEvent):
        """发布套利机会"""
        self._opportunities.append(event)
        self._total_opportunities += 1
        self._total_profit += event.net_profit_pct

        # 发布事件
        await self.publish("arbitrage", event)

        self.logger.info(
            f"套利机会: {event.symbol} "
            f"买{event.buy_exchange}@${event.buy_price:.2f} "
            f"卖{event.sell_exchange}@${event.sell_price:.2f} "
            f"价差: {event.spread_pct:.4%} "
            f"净利: {event.net_profit_pct:.4%}"
        )

        # 保持历史长度
        if len(self._opportunities) > 100:
            self._opportunities = self._opportunities[-100:]

    def get_stats(self) -> Dict:
        """获取套利统计"""
        return {
            "total_opportunities": self._total_opportunities,
            "total_profit_pct": self._total_profit,
            "recent_opportunities": len(self._opportunities),
        }
