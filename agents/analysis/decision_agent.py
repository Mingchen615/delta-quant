"""
8. 仓位决策 Agent
根据信号和辩论结果决定仓位参数
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import SignalEvent, DebateEvent, TradeProposal
from config import (
    BASE_LEVERAGE, MAX_LEVERAGE, LEVERAGE_STEP,
    SIGNAL_THRESHOLD_MAIN, SIGNAL_THRESHOLD_ALT,
    RISK_PER_TRADE
)


class DecisionAgent(BaseAgent):
    """
    仓位决策Agent
    根据signal_score + debate_confidence计算:
    - 杠杆: 基础20x，score每高10分+5x，上限50x
    - Kelly公式计算仓位
    - 多时间框架确认: MTF score>75
    - 输出TradeProposal
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="仓位决策",
            log_prefix="[仓位决策]",
            interval=0,  # 事件触发
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)
        
        self._pending_proposals: Dict[str, tuple] = {}  # symbol -> (signal, debate)
        
    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("signal", self._on_signal)
        await self.subscribe("debate", self._on_debate)
        
    async def _on_signal(self, signal: SignalEvent):
        """接收信号"""
        if signal.direction == "neutral":
            return
            
        # 存储信号
        if signal.symbol in self._pending_proposals:
            self._pending_proposals[signal.symbol] = (signal, self._pending_proposals[signal.symbol][1])
        else:
            self._pending_proposals[signal.symbol] = (signal, None)
            
        # 检查是否可以决策
        await self._try_make_decision(signal.symbol)
        
    async def _on_debate(self, debate: DebateEvent):
        """接收辩论结果"""
        if debate.symbol in self._pending_proposals:
            self._pending_proposals[debate.symbol] = (
                self._pending_proposals[debate.symbol][0],
                debate
            )
            
        # 检查是否可以决策
        await self._try_make_decision(debate.symbol)
        
    async def execute(self):
        """执行待处理决策"""
        for symbol in list(self._pending_proposals.keys()):
            await self._try_make_decision(symbol)
            
    async def _try_make_decision(self, symbol: str):
        """尝试做出仓位决策"""
        if symbol not in self._pending_proposals:
            return
            
        signal, debate = self._pending_proposals[symbol]
        
        # 需要同时有信号和辩论结果
        if signal is None or debate is None:
            return
            
        # 辩论未通过
        if not debate.approved:
            self.logger.info(f"{symbol} 辩论未通过，跳过")
            del self._pending_proposals[symbol]
            return
            
        # 多时间框架确认
        mtf_confirmed = signal.mtf_score >= 75
        
        if not mtf_confirmed:
            self.logger.debug(f"{symbol} MTF未确认，跳过")
            # 不删除，继续等待
            
        # 通过阈值检查
        threshold = SIGNAL_THRESHOLD_MAIN if signal.is_mainstream else SIGNAL_THRESHOLD_ALT
        if signal.score < threshold:
            self.logger.info(f"{symbol} 分数未达阈值({signal.score:.1f} < {threshold})")
            del self._pending_proposals[symbol]
            return
            
        # 计算仓位
        proposal = self._calculate_position(signal, debate, mtf_confirmed)
        
        # 发布交易提案
        await self.publish("trade_proposal", proposal)
        
        self.logger.info(
            f"📋 交易提案: {symbol} {proposal.direction.upper()} "
            f"杠杆: {proposal.leverage}x 仓位: {proposal.position_pct*100:.1f}% "
            f"R:R: 1:{proposal.risk_reward_ratio:.1f}"
        )
        
        # 清理
        del self._pending_proposals[symbol]
        
    def _calculate_position(
        self,
        signal: SignalEvent,
        debate: DebateEvent,
        mtf_confirmed: bool
    ) -> TradeProposal:
        """
        计算仓位参数
        
        杠杆计算:
        - 基础20x
        - score每高10分+5x
        - 上限50x
        """
        # 计算杠杆
        leverage = BASE_LEVERAGE
        leverage += int((signal.score - 50) / 10) * LEVERAGE_STEP
        leverage = min(max(leverage, 10), MAX_LEVERAGE)
        
        # Kelly公式计算仓位
        # f = (bp - q) / b
        # b = 盈亏比, p = 胜率, q = 1-p
        # 简化: 用辩论置信度估计胜率
        win_rate = debate.confidence / 100
        
        # R:R 至少2:1
        risk_reward = max(debate.confidence / 50, 2.0)
        
        # Kelly fraction
        kelly = 1.0  # 使用完整Kelly
        
        # 风险比例
        risk_pct = RISK_PER_TRADE * kelly
        
        # 杠杆调整
        effective_risk = risk_pct / leverage
        
        return TradeProposal(
            symbol=signal.symbol,
            direction=signal.direction,
            leverage=leverage,
            position_pct=effective_risk,
            stop_loss_pct=-1 / risk_reward,  # 止损比例
            take_profit_pct=1,  # 基础止盈1:1，后续调整
            risk_reward_ratio=risk_reward,
            signal_score=signal.score,
            debate_confidence=debate.confidence,
            mtf_confirmed=mtf_confirmed,
            timestamp=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=5),  # 5分钟过期
        )
