"""
Delta Quant - 13 Agent量化交易系统
异步架构的加密货币量化交易框架
"""

__version__ = "9.0.0"
__author__ = "Delta Quant Team"

from .settings import (
    # 项目配置
    PROJECT_ROOT,
    # 币安API配置
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    BINANCE_TESTNET,
    BINANCE_TESTNET_API,
    BINANCE_TESTNET_WS,
    # DeepSeek API配置
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL,
    DEEPSEEK_MODEL,
    # 风控参数
    RISK_PER_TRADE,
    RISK_PER_DAY,
    MAX_DRAWDOWN,
    MAX_POSITIONS,
    # 杠杆参数
    BASE_LEVERAGE,
    MAX_LEVERAGE,
    LEVERAGE_STEP,
    # 扫描参数
    SCAN_INTERVAL,
    SCAN_TOP_N,
    SIGNAL_THRESHOLD_MAIN,
    SIGNAL_THRESHOLD_ALT,
    # 止损止盈参数
    HARD_STOP_LOSS,
    SOFT_STOP_LOSS,
    TIME_STOP_SECONDS,
    TRAILING_STOP_TRIGGER,
    TRAILING_STOP_DISTANCE,
    TP1_RATIO,
    TP2_RATIO,
    TP3_RATIO,
    # 新闻数据配置
    CRYPTOPANIC_API_KEY,
    CRYPTOPANIC_API_URL,
    # 鲸鱼监控配置
    WHALE_THRESHOLD_USDT,
    # 订单流配置
    ORDERBOOK_DEPTH,
    ORDERBOOK_IMBALANCE_THRESHOLD,
    # 数据库配置
    DATABASE_PATH,
    # 日志配置
    LOG_LEVEL,
    LOG_ROTATION,
    LOG_RETENTION,
    LOG_FORMAT,
    # Agent运行配置
    AGENT_RESTART_MAX,
    AGENT_HEARTBEAT_INTERVAL,
    AGENT_STATUS_REPORT_INTERVAL,
    # 技术指标参数
    EMA_SHORT,
    EMA_MID,
    EMA_LONG,
    RSI_PERIOD,
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
    BOLL_PERIOD,
    BOLL_STD,
    ATR_PERIOD,
    ADX_PERIOD,
    # 多时间框架配置
    MTF_TIMEFRAMES,
    MTF_WEIGHTS,
    # 相关性计算配置
    CORRELATION_LOOKBACK,
    CORRELATION_THRESHOLD,
    SECTOR_THRESHOLD,
    # 市场状态阈值
    ADX_TREND_THRESHOLD,
    ADX_RANGING_THRESHOLD,
    ATR_MULTIPLIER_HIGH,
    # 辩论Agent配置
    DEBATE_CONFIDENCE_THRESHOLD,
    DEBATE_TIMEOUT,
    # 信号因子权重
    FACTOR_WEIGHTS,
    # 代理配置
    USE_PROXY,
    PROXY_URL,
    # v9.0 双平台配置
    LIVE_TRADE,
    set_live_trade,
    toggle_live_trade,
    OKX_API_KEY,
    OKX_API_SECRET,
    OKX_PASSPHRASE,
    BINANCE_FEE_RATE,
    OKX_FEE_RATE,
    DEFAULT_EXCHANGE,
    ARBITRAGE_THRESHOLD,
    ARBITRAGE_INTERVAL,
    WEB_HOST,
    WEB_PORT,
    MASTER_PASSWORD,
    TRADING_V3,
)

__all__ = [
    # 项目配置
    "PROJECT_ROOT",
    # 币安API配置
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_TESTNET",
    "BINANCE_TESTNET_API",
    "BINANCE_TESTNET_WS",
    # DeepSeek API配置
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_URL",
    "DEEPSEEK_MODEL",
    # 风控参数
    "RISK_PER_TRADE",
    "RISK_PER_DAY",
    "MAX_DRAWDOWN",
    "MAX_POSITIONS",
    # 杠杆参数
    "BASE_LEVERAGE",
    "MAX_LEVERAGE",
    "LEVERAGE_STEP",
    # 扫描参数
    "SCAN_INTERVAL",
    "SCAN_TOP_N",
    "SIGNAL_THRESHOLD_MAIN",
    "SIGNAL_THRESHOLD_ALT",
    # 止损止盈参数
    "HARD_STOP_LOSS",
    "SOFT_STOP_LOSS",
    "TIME_STOP_SECONDS",
    "TRAILING_STOP_TRIGGER",
    "TRAILING_STOP_DISTANCE",
    "TP1_RATIO",
    "TP2_RATIO",
    "TP3_RATIO",
    # 新闻数据配置
    "CRYPTOPANIC_API_KEY",
    "CRYPTOPANIC_API_URL",
    # 鲸鱼监控配置
    "WHALE_THRESHOLD_USDT",
    # 订单流配置
    "ORDERBOOK_DEPTH",
    "ORDERBOOK_IMBALANCE_THRESHOLD",
    # 数据库配置
    "DATABASE_PATH",
    # 日志配置
    "LOG_LEVEL",
    "LOG_ROTATION",
    "LOG_RETENTION",
    "LOG_FORMAT",
    # Agent运行配置
    "AGENT_RESTART_MAX",
    "AGENT_HEARTBEAT_INTERVAL",
    "AGENT_STATUS_REPORT_INTERVAL",
    # 技术指标参数
    "EMA_SHORT",
    "EMA_MID",
    "EMA_LONG",
    "RSI_PERIOD",
    "MACD_FAST",
    "MACD_SLOW",
    "MACD_SIGNAL",
    "BOLL_PERIOD",
    "BOLL_STD",
    "ATR_PERIOD",
    "ADX_PERIOD",
    # 多时间框架配置
    "MTF_TIMEFRAMES",
    "MTF_WEIGHTS",
    # 相关性计算配置
    "CORRELATION_LOOKBACK",
    "CORRELATION_THRESHOLD",
    "SECTOR_THRESHOLD",
    # 市场状态阈值
    "ADX_TREND_THRESHOLD",
    "ADX_RANGING_THRESHOLD",
    "ATR_MULTIPLIER_HIGH",
    # 辩论Agent配置
    "DEBATE_CONFIDENCE_THRESHOLD",
    "DEBATE_TIMEOUT",
    # 信号因子权重
    "FACTOR_WEIGHTS",
    # 代理配置
    "USE_PROXY",
    "PROXY_URL",
    # v9.0 双平台配置
    "LIVE_TRADE",
    "set_live_trade",
    "toggle_live_trade",
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_PASSPHRASE",
    "BINANCE_FEE_RATE",
    "OKX_FEE_RATE",
    "DEFAULT_EXCHANGE",
    "ARBITRAGE_THRESHOLD",
    "ARBITRAGE_INTERVAL",
    "WEB_HOST",
    "WEB_PORT",
    "MASTER_PASSWORD",
    "TRADING_V3",
]
