"""
模拟交易引擎
在模拟盘模式下执行，不实际下单
记录虚拟成交，支持滑点模拟
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict

from loguru import logger

from config import BINANCE_TESTNET, HARD_STOP_LOSS
from core.event_types import PositionEvent, OrderEvent


@dataclass
class VirtualPosition:
    """虚拟持仓"""
    symbol: str
    direction: str  # "long" or "short"
    entry_price: float
    quantity: float
    leverage: int
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: datetime = field(default_factory=datetime.now)
    trailing_stop: bool = False
    trailing激活: bool = False
    best_price: float = 0
    

@dataclass
class VirtualOrder:
    """虚拟订单"""
    order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float
    filled_price: float
    filled_at: datetime = field(default_factory=datetime.now)
    status: str = "filled"
    slippage: float = 0


class PaperTradeEngine:
    """
    模拟交易引擎
    不实际下单，记录虚拟成交
    """
    
    def __init__(
        self,
        initial_balance: float = 10000.0,
        slippage: float = 0.0005,  # 0.05%
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.slippage = slippage
        
        self._positions: Dict[str, VirtualPosition] = {}
        self._orders: List[VirtualOrder] = []
        self._order_id_counter = 0
        
        # 统计数据
        self._stats = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0,
            "max_drawdown": 0,
        }
        
        # 每日统计
        self._daily_stats = defaultdict(lambda: {
            "trades": 0, "pnl": 0, "wins": 0, "losses": 0
        })
        
        logger.info(
            f"[模拟交易] 初始化完成, "
            f"初始资金: ${initial_balance:.2f}, "
            f"滑点: {slippage*100:.3f}%"
        )
        
    def _generate_order_id(self) -> str:
        """生成订单ID"""
        self._order_id_counter += 1
        return f"PAPER_{self._order_id_counter}_{int(datetime.now().timestamp())}"
        
    def _apply_slippage(self, price: float, side: str) -> float:
        """应用滑点"""
        if side == "buy":
            return price * (1 + self.slippage)
        else:
            return price * (1 - self.slippage)
            
    def _calculate_pnl(
        self,
        entry_price: float,
        exit_price: float,
        quantity: float,
        direction: str,
        leverage: int
    ) -> float:
        """
        计算盈亏
        PnL = (exit - entry) / entry * quantity * direction * leverage
        """
        if direction == "long":
            pnl = (exit_price - entry_price) / entry_price
        else:
            pnl = (entry_price - exit_price) / entry_price
            
        return pnl * leverage * quantity * entry_price
        
    def _calculate_pnl_pct(
        self,
        entry_price: float,
        exit_price: float,
        direction: str,
        leverage: int
    ) -> float:
        """计算盈亏百分比"""
        if direction == "long":
            pnl = (exit_price - entry_price) / entry_price
        else:
            pnl = (entry_price - exit_price) / entry_price
            
        return pnl * leverage
        
    def open_position(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        quantity: float,
        leverage: int = 20,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> str:
        """
        开仓（模拟）
        
        Returns:
            订单ID
        """
        order_id = self._generate_order_id()
        
        # 考虑滑点的成交价
        filled_price = self._apply_slippage(entry_price, "buy" if direction == "long" else "sell")
        
        # 记录订单
        order = VirtualOrder(
            order_id=order_id,
            symbol=symbol,
            side="buy" if direction == "long" else "sell",
            order_type="market",
            quantity=quantity,
            price=entry_price,
            filled_price=filled_price,
        )
        self._orders.append(order)
        
        # 记录持仓
        self._positions[symbol] = VirtualPosition(
            symbol=symbol,
            direction=direction,
            entry_price=filled_price,
            quantity=quantity,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit=take_profit,
            best_price=filled_price,
        )
        
        logger.info(
            f"[模拟交易] 开仓: {symbol} {direction.upper()} "
            f"数量: {quantity} 价格: ${filled_price:.4f} 杠杆: {leverage}x"
        )
        
        return order_id
        
    def close_position(
        self,
        symbol: str,
        exit_price: float,
        reason: str = "manual"
    ) -> Optional[Dict]:
        """
        平仓（模拟）
        
        Returns:
            平仓结果，包含盈亏信息
        """
        if symbol not in self._positions:
            logger.warning(f"[模拟交易] 尝试平仓不存在的持仓: {symbol}")
            return None
            
        position = self._positions[symbol]
        
        # 考虑滑点的成交价
        filled_price = self._apply_slippage(
            exit_price, 
            "sell" if position.direction == "long" else "buy"
        )
        
        # 计算盈亏
        pnl = self._calculate_pnl(
            position.entry_price,
            filled_price,
            position.quantity,
            position.direction,
            position.leverage
        )
        
        pnl_pct = self._calculate_pnl_pct(
            position.entry_price,
            filled_price,
            position.direction,
            position.leverage
        )
        
        # 更新资金
        self.balance += pnl
        
        # 更新统计
        self._stats["total_trades"] += 1
        self._stats["total_pnl"] += pnl
        
        if pnl > 0:
            self._stats["winning_trades"] += 1
        else:
            self._stats["losing_trades"] += 1
            
        # 更新回撤
        if self.balance < self.initial_balance:
            drawdown = (self.initial_balance - self.balance) / self.initial_balance
            self._stats["max_drawdown"] = max(self._stats["max_drawdown"], drawdown)
            
        # 每日统计
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily_stats[today]["trades"] += 1
        self._daily_stats[today]["pnl"] += pnl
        if pnl > 0:
            self._daily_stats[today]["wins"] += 1
        else:
            self._daily_stats[today]["losses"] += 1
            
        # 生成订单记录
        order_id = self._generate_order_id()
        order = VirtualOrder(
            order_id=order_id,
            symbol=symbol,
            side="sell" if position.direction == "long" else "buy",
            order_type="market",
            quantity=position.quantity,
            price=exit_price,
            filled_price=filled_price,
        )
        self._orders.append(order)
        
        # 移除持仓
        del self._positions[symbol]
        
        logger.info(
            f"[模拟交易] 平仓: {symbol} 原因: {reason} "
            f"盈亏: ${pnl:.2f} ({pnl_pct*100:.2f}%) "
            f"余额: ${self.balance:.2f}"
        )
        
        return {
            "order_id": order_id,
            "symbol": symbol,
            "entry_price": position.entry_price,
            "exit_price": filled_price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "reason": reason,
            "duration": (datetime.now() - position.opened_at).total_seconds(),
        }
        
    def check_stops(
        self,
        symbol: str,
        current_price: float
    ) -> Optional[Dict]:
        """
        检查止损止盈
        
        Returns:
            如果触发止损止盈，返回平仓信息
        """
        if symbol not in self._positions:
            return None
            
        position = self._positions[symbol]
        
        # 更新最佳价格
        if position.direction == "long":
            if current_price > position.best_price:
                position.best_price = current_price
        else:
            if current_price < position.best_price:
                position.best_price = current_price
                
        # 检查硬止损
        if position.stop_loss:
            if position.direction == "long" and current_price <= position.stop_loss:
                return self.close_position(symbol, current_price, "stop_loss")
            if position.direction == "short" and current_price >= position.stop_loss:
                return self.close_position(symbol, current_price, "stop_loss")
                
        # 检查止盈
        if position.take_profit:
            if position.direction == "long" and current_price >= position.take_profit:
                return self.close_position(symbol, current_price, "take_profit")
            if position.direction == "short" and current_price <= position.take_profit:
                return self.close_position(symbol, current_price, "take_profit")
                
        # 检查追踪止损
        if position.trailing_stop and position.trailing激活:
            trail_distance = position.best_price * 0.02  # 2%回撤
            if position.direction == "long":
                if current_price <= position.best_price - trail_distance:
                    return self.close_position(symbol, current_price, "trailing_stop")
            else:
                if current_price >= position.best_price + trail_distance:
                    return self.close_position(symbol, current_price, "trailing_stop")
                    
        return None
        
    def get_positions(self) -> Dict[str, VirtualPosition]:
        """获取所有持仓"""
        return self._positions.copy()
        
    def get_position(self, symbol: str) -> Optional[VirtualPosition]:
        """获取单个持仓"""
        return self._positions.get(symbol)
        
    def get_unrealized_pnl(self, symbol: str, current_price: float) -> float:
        """计算未实现盈亏"""
        position = self._positions.get(symbol)
        if not position:
            return 0
            
        return self._calculate_pnl(
            position.entry_price,
            current_price,
            position.quantity,
            position.direction,
            position.leverage
        )
        
    def get_stats(self) -> Dict[str, Any]:
        """获取统计数据"""
        win_rate = (
            self._stats["winning_trades"] / self._stats["total_trades"]
            if self._stats["total_trades"] > 0 else 0
        )
        
        avg_win = (
            self._stats["total_pnl"] / self._stats["total_trades"]
            if self._stats["total_trades"] > 0 else 0
        )
        
        return {
            **self._stats,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "balance": self.balance,
            "equity": self.balance,  # 简化，忽略未实现
            "profit": self.balance - self.initial_balance,
            "profit_pct": (self.balance - self.initial_balance) / self.initial_balance,
        }
        
    def get_daily_stats(self, date: Optional[str] = None) -> Dict:
        """获取每日统计"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        return self._daily_stats.get(date, {}).copy()
