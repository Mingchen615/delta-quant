"""
交易所抽象基类
定义统一的交易所接口，支持币安和OKX双平台
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# =============================================================================
# 数据模型
# =============================================================================

class Ticker(BaseModel):
    """行情数据"""
    symbol: str
    last: float
    bid: float
    ask: float
    high: float
    low: float
    volume: float
    quote_volume: float
    timestamp: datetime


class OrderBook(BaseModel):
    """订单簿"""
    symbol: str
    bids: List[tuple[float, float]] = []  # [(price, quantity), ...]
    asks: List[tuple[float, float]] = []
    timestamp: datetime


class Kline(BaseModel):
    """K线数据"""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    timeframe: str = "1h"


class AccountBalance(BaseModel):
    """账户余额"""
    total: float  # 总资产 (USDT)
    free: float   # 可用余额
    used: float   # 冻结余额
    unrealized_pnl: float = 0  # 未实现盈亏


class Position(BaseModel):
    """持仓信息"""
    symbol: str
    side: str  # "long" / "short"
    contracts: float  # 合约数量
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int
    margin_mode: str = "cross"  # "cross" / "isolated"
    liquidation_price: Optional[float] = None
    timestamp: datetime


class Order(BaseModel):
    """订单信息"""
    order_id: str
    exchange: str
    symbol: str
    side: str  # "buy" / "sell"
    order_type: str  # "market" / "limit"
    amount: float
    price: Optional[float] = None
    status: str  # "open" / "filled" / "canceled" / "closed"
    filled: float = 0
    average: float = 0
    fee: float = 0
    timestamp: datetime


class OrderParams(BaseModel):
    """下单参数"""
    symbol: str
    side: str  # "buy" / "sell"
    order_type: str = "market"  # "market" / "limit"
    amount: float
    price: Optional[float] = None
    leverage: int = 20
    margin_mode: str = "cross"  # "cross" / "isolated"
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    exchange: str = "auto"  # "binance" / "okx" / "auto"


# =============================================================================
# 交易所抽象基类
# =============================================================================

class BaseExchange(ABC):
    """交易所统一接口"""

    def __init__(self):
        self._connected = False

    @property
    @abstractmethod
    def exchange_name(self) -> str:
        """交易所名称: "binance" / "okx" """
        pass

    @property
    @abstractmethod
    def supported_symbols(self) -> List[str]:
        """支持的交易对"""
        pass

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected

    # --- 连接管理 ---

    @abstractmethod
    async def connect(self) -> bool:
        """建立连接，返回是否成功"""
        pass

    @abstractmethod
    async def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    async def check_connection(self) -> bool:
        """心跳检测，返回连接是否正常"""
        pass

    # --- 账户 ---

    @abstractmethod
    async def get_balance(self) -> AccountBalance:
        """获取账户余额"""
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """获取当前持仓"""
        pass

    # --- 行情 ---

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """获取最新价格"""
        pass

    @abstractmethod
    async def get_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        """获取订单簿"""
        pass

    @abstractmethod
    async def get_klines(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> List[Kline]:
        """获取K线数据"""
        pass

    # --- 交易 ---

    @abstractmethod
    async def create_order(self, params: OrderParams) -> Order:
        """下单"""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤单"""
        pass

    @abstractmethod
    async def get_order(self, order_id: str, symbol: str) -> Order:
        """查询订单"""
        pass

    # --- 杠杆 ---

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """设置杠杆"""
        pass

    @abstractmethod
    async def set_margin_mode(self, symbol: str, mode: str) -> bool:
        """设置保证金模式: cross/isolated"""
        pass

    # --- 扫码接入 ---

    @abstractmethod
    def generate_qr_url(self) -> str:
        """生成扫码URL（跳转交易所API创建页面）"""
        pass

    @abstractmethod
    async def verify_credentials(self) -> bool:
        """验证API Key有效性（调用get_balance测试）"""
        pass
