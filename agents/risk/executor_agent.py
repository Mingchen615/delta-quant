"""
11. 订单执行 Agent
市价单执行，滑点预估
"""

import asyncio
from datetime import datetime
from typing import Dict, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import RiskCheckResult, OrderEvent, PositionEvent
from exchange.binance_client import binance_client
from exchange.paper_trade import PaperTradeEngine
from config import BINANCE_TESTNET


class ExecutorAgent(BaseAgent):
    """
    订单执行Agent
    
    功能:
    - 市价单执行
    - 滑点预估0.05%
    - 下单确认
    - 支持模拟盘模式
    """
    
    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        paper_engine: Optional[PaperTradeEngine] = None,
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
        self._pending_orders: Dict[str, OrderEvent] = {}
        
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
            
            if BINANCE_TESTNET or not binance_client.api_key:
                # 模拟执行
                await self._execute_paper(order, proposal)
            else:
                # 真实执行
                await self._execute_live(order, proposal)
                
        except Exception as e:
            self.logger.error(f"订单执行失败: {e}")
            await self._publish_order_failed(proposal.symbol, str(e))
            
    async def _execute_paper(self, order: OrderEvent, proposal):
        """模拟执行"""
        try:
            # 获取当前价格
            ticker = await binance_client.fetch_ticker(proposal.symbol)
            current_price = ticker["last"]
            
            # 计算数量（简化）
            quantity = self._paper_engine.balance * proposal.position_pct / current_price
            
            # 开仓
            order_id = self._paper_engine.open_position(
                symbol=proposal.symbol,
                direction=proposal.direction,
                entry_price=current_price,
                quantity=quantity,
                leverage=proposal.leverage,
                stop_loss=current_price * (1 + proposal.stop_loss_pct),
                take_profit=current_price * (1 + proposal.take_profit_pct),
            )
            
            # 更新订单
            order.order_id = order_id
            order.status = "filled"
            order.filled_quantity = quantity
            order.avg_fill_price = current_price
            order.updated_at = datetime.now()
            
            # 发布订单事件
            await self.publish("order_submitted", order)
            await self.publish("order_filled", order)
            
            # 发布持仓事件
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
                f"✅ 模拟开仓: {proposal.symbol} "
                f"价格: ${current_price:.4f} 数量: {quantity:.4f}"
            )
            
        except Exception as e:
            self.logger.error(f"模拟执行失败: {e}")
            order.status = "failed"
            order.error = str(e)
            await self.publish("order_failed", order)
            
    async def _execute_live(self, order: OrderEvent, proposal):
        """真实执行"""
        try:
            # 获取账户余额计算数量
            balance = await binance_client.fetch_balance()
            usdt_balance = float(balance.get("USDT", {}).get("free", 0))
            
            # 计算数量
            quantity = usdt_balance * proposal.position_pct / proposal.leverage
            # 取整（根据交易所规则）
            quantity = round(quantity, 3)
            
            # 下单
            filled = await binance_client.create_order(
                symbol=proposal.symbol,
                side=order.side,
                order_type="market",
                quantity=quantity,
                leverage=proposal.leverage,
            )
            
            # 更新订单
            order.order_id = str(filled.get("id"))
            order.status = "filled"
            order.filled_quantity = float(filled.get("filledQty", quantity))
            order.avg_fill_price = float(filled.get("average", 0))
            order.updated_at = datetime.now()
            
            # 发布事件
            await self.publish("order_submitted", order)
            await self.publish("order_filled", order)
            
            self.logger.info(
                f"✅ 真实开仓: {proposal.symbol} "
                f"订单ID: {order.order_id}"
            )
            
        except Exception as e:
            self.logger.error(f"真实执行失败: {e}")
            order.status = "failed"
            order.error = str(e)
            await self.publish("order_failed", order)
            
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
        reason: str = "manual"
    ) -> Optional[Dict]:
        """平仓"""
        if BINANCE_TESTNET or not binance_client.api_key:
            return self._paper_engine.close_position(symbol, None, reason)
        else:
            # 真实平仓
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
                    
                    return {
                        "order_id": str(order.get("id")),
                        "symbol": symbol,
                        "reason": reason,
                    }
            except Exception as e:
                self.logger.error(f"平仓失败: {e}")
                return None
                
    def get_paper_engine(self) -> PaperTradeEngine:
        """获取模拟引擎"""
        return self._paper_engine

    async def execute(self):
        """
        执行Agent逻辑 - 事件驱动型，execute为空实现
        实际逻辑通过订阅的事件触发
        """
        # ExecutorAgent是事件驱动型，等待下一个执行周期
        await asyncio.sleep(self.config.interval)
