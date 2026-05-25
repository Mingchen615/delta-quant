"""
全局配置文件
所有配置参数集中管理
"""

import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# =============================================================================
# .env 文件读取（手写解析，优先于环境变量）
# =============================================================================
def _load_env_file():
    """从项目根目录的 .env 文件读取配置"""
    env_path = PROJECT_ROOT / ".env"
    env_vars = {}
    
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释
                if not line or line.startswith("#"):
                    continue
                # 解析 KEY=VALUE 格式
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
    
    return env_vars

# 读取 .env 文件
_dotenv = _load_env_file()

def _get_config(key, default=""):
    """获取配置：.env > 环境变量 > 默认值"""
    # 1. 优先从 .env 文件读取
    if key in _dotenv and _dotenv[key]:
        return _dotenv[key]
    # 2. 其次从环境变量读取
    env_value = os.getenv(key)
    if env_value:
        return env_value
    # 3. 最后使用默认值
    return default

# =============================================================================
# 币安API配置
# =============================================================================
BINANCE_API_KEY = _get_config("BINANCE_API_KEY", "")
BINANCE_API_SECRET = _get_config("BINANCE_API_SECRET", "")
BINANCE_TESTNET = False  # 默认开启模拟盘

# 代理配置（国内用户本地Windows需要开启）
USE_PROXY = _get_config("USE_PROXY", "false").lower() == "true"
PROXY_URL = _get_config("PROXY_URL", "http://127.0.0.1:7890")

# Testnet API endpoints
BINANCE_TESTNET_API = "https://testnet.binance.vision/api"
BINANCE_TESTNET_WS = "wss://testnet.binance.vision/ws"

