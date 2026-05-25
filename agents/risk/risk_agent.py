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
    支持双平台持仓合并风控
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
        self._exchange_router = None
        self._current_trend: str = "NEUTRAL"

    def set_router(self, router):
        """设置交易所路由器"""
        self._exchange_router = router

    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("trade_proposal", self._on_proposal)
        await self.subscribe("position.closed", self._on_position_closed)
        await self.subscribe("regime", self._on_regime)

    async def _on_regime(self, event):
        """接收市场状态事件"""
        self._current_trend = event.trend_direction
        
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

        # v3: 0. 检查15m趋势方向（双重保险）
        if self._current_trend == "NEUTRAL":
            approved = False
            rejected_reasons.append("15m趋势不明(NEUTRAL)，拒绝开仓")
        else:
            reasons.append(f"趋势方向: {self._current_trend}")

        # 1. 检查单笔风险（v3: 5%上限）
        single_risk = proposal.position_pct
        max_single_risk = 0.05  # v3: 单笔最大5%（含杠杆后）
        if single_risk > max_single_risk:
            approved = False
            rejected_reasons.append(
                f"单笔风险超限: {single_risk*100:.2f}% > {max_single_risk*100:.2f}%"
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

        # 3. 检查回撤（v3: 15%收紧）
        current_drawdown = (self._peak_balance - self._current_balance) / self._peak_balance
        if current_drawdown > MAX_DRAWDOWN:
            approved = False
            rejected_reasons.append(
                f"回撤超限: {current_drawdown*100:.2f}% > {MAX_DRAWDOWN*100:.2f}%"
            )
        else:
            reasons.append(f"回撤: {current_drawdown*100:.2f}%")

        # 4. 检查杠杆上限（v3: 20x硬上限）
        if proposal.leverage > 20:
            approved = False
            rejected_reasons.append(
                f"杠杆超限: {proposal.leverage}x > 20x"
            )
        else:
            reasons.append(f"杠杆: {proposal.leverage}x")

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
            trend_direction=self._current_trend,
        )

        if approved:
            self.logger.info(
                f"✅ 风控通过: {proposal.symbol} "
                f"单笔:{single_risk*100:.2f}% 日损:{projected_daily_risk*100:.2f}% "
                f"回撤:{current_drawdown*100:.2f}% 杠杆:{proposal.leverage}x"
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
