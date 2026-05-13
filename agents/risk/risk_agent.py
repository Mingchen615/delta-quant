"""
9. 风控检查 Agent
单笔/日风险/回撤检查
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import TradeProposal, RiskCheckResult
from config import RISK_PER_TRADE, RISK_PER_DAY, MAX_DRAWDOWN


class RiskAgent(BaseAgent):
    """
    风控检查Agent
    
    检查项:
    - 单笔最大亏损3%
    - 日最大亏损5%
    - 最大回撤20%
    
    逐项检查，任一项不通过即拒绝
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="风控检查",
            log_prefix="[风控检查]",
            interval=0,  # 事件触发
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)
        
        self._daily_pnl = 0.0
        self._daily_reset = datetime.now()
        self._peak_balance = 10000.0  # 初始资金
        self._current_balance = 10000.0
        
    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("trade_proposal", self._on_proposal)
        await self.subscribe("position.closed", self._on_position_closed)
        
    async def _on_proposal(self, proposal: TradeProposal):
        """接收交易提案"""
        result = await self._check_risk(proposal)
        await self.publish("risk_check", result)
        
    async def _on_position_closed(self, event):
        """持仓平仓时更新统计"""
        if hasattr(event, "realized_pnl"):
            self._daily_pnl += event.realized_pnl
            self._current_balance += event.realized_pnl
            
            if self._current_balance > self._peak_balance:
                self._peak_balance = self._current_balance
                
    async def execute(self):
        """定期检查重置"""
        now = datetime.now()
        
        # 每天重置日盈亏
        if now.date() > self._daily_reset.date():
            self._daily_pnl = 0
            self._daily_reset = now
            self.logger.info("日盈亏统计已重置")
            
    async def _check_risk(self, proposal: TradeProposal) -> RiskCheckResult:
        """执行风控检查"""
        self.logger.debug(f"风控检查: {proposal.symbol}")
        
        reasons = []
        rejected_reasons = []
        approved = True
        
        # 1. 检查单笔风险
        single_risk = proposal.position_pct
        if single_risk > RISK_PER_TRADE:
            approved = False
            rejected_reasons.append(
                f"单笔风险超限: {single_risk*100:.2f}% > {RISK_PER_TRADE*100:.2f}%"
            )
        else:
            reasons.append(f"单笔风险: {single_risk*100:.2f}%")
            
        # 2. 检查日风险
        projected_daily_risk = self._daily_pnl - single_risk
        if projected_daily_risk < -RISK_PER_DAY:
            approved = False
            rejected_reasons.append(
                f"日风险超限: {projected_daily_risk*100:.2f}% < -{RISK_PER_DAY*100:.2f}%"
            )
        else:
            reasons.append(f"日风险: {projected_daily_risk*100:.2f}%")
            
        # 3. 检查回撤
        current_drawdown = (self._peak_balance - self._current_balance) / self._peak_balance
        if current_drawdown > MAX_DRAWDOWN:
            approved = False
            rejected_reasons.append(
                f"回撤超限: {current_drawdown*100:.2f}% > {MAX_DRAWDOWN*100:.2f}%"
            )
        else:
            reasons.append(f"回撤: {current_drawdown*100:.2f}%")
            
        result = RiskCheckResult(
            symbol=proposal.symbol,
            proposal=proposal,
            approved=approved,
            reasons=reasons,
            rejected_reasons=rejected_reasons,
            current_single_risk=single_risk,
            current_daily_risk=projected_daily_risk,
            current_drawdown=current_drawdown,
            timestamp=datetime.now(),
        )
        
        if approved:
            self.logger.info(
                f"✅ 风控通过: {proposal.symbol} "
                f"单笔:{single_risk*100:.2f}% 日损:{projected_daily_risk*100:.2f}% 回撤:{current_drawdown*100:.2f}%"
            )
        else:
            self.logger.warning(
                f"❌ 风控拒绝: {proposal.symbol} 原因: {rejected_reasons}"
            )
            
        return result
        
    def update_balance(self, balance: float):
        """更新余额"""
        self._current_balance = balance
        if balance > self._peak_balance:
            self._peak_balance = balance
            
    def get_stats(self) -> Dict:
        """获取风控统计"""
        return {
            "daily_pnl": self._daily_pnl,
            "current_balance": self._current_balance,
            "peak_balance": self._peak_balance,
            "current_drawdown": (
                (self._peak_balance - self._current_balance) / self._peak_balance
                if self._peak_balance > 0 else 0
            ),
        }
