"""
8. 仓位决策 Agent - v3重写
ATR动态止损止盈 + 信号强度动态仓位 + 杠杆硬上限20x
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
    RISK_PER_TRADE, TRADING_V3,
)


class DecisionAgent(BaseAgent):
    """
    仓位决策Agent (v3重写)

    - ATR动态止损止盈
    - 信号强度+波动率动态仓位
    - 杠杆硬上限20x
    - 安全校验：杠杆*止损% <= 50%
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
        self._current_balance: float = 10000.0

    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("signal", self._on_signal)
        await self.subscribe("debate", self._on_debate)

    async def _on_signal(self, signal: SignalEvent):
        """接收信号"""
        self.logger.debug(f"收到信号: {signal.symbol} {signal.direction} 分数:{signal.score:.1f}")
        if signal.direction == "neutral":
            return

        # 存储信号
        if signal.symbol in self._pending_proposals:
            self._pending_proposals[signal.symbol] = (signal, self._pending_proposals[signal.symbol][1])
        else:
            self._pending_proposals[signal.symbol] = (signal, None)

        await self._try_make_decision(signal.symbol)

    async def _on_debate(self, debate: DebateEvent):
        """接收辩论结果"""
        self.logger.debug(f"收到辩论: {debate.symbol} 通过:{debate.approved} 置信度:{debate.confidence:.1f}%")
        if debate.symbol in self._pending_proposals:
            self._pending_proposals[debate.symbol] = (
                self._pending_proposals[debate.symbol][0],
                debate
            )
        else:
            self.logger.warning(f"收到辩论但无对应信号: {debate.symbol}")

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

        if signal is None or debate is None:
            return

        if not debate.approved:
            self.logger.info(f"{symbol} 辩论未通过，跳过")
            del self._pending_proposals[symbol]
            return

        # v3: 信号强度检查
        min_strength = TRADING_V3.get('min_signal_strength', 70)
        if signal.score < min_strength:
            self.logger.info(f"{symbol} 分数未达阈值({signal.score:.1f} < {min_strength})")
            del self._pending_proposals[symbol]
            return

        # 计算仓位
        proposal = self._calculate_position(signal, debate)

        await self.publish("trade_proposal", proposal)

        self.logger.info(
            f"📋 交易提案: {symbol} {proposal.direction.upper()} "
            f"杠杆: {proposal.leverage}x 仓位: {proposal.position_pct*100:.1f}% "
            f"止损: ${proposal.stop_loss:.4f} 止盈: ${proposal.take_profit:.4f} "
            f"ATR: {proposal.atr:.4f}"
        )

        del self._pending_proposals[symbol]

    def _calculate_position(
        self,
        signal: SignalEvent,
        debate: DebateEvent,
    ) -> TradeProposal:
        """v3: 计算仓位参数 - ATR动态止损止盈 + 动态仓位"""

        # === 杠杆计算 ===
        base_leverage = TRADING_V3.get('base_leverage', 5)
        max_leverage = TRADING_V3.get('max_leverage', 20)

        if signal.score >= 85:
            leverage = 10
        elif signal.score >= 75:
            leverage = 7
        elif signal.score >= 70:
            leverage = 5
        else:
            leverage = base_leverage

        leverage = min(leverage, max_leverage)  # 硬上限

        # === ATR动态止损止盈 ===
        atr = signal.atr
        price = signal.score  # 这里需要当前价格，从信号中获取
        # 实际价格从K线数据中获取，这里用信号的atr计算
        # 如果ATR为0，使用默认值
        if atr <= 0:
            atr = 0.001  # 默认0.1%

        atr_sl_mult = TRADING_V3.get('atr_sl_multiplier', 1.5)
        atr_tp_mult = TRADING_V3.get('atr_tp_multiplier', 3.0)
        sl_min = TRADING_V3.get('sl_min_pct', 0.01)
        sl_max = TRADING_V3.get('sl_max_pct', 0.05)
        tp_min = TRADING_V3.get('tp_min_pct', 0.02)
        tp_max = TRADING_V3.get('tp_max_pct', 0.15)

        # 使用信号中的价格（从K线收盘价获取）
        # 这里我们使用ATR百分比来计算止损止盈
        atr_pct = atr / 100 if atr > 1 else atr  # 如果ATR是绝对值，转换为百分比

        sl_pct = atr_pct * atr_sl_mult
        tp_pct = atr_pct * atr_tp_mult

        # 安全边界
        sl_pct = max(sl_min, min(sl_pct, sl_max))
        tp_pct = max(tp_min, min(tp_pct, tp_max))

        # 计算止损止盈价格（使用信号分数作为参考价格，实际应从K线获取）
        # 这里使用百分比形式
        side = signal.direction
        if side == "long":
            stop_loss_pct = -sl_pct
            take_profit_pct = tp_pct
        else:
            stop_loss_pct = sl_pct
            take_profit_pct = -tp_pct

        # === 动态仓位 ===
        margin, pos_pct = self._calc_position_size(signal.score, atr)

        # === 安全校验：杠杆 * 止损% 不能超过50% ===
        if leverage * sl_pct > 0.50:
            leverage = max(1, int(0.50 / sl_pct))

        # R:R
        risk_reward = tp_pct / sl_pct if sl_pct > 0 else 2.0

        # 获取移动止盈参数
        trailing_trigger = TRADING_V3.get('trailing_trigger', 0.50)
        trailing_step = TRADING_V3.get('trailing_step', 0.30)

        return TradeProposal(
            symbol=signal.symbol,
            direction=side,
            leverage=leverage,
            position_pct=pos_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            risk_reward_ratio=risk_reward,
            signal_score=signal.score,
            debate_confidence=debate.confidence,
            mtf_confirmed=True,
            timestamp=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=5),
            # v3新增
            atr=atr,
            trailing_trigger=trailing_trigger,
            trailing_step=trailing_step,
            stop_loss=0,  # 实际价格由PositionAgent计算
            take_profit=0,  # 实际价格由PositionAgent计算
        )

    def _calc_position_size(self, strength: float, atr: float):
        """v3: 动态仓位 - 强度+波动率"""
        balance = self._current_balance

        # 强度→基础仓位比例
        if strength >= 85:
            base_pct = 0.12
        elif strength >= 75:
            base_pct = 0.10
        elif strength >= 70:
            base_pct = 0.08
        else:
            base_pct = 0.05

        # 波动率调整：高波动降仓
        # ATR作为波动率指标
        volatility = atr if atr < 1 else atr / 100  # 归一化
        if volatility > 0.03:
            base_pct *= 0.7  # 高波动-30%
        elif volatility > 0.02:
            base_pct *= 0.85  # 中波动-15%

        # 不超过单笔风险上限
        max_pct = TRADING_V3.get('max_position_pct', 0.10)
        base_pct = min(base_pct, max_pct)

        return balance * base_pct, base_pct

    def update_balance(self, balance: float):
        """更新余额"""
        self._current_balance = balance
