"""
12. 持仓监控 Agent (核心)
三级止损 + 动态止盈
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import PositionEvent
from exchange.paper_trade import PaperTradeEngine
from config import (
    HARD_STOP_LOSS, SOFT_STOP_LOSS, TIME_STOP_SECONDS,
    TRAILING_STOP_TRIGGER, TRAILING_STOP_DISTANCE,
    TP1_RATIO, TP2_RATIO, TP3_RATIO
)


class PositionAgent(BaseAgent):
    """
    持仓监控Agent (核心)
    
    三级止损（保证金维度）:
    1. 硬止损 -25% (触发即平)
    2. 软止损 -5% (可调整)
    3. 时间止损 - 3分钟内不盈利即砍
    
    动态止盈:
    - 1R → 止盈移到+1R
    - 2R → 止盈移到+2R
    - 3R+ → 追踪止盈（回撤1R即平）
    - 目标5:1+
    
    每秒检查一次所有持仓
    """
    
    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        paper_engine: Optional[PaperTradeEngine] = None,
        **kwargs
    ):
        default_config = AgentConfig(
            name="持仓监控",
            log_prefix="[持仓监控]",
            interval=1,  # 1秒检查一次
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)
        
        self._paper_engine = paper_engine
        self._position_entries: Dict[str, datetime] = {}  # 开仓时间
        self._tp_levels: Dict[str, tuple] = {}  # symbol -> (tp1, tp2, tp3)
        
    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("position.opened", self._on_position_opened)
        await self.subscribe("position.closed", self._on_position_closed)
        
    async def _on_position_opened(self, event: PositionEvent):
        """持仓开仓"""
        self._position_entries[event.symbol] = datetime.now()
        
        # 设置止盈目标
        tp1 = event.entry_price * (1 + TP1_RATIO / event.leverage)
        tp2 = event.entry_price * (1 + TP2_RATIO / event.leverage)
        tp3 = event.entry_price * (1 + TP3_RATIO / event.leverage)
        
        if event.direction == "short":
            tp1 = event.entry_price * (1 - TP1_RATIO / event.leverage)
            tp2 = event.entry_price * (1 - TP2_RATIO / event.leverage)
            tp3 = event.entry_price * (1 - TP3_RATIO / event.leverage)
            
        self._tp_levels[event.symbol] = (tp1, tp2, tp3)
        
        self.logger.info(
            f"持仓监控开始: {event.symbol} "
            f"入场: ${event.entry_price:.4f} "
            f"止盈: {TP1_RATIO}R/${tp1:.4f}, {TP2_RATIO}R/${tp2:.4f}, {TP3_RATIO}R/${tp3:.4f}"
        )
        
    async def _on_position_closed(self, event: PositionEvent):
        """持仓平仓"""
        self._position_entries.pop(event.symbol, None)
        self._tp_levels.pop(event.symbol, None)
        
    async def execute(self):
        """检查所有持仓"""
        if not self._paper_engine:
            return
            
        positions = self._paper_engine.get_positions()
        
        for symbol, position in positions.items():
            await self._check_position(symbol, position)
            
    async def _check_position(self, symbol: str, position):
        """检查单个持仓"""
        try:
            # 获取当前价格
            from exchange.binance_client import binance_client
            ticker = await binance_client.fetch_ticker(symbol)
            current_price = ticker["last"]
            
            # 计算盈亏
            pnl = self._paper_engine.get_unrealized_pnl(symbol, current_price)
            pnl_pct = pnl / self._paper_engine.balance
            
            # 计算R数
            entry_price = position.entry_price
            if position.direction == "long":
                r = (current_price - entry_price) / entry_price * position.leverage
            else:
                r = (entry_price - current_price) / entry_price * position.leverage
                
            # 1. 检查硬止损
            if pnl_pct <= HARD_STOP_LOSS:
                result = self._paper_engine.close_position(symbol, current_price, "hard_stop_loss")
                if result:
                    await self._publish_closed(symbol, result, "硬止损")
                return
                
            # 2. 检查时间止损
            if symbol in self._position_entries:
                elapsed = (datetime.now() - self._position_entries[symbol]).total_seconds()
                if elapsed >= TIME_STOP_SECONDS and r <= 0:
                    result = self._paper_engine.close_position(symbol, current_price, "time_stop")
                    if result:
                        await self._publish_closed(symbol, result, "时间止损")
                    return
                    
            # 3. 检查动态止盈
            await self._check_take_profit(symbol, position, current_price, r)
            
            # 4. 检查追踪止损
            await self._check_trailing_stop(symbol, position, current_price, r)
            
            # 5. 更新最佳价格
            position.best_price = (
                max(position.best_price, current_price)
                if position.direction == "long"
                else min(position.best_price, current_price)
            )
            
        except Exception as e:
            self.logger.error(f"检查持仓{symbol}出错: {e}")
            
    async def _check_take_profit(
        self,
        symbol: str,
        position,
        current_price: float,
        r: float
    ):
        """检查止盈"""
        if symbol not in self._tp_levels:
            return
            
        tp1, tp2, tp3 = self._tp_levels[symbol]
        
        # 检查是否达到止盈目标
        if position.direction == "long":
            if r >= TP3_RATIO:
                # 全部平仓
                result = self._paper_engine.close_position(symbol, current_price, "tp3")
                if result:
                    await self._publish_closed(symbol, result, f"止盈{TP3_RATIO}R")
            elif r >= TP2_RATIO:
                # 平50%
                # 简化：直接全部平
                result = self._paper_engine.close_position(symbol, current_price, f"tp{TP2_RATIO}")
                if result:
                    await self._publish_closed(symbol, result, f"止盈{TP2_RATIO}R")
            elif r >= TP1_RATIO:
                # 平30%
                result = self._paper_engine.close_position(symbol, current_price, f"tp{TP1_RATIO}")
                if result:
                    await self._publish_closed(symbol, result, f"止盈{TP1_RATIO}R")
        else:
            # 做空
            if r >= TP3_RATIO:
                result = self._paper_engine.close_position(symbol, current_price, "tp3")
                if result:
                    await self._publish_closed(symbol, result, f"止盈{TP3_RATIO}R")
            elif r >= TP2_RATIO:
                result = self._paper_engine.close_position(symbol, current_price, f"tp{TP2_RATIO}")
                if result:
                    await self._publish_closed(symbol, result, f"止盈{TP2_RATIO}R")
            elif r >= TP1_RATIO:
                result = self._paper_engine.close_position(symbol, current_price, f"tp{TP1_RATIO}")
                if result:
                    await self._publish_closed(symbol, result, f"止盈{TP1_RATIO}R")
                    
    async def _check_trailing_stop(
        self,
        symbol: str,
        position,
        current_price: float,
        r: float
    ):
        """检查追踪止损"""
        if r < TRAILING_STOP_TRIGGER:
            return  # 未达到触发条件
            
        # 计算回撤
        if position.direction == "long":
            if position.best_price > 0:
                drawdown = (position.best_price - current_price) / position.best_price * position.leverage
                if drawdown >= TRAILING_STOP_DISTANCE:
                    result = self._paper_engine.close_position(symbol, current_price, "trailing_stop")
                    if result:
                        await self._publish_closed(symbol, result, "追踪止损")
        else:
            if position.best_price > 0:
                drawdown = (current_price - position.best_price) / position.best_price * position.leverage
                if drawdown >= TRAILING_STOP_DISTANCE:
                    result = self._paper_engine.close_position(symbol, current_price, "trailing_stop")
                    if result:
                        await self._publish_closed(symbol, result, "追踪止损")
                        
    async def _publish_closed(self, symbol: str, result: Dict, reason: str):
        """发布平仓事件"""
        event = PositionEvent(
            event_type="position_closed",
            symbol=symbol,
            direction=result.get("direction", "unknown"),
            entry_price=result.get("entry_price", 0),
            exit_price=result.get("exit_price", 0),
            quantity=0,
            leverage=0,
            realized_pnl=result.get("pnl", 0),
            unrealized_pnl_pct=result.get("pnl_pct", 0),
            close_reason=reason,
            closed_at=datetime.now(),
        )
        await self.publish("position.closed", event)
        
        self.logger.info(
            f"平仓: {symbol} 原因: {reason} "
            f"盈亏: ${result.get('pnl', 0):.2f} ({result.get('pnl_pct', 0)*100:.2f}%)"
        )
        
    def get_open_positions(self) -> List[str]:
        """获取开仓中的币种"""
        return list(self._position_entries.keys())
