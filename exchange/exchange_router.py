"""
交易所智能路由器
根据价格、深度、手续费选择最优平台执行交易
"""

import asyncio
from typing import Dict, Optional, List

from loguru import logger

from exchange.base_exchange import (
    BaseExchange, OrderParams, Order, Ticker, AccountBalance, Position,
)
from config import (
    BINANCE_FEE_RATE, OKX_FEE_RATE, DEFAULT_EXCHANGE,
)


class ExchangeRouter:
    """智能路由：选择最优交易所执行交易"""

    def __init__(self):
        self.exchanges: Dict[str, BaseExchange] = {}
        self._fee_rates = {
            "binance": BINANCE_FEE_RATE,
            "okx": OKX_FEE_RATE,
        }

    def register(self, name: str, exchange: BaseExchange):
        """注册交易所"""
        self.exchanges[name] = exchange
        logger.info(f"[路由器] 注册交易所: {name}")

    @property
    def available_exchanges(self) -> List[str]:
        """可用交易所列表"""
        return [name for name, ex in self.exchanges.items() if ex.is_connected]

    async def connect_all(self) -> Dict[str, bool]:
        """连接所有已注册的交易所"""
        results = {}
        for name, exchange in self.exchanges.items():
            results[name] = await exchange.connect()
        return results

    async def disconnect_all(self):
        """断开所有交易所"""
        for exchange in self.exchanges.values():
            await exchange.disconnect()

    async def route_order(self, params: OrderParams) -> Order:
        """
        路由订单到最优交易所

        Args:
            params: 下单参数，exchange字段控制路由策略:
                - "auto": 自动选择最优平台
                - "binance": 指定币安
                - "okx": 指定OKX

        Returns:
            订单结果
        """
        exchange_name = params.exchange

        if exchange_name == "auto":
            exchange_name = await self._find_best_exchange(params)

        if exchange_name not in self.exchanges:
            raise ValueError(f"交易所 {exchange_name} 未注册")

        exchange = self.exchanges[exchange_name]
        if not exchange.is_connected:
            raise RuntimeError(f"交易所 {exchange_name} 未连接")

        logger.info(f"[路由器] 通过 {exchange_name} 执行: {params.symbol} {params.side}")
        return await exchange.create_order(params)

    async def _find_best_exchange(self, params: OrderParams) -> str:
        """找到最优交易所"""
        available = self.available_exchanges
        if not available:
            raise RuntimeError("没有可用的交易所")

        if len(available) == 1:
            return available[0]

        # 并行获取两个平台的价格和深度
        tasks = {}
        for name in available:
            ex = self.exchanges[name]
            tasks[name] = {
                "ticker": ex.get_ticker(params.symbol),
                "orderbook": ex.get_orderbook(params.symbol, limit=5),
            }

        results = {}
        for name in available:
            try:
                ticker = await tasks[name]["ticker"]
                orderbook = await tasks[name]["orderbook"]
                results[name] = {"ticker": ticker, "orderbook": orderbook}
            except Exception as e:
                logger.warning(f"[路由器] 获取 {name} 数据失败: {e}")
                continue

        if not results:
            # fallback到第一个可用的
            return available[0]

        # 计算综合评分
        best_name = available[0]
        best_score = -float("inf")

        for name, data in results.items():
            ticker = data["ticker"]
            orderbook = data["orderbook"]
            fee = self._fee_rates.get(name, 0.001)

            score = self._calculate_score(params, ticker, orderbook, fee)

            if score > best_score:
                best_score = score
                best_name = name

        return best_name

    def _calculate_score(
        self,
        params: OrderParams,
        ticker: Ticker,
        orderbook,
        fee: float,
    ) -> float:
        """
        计算交易所综合评分

        评分因素:
        1. 价格优势 (买低卖高)
        2. 深度 (前5档挂单量)
        3. 手续费
        """
        score = 0.0

        # 1. 价格优势
        if params.side == "buy":
            # 买入：ask越低越好，用负数使得低价得分高
            price_score = -ticker.ask
        else:
            # 卖出：bid越高越好
            price_score = ticker.bid
        score += price_score * 1000  # 放大价格因子

        # 2. 深度
        if params.side == "buy":
            depth = sum(qty for _, qty in orderbook.asks[:5])
        else:
            depth = sum(qty for _, qty in orderbook.bids[:5])
        score += depth * 0.01  # 深度权重

        # 3. 手续费 (越低越好)
        score -= fee * 10000

        return score

    async def get_all_balances(self) -> Dict[str, AccountBalance]:
        """获取所有交易所余额"""
        balances = {}
        for name, exchange in self.exchanges.items():
            if exchange.is_connected:
                try:
                    balances[name] = await exchange.get_balance()
                except Exception as e:
                    logger.warning(f"[路由器] 获取 {name} 余额失败: {e}")
        return balances

    async def get_all_positions(self) -> Dict[str, List[Position]]:
        """获取所有交易所持仓"""
        positions = {}
        for name, exchange in self.exchanges.items():
            if exchange.is_connected:
                try:
                    positions[name] = await exchange.get_positions()
                except Exception as e:
                    logger.warning(f"[路由器] 获取 {name} 持仓失败: {e}")
        return positions

    async def close_all_positions(self) -> List[Dict]:
        """紧急全平：关闭所有交易所的所有持仓"""
        results = []
        for name, exchange in self.exchanges.items():
            if not exchange.is_connected:
                continue
            try:
                positions = await exchange.get_positions()
                for pos in positions:
                    try:
                        close_params = OrderParams(
                            symbol=pos.symbol,
                            side="sell" if pos.side == "long" else "buy",
                            order_type="market",
                            amount=pos.contracts,
                            exchange=name,
                        )
                        order = await exchange.create_order(close_params)
                        results.append({
                            "exchange": name,
                            "symbol": pos.symbol,
                            "side": pos.side,
                            "order_id": order.order_id,
                            "status": "closed",
                        })
                        logger.info(
                            f"[路由器] 紧急平仓: {name} {pos.symbol} {pos.side}"
                        )
                    except Exception as e:
                        results.append({
                            "exchange": name,
                            "symbol": pos.symbol,
                            "error": str(e),
                        })
            except Exception as e:
                logger.error(f"[路由器] 获取 {name} 持仓失败: {e}")
        return results

    async def get_best_ticker(self, symbol: str) -> tuple[str, Ticker]:
        """获取最优价格的ticker"""
        best_name = None
        best_ticker = None

        for name, exchange in self.exchanges.items():
            if not exchange.is_connected:
                continue
            try:
                ticker = await exchange.get_ticker(symbol)
                if best_ticker is None or ticker.last < best_ticker.last:
                    best_ticker = ticker
                    best_name = name
            except Exception:
                continue

        return best_name, best_ticker


# 全局路由器实例
exchange_router = ExchangeRouter()
