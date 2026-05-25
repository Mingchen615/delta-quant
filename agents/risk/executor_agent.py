"""
11. 订单执行 Agent
市价单执行，支持双平台路由
"""

import asyncio
from datetime import datetime
from typing import Dict, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import RiskCheckResult, OrderEvent, PositionEvent
from exchange.paper_trade import PaperTradeEngine
from exchange.base_exchange import OrderParams
from config import LIVE_TRADE, HARD_STOP_LOSS, TP1_RATIO


class ExecutorAgent(BaseAgent):
    """
    订单执行Agent

    功能:
    - 支持双平台路由（币安/OKX/自动选择）
    - 模拟盘/实盘自动切换
    - 市价单执行 + 滑点控制
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        paper_engine: Optional[PaperTradeEngine] = None,
        exchange_router=None,
        **kwargs
    ):
        default_config = AgentConfig(
            name="订单执行",
            log_prefix="[订单执行]",
            interval=0,  # 事件触发
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)

        self._paper_engine = paper_engine or PaperTradeEngine()
        self._exchange_router = exchange_router
        self._pending_orders: Dict[str, OrderEvent] = {}

    def set_router(self, router):
        """设置交易所路由器"""
        self._exchange_router = router

    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("portfolio_check", self._on_portfolio_check)

    async def _on_portfolio_check(self, result: RiskCheckResult):
        """接收组合检查通过的提案"""
        await self.execute_order(result)

    async def execute_order(self, result: RiskCheckResult):
        """执行订单"""
        proposal = result.proposal
        self.logger.info(f"执行订单: {proposal.symbol} {proposal.direction.upper()}")

        try:
            # 创建订单事件
            order = OrderEvent(
                event_type="order_request",
                symbol=proposal.symbol,
                direction=proposal.direction,
                order_type="market",
                side="buy" if proposal.direction == "long" else "sell",
                leverage=proposal.leverage,
                status="pending",
                created_at=datetime.now(),
            )

            if LIVE_TRADE and self._exchange_router:
                # 实盘执行：通过路由器选择最优平台
                await self._execute_live_router(order, proposal)
            elif LIVE_TRADE:
                # 实盘执行：直接调用（兼容旧模式）
                await self._execute_live_direct(order, proposal)
            else:
                # 模拟执行
                await self._execute_paper(order, proposal)

        except Exception as e:
            self.logger.error(f"订单执行失败: {e}")
            await self._publish_order_failed(proposal.symbol, str(e))

    async def _execute_live_router(self, order: OrderEvent, proposal):
        """通过路由器的实盘执行"""
        try:
            current_price = await self._get_current_price(proposal.symbol)
            # 余额 * 仓位比例 / 当前价格 = 数量
            balance = 1000  # 默认值，实际应从交易所获取
            if self._exchange_router:
                for name, ex in self._exchange_router.exchanges.items():
                    if ex.is_connected:
                        try:
                            bal = await ex.get_balance()
                            balance = bal.free
                            break
                        except Exception:
                            continue
            quantity = balance * proposal.position_pct * proposal.leverage / current_price

            params = OrderParams(
                symbol=proposal.symbol,
                side=order.side,
                order_type="market",
                amount=round(quantity, 6),
                leverage=proposal.leverage,
                margin_mode="cross",
                exchange=getattr(proposal, "exchange", "auto"),
            )

            result = await self._exchange_router.route_order(params)

            # 更新订单
            order.order_id = result.order_id
            order.status = result.status
            order.filled_quantity = result.filled
            order.avg_fill_price = result.average
            order.updated_at = datetime.now()

            # 发布事件
            await self.publish("order_submitted", order)
            await self.publish("order_filled", order)

            # 发布持仓事件
            pos_event = PositionEvent(
                event_type="position_opened",
                symbol=proposal.symbol,
                direction=proposal.direction,
                entry_price=result.average,
                quantity=result.filled,
                leverage=proposal.leverage,
                stop_loss=proposal.stop_loss_pct,
                take_profit=proposal.take_profit_pct,
                timestamp=datetime.now(),
            )
            await self.publish("position.opened", pos_event)

            self.logger.info(
                f"实盘开仓: {proposal.symbol} via {result.exchange} "
                f"价格: ${result.average:.4f} 数量: {result.filled:.4f}"
            )

        except Exception as e:
            self.logger.error(f"路由器执行失败: {e}")
            order.status = "failed"
            order.error = str(e)
            await self.publish("order_failed", order)

    async def _execute_live_direct(self, order: OrderEvent, proposal):
        """直接调用币安的实盘执行（兼容旧模式）"""
        from exchange.binance_client import binance_client
        try:
            balance = await binance_client.fetch_balance()
            usdt_balance = float(balance.get("USDT", {}).get("free", 0))
            quantity = usdt_balance * proposal.position_pct / proposal.leverage
            quantity = round(quantity, 3)

            filled = await binance_client.create_order(
                symbol=proposal.symbol,
                side=order.side,
                order_type="market",
                quantity=quantity,
                leverage=proposal.leverage,
            )

            order.order_id = str(filled.get("id"))
            order.status = "filled"
            order.filled_quantity = float(filled.get("filledQty", quantity))
            order.avg_fill_price = float(filled.get("average", 0))
            order.updated_at = datetime.now()

            await self.publish("order_submitted", order)
            await self.publish("order_filled", order)

            self.logger.info(f"实盘开仓: {proposal.symbol} 订单ID: {order.order_id}")

        except Exception as e:
            self.logger.error(f"直接执行失败: {e}")
            order.status = "failed"
            order.error = str(e)
            await self.publish("order_failed", order)

    async def _execute_paper(self, order: OrderEvent, proposal):
        """模拟执行"""
        try:
            current_price = await self._get_current_price(proposal.symbol)

            quantity = self._paper_engine.balance * proposal.position_pct / current_price

            # 计算止损止盈价格（基于杠杆调整）
            if proposal.direction == "long":
                stop_loss = current_price * (1 + HARD_STOP_LOSS / proposal.leverage)
                take_profit = current_price * (1 + TP1_RATIO / proposal.leverage)
            else:
                stop_loss = current_price * (1 - HARD_STOP_LOSS / proposal.leverage)
                take_profit = current_price * (1 - TP1_RATIO / proposal.leverage)

            order_id = self._paper_engine.open_position(
                symbol=proposal.symbol,
                direction=proposal.direction,
                entry_price=current_price,
                quantity=quantity,
                leverage=proposal.leverage,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )

            order.order_id = order_id
            order.status = "filled"
            order.filled_quantity = quantity
            order.avg_fill_price = current_price
            order.updated_at = datetime.now()

            await self.publish("order_submitted", order)
            await self.publish("order_filled", order)

            position = self._paper_engine.get_position(proposal.symbol)
            if position:
                pos_event = PositionEvent(
                    event_type="position_opened",
                    symbol=proposal.symbol,
                    direction=proposal.direction,
                    entry_price=position.entry_price,
                    quantity=position.quantity,
                    leverage=position.leverage,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                    timestamp=datetime.now(),
                )
                await self.publish("position.opened", pos_event)

            self.logger.info(
                f"模拟开仓: {proposal.symbol} "
                f"价格: ${current_price:.4f} 数量: {quantity:.4f}"
            )

        except Exception as e:
            self.logger.error(f"模拟执行失败: {e}")
            order.status = "failed"
            order.error = str(e)
            await self.publish("order_failed", order)

    async def _get_current_price(self, symbol: str) -> float:
        """从已连接的交易所获取当前价格"""
        if self._exchange_router:
            for name, ex in self._exchange_router.exchanges.items():
                if ex.is_connected:
                    try:
                        ticker = await ex.get_ticker(symbol)
                        return ticker.last
                    except Exception as e:
                        self.logger.warning(f"[{name}] 获取{symbol}价格失败: {e}")
                        continue
            raise RuntimeError(f"无法获取 {symbol} 价格：所有交易所调用失败")
        # 仅在没有路由器时才用binance_client
        from exchange.binance_client import binance_client
        ticker = await binance_client.fetch_ticker(symbol)
        return float(ticker["last"])

    def _calculate_quantity(self, proposal, balance: float = 1000) -> float:
        """计算下单数量"""
        # 余额 * 仓位比例 / 杠杆 → 名义金额，再除以价格得到数量
        # 简化：使用position_pct作为保证金比例
        notional = balance * proposal.position_pct * proposal.leverage
        # 返回名义金额，实际数量需要除以价格（由交易所处理）
        return round(notional, 2)

    async def _publish_order_failed(self, symbol: str, error: str):
        """发布订单失败事件"""
        order = OrderEvent(
            event_type="order_failed",
            symbol=symbol,
            status="failed",
            error=error,
            updated_at=datetime.now(),
        )
        await self.publish("order_failed", order)

    async def close_position(
        self,
        symbol: str,
        reason: str = "manual",
        exchange: str = "auto",
    ):
        """平仓"""
        if LIVE_TRADE and self._exchange_router:
            # 通过路由器平仓
            try:
                all_positions = await self._exchange_router.get_all_positions()
                for ex_name, positions in all_positions.items():
                    if exchange != "auto" and ex_name != exchange:
                        continue
                    for pos in positions:
                        if pos.symbol == symbol:
                            close_params = OrderParams(
                                symbol=symbol,
                                side="sell" if pos.side == "long" else "buy",
                                order_type="market",
                                amount=pos.contracts,
                                exchange=ex_name,
                            )
                            result = await self._exchange_router.route_order(close_params)
                            self.logger.info(f"平仓: {symbol} via {ex_name} 原因: {reason}")
                            return {
                                "order_id": result.order_id,
                                "symbol": symbol,
                                "exchange": ex_name,
                                "reason": reason,
                            }
            except Exception as e:
                self.logger.error(f"路由器平仓失败: {e}")
                return None
        elif not LIVE_TRADE:
            return self._paper_engine.close_position(symbol, None, reason)
        else:
            from exchange.binance_client import binance_client
            try:
                positions = await binance_client.fetch_positions(symbol)
                pos = positions[0] if positions else None
                if pos:
                    side = "sell" if pos["side"] == "long" else "buy"
                    quantity = abs(float(pos["contracts"]))
                    order = await binance_client.create_order(
                        symbol=symbol,
                        side=side,
                        order_type="market",
                        quantity=quantity,
                    )
                    return {"order_id": str(order.get("id")), "symbol": symbol, "reason": reason}
            except Exception as e:
                self.logger.error(f"平仓失败: {e}")
                return None

    def get_paper_engine(self) -> PaperTradeEngine:
        return self._paper_engine

    async def execute(self):
        """事件驱动型Agent，execute为空"""
        await asyncio.sleep(self.config.interval)
