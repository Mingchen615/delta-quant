"""
市场数据管理
提供行情数据获取、缓存、管理
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass
from loguru import logger


@dataclass
class Ticker:
    """行情数据"""
    symbol: str
    price: float
    volume_24h: float
    quote_volume_24h: float
    price_change_24h: float
    price_change_pct_24h: float
    high_24h: float
    low_24h: float
    timestamp: datetime


@dataclass
class OrderBook:
    """订单簿"""
    symbol: str
    bids: List[tuple[float, float]]  # [(price, qty), ...]
    asks: List[tuple[float, float]]
    last_update_id: int
    timestamp: datetime


@dataclass
class Kline:
    """K线数据"""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    timeframe: str
    closed: bool


class MarketDataManager:
    """
    市场数据管理器
    提供统一的数据访问接口和缓存
    """
    
    def __init__(self):
        self._tickers: Dict[str, Ticker] = {}
        self._orderbooks: Dict[str, OrderBook] = {}
        self._klines: Dict[str, Dict[str, List[Kline]]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._last_update: Dict[str, datetime] = {}
        
    async def update_ticker(self, ticker: Ticker):
        """更新行情数据"""
        async with self._lock:
            self._tickers[ticker.symbol] = ticker
            self._last_update[ticker.symbol] = datetime.now()
            
    async def update_orderbook(self, orderbook: OrderBook):
        """更新订单簿"""
        async with self._lock:
            self._orderbooks[orderbook.symbol] = orderbook
            
    async def update_kline(self, kline: Kline):
        """更新K线数据"""
        async with self._lock:
            tf_dict = self._klines[kline.symbol]
            if kline.timeframe not in tf_dict:
                tf_dict[kline.timeframe] = []
            tf_dict[kline.timeframe].append(kline)
            
            # 保持最多1000根K线
            if len(tf_dict[kline.timeframe]) > 1000:
                tf_dict[kline.timeframe] = tf_dict[kline.timeframe][-1000:]
                
    def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """获取行情"""
        return self._tickers.get(symbol)
    
    def get_orderbook(self, symbol: str) -> Optional[OrderBook]:
        """获取订单簿"""
        return self._orderbooks.get(symbol)
    
    def get_klines(
        self, 
        symbol: str, 
        timeframe: str, 
        limit: Optional[int] = None
    ) -> List[Kline]:
        """获取K线"""
        klines = self._klines.get(symbol, {}).get(timeframe, [])
        if limit:
            return klines[-limit:]
        return klines
        
    def get_top_symbols(self, n: int = 40, quote: str = "USDT") -> List[str]:
        """
        获取Top N交易量币种
        
        Args:
            n: 数量
            quote: 报价货币
            
        Returns:
            币种列表
        """
        # 按24h成交量排序
        sorted_tickers = sorted(
            self._tickers.values(),
            key=lambda x: x.quote_volume_24h,
            reverse=True
        )
        
        result = []
        for ticker in sorted_tickers:
            if ticker.symbol.endswith(quote):
                result.append(ticker.symbol)
                if len(result) >= n:
                    break
                    
        return result
        
    def get_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        ticker = self._tickers.get(symbol)
        return ticker.price if ticker else None
        
    def get_orderbook_imbalance(self, symbol: str) -> Optional[float]:
        """
        计算订单簿不平衡度
        返回: -1(全是卖) ~ 1(全是买)
        """
        ob = self._orderbooks.get(symbol)
        if not ob or not ob.bids or not ob.asks:
            return None
            
        bid_vol = sum(qty for _, qty in ob.bids[:20])
        ask_vol = sum(qty for _, qty in ob.asks[:20])
        
        total = bid_vol + ask_vol
        if total == 0:
            return 0
            
        return (bid_vol - ask_vol) / total
        
    def clear_cache(self, symbol: Optional[str] = None):
        """清空缓存"""
        if symbol:
            self._klines.pop(symbol, None)
            self._tickers.pop(symbol, None)
            self._orderbooks.pop(symbol, None)
        else:
            self._klines.clear()
            self._tickers.clear()
            self._orderbooks.clear()


# 全局市场数据管理器
market_data_manager = MarketDataManager()
