"""
10. 风控组合优化 Agent
多仓位管理，相关性检查
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Set

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import RiskCheckResult, TradeProposal
from config import MAX_POSITIONS, CORRELATION_THRESHOLD


class PortfolioAgent(BaseAgent):
    """
    组合优化Agent
    
    检查项:
    - 最多同时2个仓位
    - 相关性检查（避免同方向高相关持仓）
    - 账户热度监控
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="组合优化",
            log_prefix="[组合优化]",
            interval=0,  # 事件触发
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)
        
        self._current_positions: Set[str] = set()
        self._position_directions: Dict[str, str] = {}
        self._position_correlations: Dict[str, float] = {}
        
    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("risk_check", self._on_risk_check)
        await self.subscribe("position.opened", self._on_position_opened)
        await self.subscribe("position.closed", self._on_position_closed)
        
    async def _on_risk_check(self, result: RiskCheckResult):
        """接收风控检查结果"""
        if not result.approved:
            return
            
        # 组合检查
        approved = await self._check_portfolio(result)
        
        if approved:
            await self.publish("portfolio_check", result)
            self.logger.info(f"✅ 组合通过: {result.symbol}")
        else:
            self.logger.warning(f"❌ 组合拒绝: {result.symbol} - 仓位数超限或相关性过高")
            
    async def _on_position_opened(self, event):
        """持仓开仓"""
        if hasattr(event, "symbol"):
            self._current_positions.add(event.symbol)
            if hasattr(event, "direction"):
                self._position_directions[event.symbol] = event.direction
                
    async def _on_position_closed(self, event):
        """持仓平仓"""
        if hasattr(event, "symbol"):
            self._current_positions.discard(event.symbol)
            self._position_directions.pop(event.symbol, None)
            self._position_correlations.pop(event.symbol, None)
            
    async def _check_portfolio(self, result: RiskCheckResult) -> bool:
        """执行组合检查"""
        symbol = result.symbol
        direction = result.proposal.direction
        
        # 1. 检查仓位数量
        if len(self._current_positions) >= MAX_POSITIONS:
            self.logger.warning(f"仓位数已达上限({MAX_POSITIONS})")
            return False
            
        # 2. 检查同向高相关持仓
        if direction in ["long", "short"]:
            for pos_symbol, pos_dir in self._position_directions.items():
                if pos_dir == direction:
                    # 检查相关性（简化：同板块或同向动量）
                    if self._is_highly_correlated(symbol, pos_symbol):
                        self.logger.warning(
                            f"{symbol} 与 {pos_symbol} 相关性过高且同向"
                        )
                        return False
                        
        # 3. 账户热度检查（简化）
        # 持仓越多，热度越高，新开仓越谨慎
        if len(self._current_positions) >= MAX_POSITIONS - 1:
            if result.proposal.signal_score < 70:
                self.logger.info(f"账户热度高，低分信号跳过")
                return False
                
        return True
        
    def _is_highly_correlated(self, symbol1: str, symbol2: str) -> bool:
        """
        检查两个币种是否高度相关
        简化实现：同板块或BTC/ETH高度相关
        """
        # 同板块币种
        def get_sector(symbol: str) -> str:
            s = symbol.replace("/USDT", "")
            if s in ["BTC", "ETH"]:
                return "core"
            elif s in ["BNB", "SOL", "AVAX", "ADA"]:
                return "layer1"
            elif s in ["UNI", "AAVE", "MKR"]:
                return "defi"
            else:
                return "other"
                
        return get_sector(symbol1) == get_sector(symbol2)
        
    def get_portfolio_status(self) -> Dict:
        """获取组合状态"""
        return {
            "positions": list(self._current_positions),
            "position_count": len(self._current_positions),
            "max_positions": MAX_POSITIONS,
            "utilization": len(self._current_positions) / MAX_POSITIONS,
            "directions": self._position_directions.copy(),
        }

    async def execute(self):
        """
        执行Agent逻辑 - 事件驱动型，execute为空实现
        实际逻辑通过订阅的事件触发
        """
        # PortfolioAgent是事件驱动型，等待下一个执行周期
        await asyncio.sleep(self.config.interval)
