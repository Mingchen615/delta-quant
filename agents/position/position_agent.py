"""
12. 持仓监控 Agent (核心) - v3重写
ATR动态止损 + 移动止盈，无时间止损
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import PositionEvent, EventType
from exchange.paper_trade import PaperTradeEngine
from config import TRADING_V3, LIVE_TRADE


class PositionAgent(BaseAgent):
    """
    持仓监控Agent (v3重写)

    ATR动态止损 + 移动止盈:
    - 止损: 1.5倍ATR（下限1%，上限5%）
    - 止盈: 3倍ATR（2:1盈亏比）
    - 移动止盈: 盈利50%后激活，回撤30%平仓
    - 无时间止损！不到止损位不平仓

    每秒检查一次所有持仓，支持跨平台监控
    """

    TRAILING_STOP_TRIGGER = TRADING_V3.get('trailing_trigger', 0.50)  # 盈利50%激活
    TRAILING_STOP_STEP = TRADING_V3.get('trailing_step', 0.30)  # 回撤30%平仓

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
        self._position_data: Dict[str, dict] = {}  # symbol -> position metadata
        self._exchange_router = None

    def set_router(self, router):
        """设置交易所路由器"""
        self._exchange_router = router

    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("position.opened", self._on_position_opened)
        await self.subscribe("position.closed", self._on_position_closed)

    async def _on_position_opened(self, event: PositionEvent):
        """持仓开仓 - 存储ATR止损止盈信息"""
        symbol = event.symbol

        # 从事件或配置获取ATR止损止盈参数
        atr = getattr(event, 'atr', 0)
        entry = event.entry_price
        side = event.direction
        leverage = event.leverage

        # 计算ATR止损止盈
        atr_sl_mult = TRADING_V3.get('atr_sl_multiplier', 1.5)
        atr_tp_mult = TRADING_V3.get('atr_tp_multiplier', 3.0)
        sl_min = TRADING_V3.get('sl_min_pct', 0.01)
        sl_max = TRADING_V3.get('sl_max_pct', 0.05)
        tp_min = TRADING_V3.get('tp_min_pct', 0.02)
        tp_max = TRADING_V3.get('tp_max_pct', 0.15)

        if atr > 0 and entry > 0:
            sl_distance = atr * atr_sl_mult
            tp_distance = atr * atr_tp_mult

            if side == "long":
                stop_loss = entry - sl_distance
                take_profit = entry + tp_distance
                sl_pct = sl_distance / entry
                tp_pct = tp_distance / entry
            else:
                stop_loss = entry + sl_distance
                take_profit = entry - tp_distance
                sl_pct = sl_distance / entry
                tp_pct = tp_distance / entry

            # 安全边界
            if sl_pct < sl_min:
                if side == "long":
                    stop_loss = entry * (1 - sl_min)
                else:
                    stop_loss = entry * (1 + sl_min)
            if sl_pct > sl_max:
                if side == "long":
                    stop_loss = entry * (1 - sl_max)
                else:
                    stop_loss = entry * (1 + sl_max)
            if tp_pct < tp_min:
                if side == "long":
                    take_profit = entry * (1 + tp_min)
                else:
                    take_profit = entry * (1 - tp_min)
            if tp_pct > tp_max:
                if side == "long":
                    take_profit = entry * (1 + tp_max)
                else:
                    take_profit = entry * (1 - tp_max)
        else:
            # 默认值
            if side == "long":
                stop_loss = entry * 0.97  # 3%
                take_profit = entry * 1.06  # 6%
            else:
                stop_loss = entry * 1.03
                take_profit = entry * 0.94

        self._position_data[symbol] = {
            'entry': entry,
            'side': side,
            'leverage': leverage,
            'margin': getattr(event, 'margin', 0) or (entry * 0.1),
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'trailing_active': False,
            'max_pnl_pct': 0,
            'atr': atr,
        }

        self.logger.info(
            f"持仓监控开始: {symbol} "
            f"入场: ${entry:.4f} "
            f"止损: ${stop_loss:.4f} "
            f"止盈: ${take_profit:.4f} "
            f"ATR: {atr:.4f}"
        )

    async def _on_position_closed(self, event: PositionEvent):
        """持仓平仓"""
        self._position_data.pop(event.symbol, None)

    async def execute(self):
        """检查所有持仓"""
        if self._exchange_router and LIVE_TRADE:
            await self._check_real_positions()
        elif self._paper_engine:
            positions = self._paper_engine.get_positions()
            for symbol, position in positions.items():
                await self._check_position(symbol, position)

    async def _check_real_positions(self):
        """检查实盘持仓（双平台）"""
        try:
            all_positions = await self._exchange_router.get_all_positions()
            for exchange_name, positions in all_positions.items():
                for pos in positions:
                    await self._check_real_position(exchange_name, pos)
        except Exception as e:
            self.logger.error(f"实盘持仓检查出错: {e}")

    async def _check_real_position(self, exchange_name: str, position):
        """检查单个实盘持仓"""
        try:
            current_price = position.mark_price
            entry_price = position.entry_price
            symbol = position.symbol

            # 获取或创建持仓数据
            if symbol not in self._position_data:
                self._position_data[symbol] = {
                    'entry': entry_price,
                    'side': position.side,
                    'leverage': position.leverage,
                    'margin': entry_price * position.contracts / position.leverage,
                    'stop_loss': entry_price * (0.97 if position.side == "long" else 1.03),
                    'take_profit': entry_price * (1.06 if position.side == "long" else 0.94),
                    'trailing_active': False,
                    'max_pnl_pct': 0,
                    'atr': 0,
                }

            data = self._position_data[symbol]
            result = self._check_stop_logic(data, current_price)

            if result['closed']:
                await self._close_real_position(
                    exchange_name, symbol, position.side, position.contracts,
                    result['close_reason']
                )

        except Exception as e:
            self.logger.error(f"检查实盘持仓出错: {e}")

    async def _close_real_position(self, exchange_name: str, symbol: str, side: str, contracts: float, reason: str):
        """平仓实盘持仓"""
        try:
            from exchange.base_exchange import OrderParams
            close_params = OrderParams(
                symbol=symbol,
                side="sell" if side == "long" else "buy",
                order_type="market",
                amount=contracts,
                exchange=exchange_name,
            )
            if self._exchange_router:
                await self._exchange_router.route_order(close_params)
                self.logger.info(f"[{exchange_name}] 平仓: {symbol} 原因: {reason}")
        except Exception as e:
            self.logger.error(f"平仓失败: {e}")

    async def _get_current_price(self, symbol: str) -> float:
        """从路由器获取当前价格"""
        if self._exchange_router:
            for name, ex in self._exchange_router.exchanges.items():
                if ex.is_connected:
                    try:
                        ticker = await ex.get_ticker(symbol)
                        return ticker.last
                    except Exception:
                        continue
        from exchange.binance_client import binance_client
        ticker = await binance_client.fetch_ticker(symbol)
        return float(ticker["last"])

    async def _check_position(self, symbol: str, position):
        """检查单个模拟盘持仓"""
        try:
            current_price = await self._get_current_price(symbol)

            # 获取或创建持仓数据
            if symbol not in self._position_data:
                entry = position.entry_price
                side = position.direction
                self._position_data[symbol] = {
                    'entry': entry,
                    'side': side,
                    'leverage': position.leverage,
                    'margin': getattr(position, 'margin', entry * 0.1),
                    'stop_loss': entry * (0.97 if side == "long" else 1.03),
                    'take_profit': entry * (1.06 if side == "long" else 0.94),
                    'trailing_active': False,
                    'max_pnl_pct': 0,
                    'atr': 0,
                }

            data = self._position_data[symbol]
            result = self._check_stop_logic(data, current_price)

            if result['closed']:
                close_result = self._paper_engine.close_position(
                    symbol, current_price, result['close_reason']
                )
                if close_result:
                    await self._publish_closed(symbol, close_result, result['close_reason'])

        except Exception as e:
            self.logger.error(f"检查持仓{symbol}出错: {e}")

    def _check_stop_logic(self, data: dict, current_price: float) -> dict:
        """v3: ATR止损 + 移动止盈逻辑（无时间止损）"""
        entry = data['entry']
        side = data['side']
        sl = data['stop_loss']
        tp = data['take_profit']
        lev = data.get('leverage', 5)

        closed = False
        close_price = None
        close_reason = ''

        # 计算盈亏百分比（含杠杆）
        if side == 'long':
            pnl_pct = (current_price - entry) / entry * lev
        else:
            pnl_pct = (entry - current_price) / entry * lev

        # 1. 移动止盈检查
        if data.get('trailing_active'):
            if side == 'long':
                # 盈利最高点回撤30%平仓
                trail_price = entry * (1 + data['max_pnl_pct'] / lev - self.TRAILING_STOP_STEP / lev)
                if current_price <= trail_price:
                    closed = True
                    close_price = current_price
                    close_reason = '移动止盈'
            else:
                trail_price = entry * (1 - data['max_pnl_pct'] / lev + self.TRAILING_STOP_STEP / lev)
                if current_price >= trail_price:
                    closed = True
                    close_price = current_price
                    close_reason = '移动止盈'

            # 更新最大盈亏
            if pnl_pct > data.get('max_pnl_pct', 0):
                data['max_pnl_pct'] = pnl_pct

        elif pnl_pct >= self.TRAILING_STOP_TRIGGER:
            # 激活移动止盈
            data['trailing_active'] = True
            data['max_pnl_pct'] = pnl_pct
            self.logger.info(f"移动止盈激活: 盈利{pnl_pct*100:.1f}%")

        # 2. ATR止损（不到止损位不平仓）
        if not closed:
            if side == 'long' and current_price <= sl:
                closed = True
                close_price = sl
                close_reason = 'ATR止损'
            elif side == 'short' and current_price >= sl:
                closed = True
                close_price = sl
                close_reason = 'ATR止损'

        # 3. ATR止盈
        if not closed:
            if side == 'long' and current_price >= tp:
                closed = True
                close_price = tp
                close_reason = 'ATR止盈'
            elif side == 'short' and current_price <= tp:
                closed = True
                close_price = tp
                close_reason = 'ATR止盈'

        # 注意：没有时间止损！不到止损位就不平！

        if closed:
            # 计算实际盈亏
            if side == 'long':
                final_pct = (close_price - entry) / entry
            else:
                final_pct = (entry - close_price) / entry
            lev_pct = final_pct * lev
            margin = data.get('margin', 0)
            pnl = margin * lev_pct

            return {
                'closed': True,
                'close_price': close_price,
                'close_reason': close_reason,
                'pnl': pnl,
                'pnl_pct': lev_pct,
                'direction': side,
                'entry_price': entry,
            }

        return {'closed': False}

    async def _publish_closed(self, symbol: str, result: dict, reason: str):
        """发布平仓事件"""
        event = PositionEvent(
            event_type=EventType.POSITION_CLOSED,
            symbol=symbol,
            direction=result.get("direction", "unknown"),
            entry_price=result.get("entry_price", 0),
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
        return list(self._position_data.keys())
