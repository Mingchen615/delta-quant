"""
4. 订单流 Agent
分析订单簿，计算买卖压力
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import OrderFlowEvent
from exchange.binance_client import binance_client
from data.market_data import market_data_manager
from config import ORDERBOOK_DEPTH, ORDERBOOK_IMBALANCE_THRESHOLD


class OrderFlowAgent(BaseAgent):
    """
    订单流分析Agent
    - 从盘口深度计算买卖压力
    - 订单簿不平衡度
    - 大额挂单检测
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="订单流",
            log_prefix="[订单流]",
            interval=3,  # 3秒
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)
        
        self._symbols = ["BTC/USDT", "ETH/USDT"]
        self._orderflow_cache: Dict[str, OrderFlowEvent] = {}
        
    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("signal.*", self._on_signal)
        
    async def _on_signal(self, event):
        """收到信号时增加监控频率"""
        if hasattr(event, "symbol"):
            if event.symbol not in self._symbols:
                self._symbols.append(event.symbol)
                self.logger.info(f"增加监控: {event.symbol}")
                
    async def execute(self):
        """分析订单流"""
        try:
            for symbol in self._symbols:
                orderbook = await binance_client.fetch_order_book(symbol, ORDERBOOK_DEPTH)
                
                if not orderbook:
                    continue
                    
                # 计算不平衡度
                imbalance = self._calculate_imbalance(orderbook)
                
                # 检测大单
                large_bids, large_asks = self._detect_large_orders(orderbook)
                
                # 计算买卖压力
                bid_vol = sum(qty for price, qty in orderbook["bids"][:ORDERBOOK_DEPTH])
                ask_vol = sum(qty for price, qty in orderbook["asks"][:ORDERBOOK_DEPTH])
                
                # 创建事件
                event = OrderFlowEvent(
                    symbol=symbol,
                    imbalance=imbalance,
                    bid_volume=bid_vol,
                    ask_volume=ask_vol,
                    large_bids=large_bids,
                    large_asks=large_asks,
                    timestamp=datetime.now(),
                )
                
                # 缓存
                self._orderflow_cache[symbol] = event
                
                # 发布
                await self.publish(f"orderflow.{symbol}", event)
                
                # 日志（仅显示不平衡度高的）
                if abs(imbalance) > ORDERBOOK_IMBALANCE_THRESHOLD:
                    direction = "买入" if imbalance > 0 else "卖出"
                    self.logger.info(
                        f"订单流 {symbol}: {direction}压力 "
                        f"(不平衡度: {imbalance:.2%})"
                    )
                    
        except Exception as e:
            self.logger.error(f"订单流分析出错: {e}")
            
    def _calculate_imbalance(self, orderbook: Dict) -> float:
        """
        计算订单簿不平衡度
        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        返回: -1(全是卖) ~ 1(全是买)
        """
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        
        if not bids or not asks:
            return 0
            
        bid_vol = sum(qty for _, qty in bids[:ORDERBOOK_DEPTH])
        ask_vol = sum(qty for _, qty in asks[:ORDERBOOK_DEPTH])
        
        total = bid_vol + ask_vol
        if total == 0:
            return 0
            
        return (bid_vol - ask_vol) / total
        
    def _detect_large_orders(
        self,
        orderbook: Dict,
        threshold_multiplier: float = 5
    ) -> tuple:
        """
        检测大额挂单
        返回: (大买单, 大卖单)
        """
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        
        if not bids or not asks:
            return [], []
            
        # 计算平均单量
        avg_bid_qty = sum(qty for _, qty in bids[:10]) / len(bids[:10]) if bids else 0
        avg_ask_qty = sum(qty for _, qty in asks[:10]) / len(asks[:10]) if asks else 0
        
        threshold = max(avg_bid_qty, avg_ask_qty) * threshold_multiplier
        
        large_bids = [(price, qty) for price, qty in bids if qty > threshold]
        large_asks = [(price, qty) for price, qty in asks if qty > threshold]
        
        return large_bids[:5], large_asks[:5]
        
    def get_imbalance(self, symbol: str) -> Optional[float]:
        """获取订单簿不平衡度"""
        event = self._orderflow_cache.get(symbol)
        return event.imbalance if event else None
        
    def get_short_term_bias(self, symbol: str, window: int = 5) -> str:
        """
        获取短期偏向
        基于最近window次订单流
        """
        # 这里简化处理，实际应该记录历史
        imbalance = self.get_imbalance(symbol)
        
        if imbalance is None:
            return "neutral"
            
        if imbalance > 0.2:
            return "bullish"
        elif imbalance < -0.2:
            return "bearish"
        else:
            return "neutral"