# =============================================================================
# DeepSeek API配置
# =============================================================================
DEEPSEEK_API_KEY = _get_config("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# =============================================================================
# 风控参数
# =============================================================================
RISK_PER_TRADE = 0.03       # 单笔最大亏损 (3%)
RISK_PER_DAY = 0.05         # 日最大亏损 (5%)
MAX_DRAWDOWN = 0.15         # 最大回撤 (15%, v3收紧)
MAX_POSITIONS = 3           # 最大同时持仓数 (v3调整)

# =============================================================================
# 杠杆参数
# =============================================================================
BASE_LEVERAGE = 5          # 基础杠杆 (v3降低)
MAX_LEVERAGE = 20          # 最大杠杆 (v3硬上限)
LEVERAGE_STEP = 5          # 杠杆步进

# =============================================================================
# 扫描参数
# =============================================================================
SCAN_INTERVAL = 300        # 主扫描间隔 (秒, 5分钟)
SCAN_TOP_N = 40            # 扫描Top N币种
SIGNAL_THRESHOLD_MAIN = 45 # 主流币信号阈值
SIGNAL_THRESHOLD_ALT = 50  # 山寨币信号阈值

# =============================================================================
# 止损止盈参数
# =============================================================================
HARD_STOP_LOSS = -0.25     # 硬止损 (保证金维度, -25%)
SOFT_STOP_LOSS = -0.05     # 软止损 (5%)
TIME_STOP_SECONDS = 180    # 时间止损 (3分钟)
TRAILING_STOP_TRIGGER = 1  # 追踪止损触发R数
TRAILING_STOP_DISTANCE = 1 # 追踪止损回撤距离(R)

# 止盈目标
TP1_RATIO = 2              # 第一止盈目标 (2R)
TP2_RATIO = 3              # 第二止盈目标 (3R) 
TP3_RATIO = 5              # 第三止盈目标 (5R+)

# =============================================================================
# 新闻数据配置
# =============================================================================
CRYPTOPANIC_API_KEY = _get_config("CRYPTOPANIC_API_KEY", "")
CRYPTOPANIC_API_URL = "https://cryptopanic.com/api/free/v1/posts/"

# =============================================================================
# 鲸鱼监控配置
# =============================================================================
WHALE_THRESHOLD_USDT = 500_000  # 鲸鱼门槛 (50万USDT)

# =============================================================================
# 订单流配置
# =============================================================================
ORDERBOOK_DEPTH = 20       # 订单簿深度
ORDERBOOK_IMBALANCE_THRESHOLD = 0.3  # 订单簿不平衡阈值

# =============================================================================
# 数据库配置
# =============================================================================
DATABASE_PATH = PROJECT_ROOT / "data" / "delta_quant.db"

# =============================================================================
# 日志配置
# =============================================================================
LOG_LEVEL = "INFO"
LOG_ROTATION = "100 MB"
LOG_RETENTION = "7 days"
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

# =============================================================================
# Agent运行配置
# =============================================================================
AGENT_RESTART_MAX = 3          # Agent最大重启次数
AGENT_HEARTBEAT_INTERVAL = 30   # 心跳检测间隔 (秒)
AGENT_STATUS_REPORT_INTERVAL = 60  # 状态上报间隔 (秒)

# =============================================================================
# 技术指标参数
# =============================================================================
EMA_SHORT = 9          # 短期EMA周期
EMA_MID = 21           # 中期EMA周期
EMA_LONG = 55          # 长期EMA周期
RSI_PERIOD = 14        # RSI周期
MACD_FAST = 12         # MACD快线周期
MACD_SLOW = 26         # MACD慢线周期
MACD_SIGNAL = 9        # MACD信号线周期
BOLL_PERIOD = 20       # 布林带周期
BOLL_STD = 2           # 布林带标准差倍数
ATR_PERIOD = 14        # ATR周期
ADX_PERIOD = 14        # ADX周期

# =============================================================================
# 多时间框架配置
# =============================================================================
MTF_TIMEFRAMES = ["1h", "4h", "1d"]  # 多时间框架列表
MTF_WEIGHTS = {"1h": 0.2, "4h": 0.3, "1d": 0.5}  # 各周期权重

# =============================================================================
# 相关性计算配置
# =============================================================================
CORRELATION_LOOKBACK = 100      # 相关性计算回溯周期
CORRELATION_THRESHOLD = 0.7     # 相关性阈值
SECTOR_THRESHOLD = 0.6         # 板块相关性阈值

# =============================================================================
# 市场状态阈值
# =============================================================================
ADX_TREND_THRESHOLD = 25        # 趋势市场ADX阈值
ADX_RANGING_THRESHOLD = 20      # 震荡市场ADX阈值
ATR_MULTIPLIER_HIGH = 2.0       # 高波动ATR倍数

# =============================================================================
# 辩论Agent配置
# =============================================================================
DEBATE_CONFIDENCE_THRESHOLD = 0.5  # 辩论置信度阈值 (0.5=中性，低于此值拒绝)
DEBATE_TIMEOUT = 30             # 辩论超时时间 (秒)

# =============================================================================
# 信号因子权重
# =============================================================================
FACTOR_WEIGHTS = {
    "delta": 0.25,
    "momentum": 0.20,
    "whale": 0.15,
    "orderflow": 0.15,
    "sentiment": 0.15,
    "correlation": 0.10,
}

# =============================================================================
# v9.0 - 双平台配置
# =============================================================================

# 实盘模式开关（运行时可切换）
LIVE_TRADE = _get_config("LIVE_TRADE", "false").lower() == "true"

def set_live_trade(value: bool):
    """运行时切换实盘/模拟盘模式"""
    global LIVE_TRADE
    LIVE_TRADE = value
    import logging
    logging.getLogger("config").warning(
        f"{'🔴 实盘模式' if value else '🟢 模拟盘模式'} 已启用"
    )

def toggle_live_trade() -> bool:
    """切换模式，返回新模式"""
    set_live_trade(not LIVE_TRADE)
    return LIVE_TRADE

# 欧易API配置
OKX_API_KEY = _get_config("OKX_API_KEY", "")
OKX_API_SECRET = _get_config("OKX_API_SECRET", "")
OKX_PASSPHRASE = _get_config("OKX_PASSPHRASE", "")

# 手续费率
BINANCE_FEE_RATE = 0.0004   # 币安合约手续费 0.04%
OKX_FEE_RATE = 0.0005        # OKX合约手续费 0.05%

# 默认交易所选择: "auto" / "binance" / "okx"
DEFAULT_EXCHANGE = _get_config("DEFAULT_EXCHANGE", "auto")

# 套利配置
ARBITRAGE_THRESHOLD = 0.003   # 套利价差阈值 0.3%（含手续费）
ARBITRAGE_INTERVAL = 1        # 套利检查间隔（秒）

# Web服务配置
WEB_HOST = _get_config("WEB_HOST", "0.0.0.0")
WEB_PORT = int(_get_config("WEB_PORT", "8000"))

# 加密存储主密码（生产环境从环境变量获取）
MASTER_PASSWORD = _get_config("MASTER_PASSWORD", "")

# =============================================================================
# v3.0 交易规则配置
# =============================================================================
TRADING_V3 = {
    # 开仓门槛
    'min_signal_strength': 70,      # 信号强度阈值
    'min_vol_ratio': 1.0,           # 成交量门槛
    'min_adx': 20,                  # ADX趋势强度门槛

    # 止损止盈
    'atr_sl_multiplier': 1.5,       # ATR止损倍数
    'atr_tp_multiplier': 3.0,       # ATR止盈倍数
    'atr_period': 14,               # ATR计算周期
    'sl_min_pct': 0.01,             # 止损下限1%
    'sl_max_pct': 0.05,             # 止损上限5%
    'tp_min_pct': 0.02,             # 止盈下限2%
    'tp_max_pct': 0.15,             # 止盈上限15%

    # 移动止盈
    'trailing_trigger': 0.50,       # 盈利50%激活
    'trailing_step': 0.30,          # 回撤30%平仓

    # 杠杆
    'base_leverage': 5,             # 基础杠杆5x
    'max_leverage': 20,             # 硬上限20x

    # 仓位
    'max_position_pct': 0.10,       # 单笔最大10%

    # 风控
    'daily_loss_limit': 0.05,       # 日亏5%停
    'max_drawdown': 0.15,           # 回撤15%停
    'max_positions': 3,             # 最大3持仓

    # RSI背离周期
    'rsi_divergence_lookback': 20,  # RSI背离用20根K线对比
}
