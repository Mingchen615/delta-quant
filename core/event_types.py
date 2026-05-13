"""
事件类型定义
使用Pydantic进行数据模型定义
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field


class EventType(str, Enum):
    """事件类型枚举"""
    # 市场数据
    MARKET_DATA = "market_data"
    KLINE = "kline"
    ORDERBOOK = "orderbook"
    TRADE = "trade"
    AGG_TRADE = "agg_trade"
    
    # 信号与决策
    SIGNAL = "signal"
    DEBATE = "debate"
    TRADE_PROPOSAL = "trade_proposal"
    
    # 风控
    RISK_CHECK = "risk_check"
    PORTFOLIO_CHECK = "portfolio_check"
    
    # 订单
    ORDER_REQUEST = "order_request"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_FAILED = "order_failed"
    
    # 持仓
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_UPDATED = "position_updated"
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    TAKE_PROFIT_TRIGGERED = "take_profit_triggered"
    
    # Agent状态
    AGENT_STATUS = "agent_status"
    AGENT_ERROR = "agent_error"
    
    # 数据采集
    WHALE_ACTIVITY = "whale_activity"
    SENTIMENT = "sentiment"
    CORRELATION = "correlation"
    ORDER_FLOW = "order_flow"
    REGIME = "regime"


class MarketDataEvent(BaseModel):
    """市场数据事件"""
    event_type: EventType = EventType.MARKET_DATA
    symbol: str
    timestamp: datetime = Field(default_factory=datetime.now)
    price: float
    volume: float = 0
    quote_volume: float = 0
    data_type: str = "trade"  # trade, kline, orderbook


class KlineEvent(BaseModel):
    """K线数据事件"""
    event_type: EventType = EventType.KLINE
    symbol: str
    timestamp: datetime
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    timeframe: str = "1m"
    closed: bool = True


class OrderBookEvent(BaseModel):
    """订单簿事件"""
    event_type: EventType = EventType.ORDERBOOK
    symbol: str
    timestamp: datetime
    bids: List[tuple[float, float]] = []  # [(price, quantity), ...]
    asks: List[tuple[float, float]] = []  # [(price, quantity), ...]
    last_update_id: int = 0


class SignalEvent(BaseModel):
    """信号事件 - 包含9因子评分"""
    event_type: EventType = EventType.SIGNAL
    symbol: str
    direction: str  # "long" or "short"
    score: float = 0  # 0-100
    confidence: float = 0  # 0-100
    
    # 9因子分数
    factor_scores: Dict[str, float] = {}
    factor_weights: Dict[str, float] = {}
    
    # 因子详情
    trend_score: float = 0
    momentum_score: float = 0
    volatility_score: float = 0
    volume_score: float = 0
    oi_score: float = 0
    funding_rate_score: float = 0
    liquidation_score: float = 0
    mtf_score: float = 0
    sentiment_score: float = 0
    
    # 多时间框架信号
    mtf_signals: Dict[str, str] = {}  # {"15m": "long", "1h": "long", "4h": "neutral"}
    
    timestamp: datetime = Field(default_factory=datetime.now)
    is_mainstream: bool = True  # 是否为主流币


class DebateEvent(BaseModel):
    """辩论事件 - DeepSeek多空辩论"""
    event_type: EventType = EventType.DEBATE
    symbol: str
    direction: str  # "long" or "short"
    signal_score: float
    
    # 辩论结果
    approved: bool = False
    confidence: float = 0  # 0-100
    
    # Bull论证
    bull_arguments: List[str] = []
    bull_confidence: float = 0
    
    # Bear论证
    bear_arguments: List[str] = []
    bear_confidence: float = 0
    
    # 综合判断
    summary: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class TradeProposal(BaseModel):
    """交易提案 - 仓位决策输出"""
    event_type: EventType = EventType.TRADE_PROPOSAL
    
    symbol: str
    direction: str  # "long" or "short"
    
    # 仓位参数
    leverage: int = 20
    position_pct: float = 0.03  # 账户比例 3%
    
    # 止损止盈
    stop_loss_pct: float = -0.05  # -5%
    take_profit_pct: float = 0.20  # 20%
    
    # R:R
    risk_reward_ratio: float = 4.0
    
    # 信号来源
    signal_score: float = 0
    debate_confidence: float = 0
    mtf_confirmed: bool = False
    
    timestamp: datetime = Field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None  # 信号过期时间


class RiskCheckResult(BaseModel):
    """风控检查结果"""
    event_type: EventType = EventType.RISK_CHECK
    
    symbol: str
    proposal: TradeProposal
    
    approved: bool = False
    reasons: List[str] = []
    rejected_reasons: List[str] = []
    
    # 检查项
    check_single_risk: bool = True  # 单笔风险
    check_daily_risk: bool = True   # 日风险
    check_drawdown: bool = True     # 回撤检查
    check_position_limit: bool = True  # 持仓限制
    
    # 当前风险值
    current_single_risk: float = 0
    current_daily_risk: float = 0
    current_drawdown: float = 0
    current_positions: int = 0
    
    timestamp: datetime = Field(default_factory=datetime.now)


class OrderEvent(BaseModel):
    """订单事件"""
    event_type: EventType
    order_id: Optional[str] = None
    symbol: str
    direction: str
    order_type: str  # "market", "limit"
    side: str  # "buy", "sell"
    
    # 订单参数
    price: Optional[float] = None
    quantity: Optional[float] = None
    quote_quantity: Optional[float] = None
    leverage: int = 20
    
    # 执行结果
    status: str = "pending"  # pending, submitted, filled, cancelled, failed
    filled_quantity: float = 0
    avg_fill_price: float = 0
    commission: float = 0
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    error: Optional[str] = None


class PositionEvent(BaseModel):
    """持仓事件"""
    event_type: EventType
    symbol: str
    direction: str  # "long" or "short"
    
    # 持仓信息
    entry_price: float
    quantity: float
    leverage: int
    unrealized_pnl: float = 0
    unrealized_pnl_pct: float = 0
    
    # 止损止盈
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    # 追踪止损
    trailing_stop: bool = False
    trailing激活: bool = False
    
    # 状态
    status: str = "open"  # open, closed, liquidated
    close_reason: Optional[str] = None
    realized_pnl: float = 0
    
    # 时间
    opened_at: datetime = Field(default_factory=datetime.now)
    closed_at: Optional[datetime] = None
    
    # R数
    current_r: float = 0
    
    metadata: Dict[str, Any] = {}


class AgentStatusEvent(BaseModel):
    """Agent状态事件"""
    event_type: EventType = EventType.AGENT_STATUS
    agent_name: str
    state: str  # "idle", "running", "stopped", "failed"
    last_execution: Optional[datetime] = None
    error_count: int = 0
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class WhaleActivityEvent(BaseModel):
    """鲸鱼活动事件"""
    event_type: EventType = EventType.WHALE_ACTIVITY
    symbol: str
    direction: str  # "buy" or "sell"
    quantity: float
    price: float
    quote_quantity: float  # USDT价值
    is_buyer_maker: bool = False
    timestamp: datetime = Field(default_factory=datetime.now)


class SentimentEvent(BaseModel):
    """情绪事件"""
    event_type: EventType = EventType.SENTIMENT
    symbol: Optional[str] = None  # None表示全局
    sentiment: str  # "bullish", "bearish", "neutral"
    score: float = 0  # -1 to 1
    sources: List[str] = []
    timestamp: datetime = Field(default_factory=datetime.now)


class CorrelationEvent(BaseModel):
    """相关性事件"""
    event_type: EventType = EventType.CORRELATION
    correlations: Dict[str, float] = {}  # symbol -> correlation with BTC
    sector_strength: Dict[str, float] = {}  # sector -> strength
    btc_dominance: float = 0
    timestamp: datetime = Field(default_factory=datetime.now)


class OrderFlowEvent(BaseModel):
    """订单流事件"""
    event_type: EventType = EventType.ORDER_FLOW
    symbol: str
    imbalance: float = 0  # -1 to 1
    bid_volume: float = 0
    ask_volume: float = 0
    large_bids: List[tuple[float, float]] = []  # [(price, qty), ...]
    large_asks: List[tuple[float, float]] = []   # [(price, qty), ...]
    timestamp: datetime = Field(default_factory=datetime.now)


class RegimeEvent(BaseModel):
    """市场状态事件"""
    event_type: EventType = EventType.REGIME
    regime: str  # "trend", "ranging", "high_volatility"
    adx: float = 0
    atr: float = 0
    atr_percentile: float = 0  # ATR在历史中的百分位
    timestamp: datetime = Field(default_factory=datetime.now)
