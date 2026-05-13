"""
2. 鲸鱼地址监控 Agent
监控大额成交（>50万USDT）
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import WhaleActivityEvent
from exchange.binance_client import binance_client
from config import WHALE_THRESHOLD_USDT


class WhaleAgent(BaseAgent):
    """
    鲸鱼活动监控Agent
    - 从aggTrades流获取大额成交
    - 标记方向（买入/卖出）
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
        
    async def execute(self):
        """检查大额成交"""
        try:
            # 获取Top币种的聚合成交
            symbols = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
            
            for symbol in symbols:
                trades = await binance_client.fetch_trades(symbol, limit=20)
                
                if not trades:
                    continue
                    
                # 检查是否有大额成交
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
                        
                        # 添加到历史
                        self._add_whale_activity(whale_event)
                        
                        # 发布事件
                        await self.publish("whale.activity", whale_event)
                        
                        self.logger.info(
                            f"🐋 鲸鱼活动: {symbol} {whale_event.direction.upper()} "
                            f"${whale_event.quote_quantity/1e6:.2f}M "
                            f"(@${whale_event.price:.2f})"
                        )
                        
        except Exception as e:
            self.logger.error(f"鲸鱼监控出错: {e}")
            
    def _add_whale_activity(self, event: WhaleActivityEvent):
        """添加鲸鱼活动到历史"""
        self._recent_trades.append(event)
        
        # 保持历史长度
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
