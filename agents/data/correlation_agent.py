"""
3. 品种相关性计算 Agent
计算币种相关性，检测板块轮动
"""

import asyncio
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import CorrelationEvent
from exchange.binance_client import binance_client
from data.market_data import market_data_manager
from config import CORRELATION_LOOKBACK, CORRELATION_THRESHOLD


class CorrelationAgent(BaseAgent):
    """
    相关性计算Agent
    - 计算Top40币种与BTC的相关性
    - 板块轮动检测
    - BTC主导率监控
    """

    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="相关性计算",
            log_prefix="[相关性计算]",
            interval=300,  # 5分钟
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)

        self._correlation_matrix: Dict[str, float] = {}
        self._sector_strength: Dict[str, float] = {}
        self._exchange_router = None

    def set_router(self, router):
        """设置交易所路由器"""
        self._exchange_router = router
        
        # 板块定义
        self._sectors = {
            "DeFi": ["UNI", "AAVE", "COMP", "SUSHI", "CRV", "MKR", "SNX"],
            "L2": ["ARB", "OP", "MATIC", "IMX", "LOOP"],
            "L1": ["ETH", "SOL", "ADA", "AVAX", "DOT", "NEAR", "ALGO"],
            "Meme": ["DOGE", "SHIB", "PEPE", "FLOKI"],
            "GameFi": ["AXS", "SAND", "MANA", "ENJ", "GALA"],
            "AI": ["FET", "AGIX", "OCEAN", "RNDR"],
        }
        
    async def execute(self):
        """计算相关性"""
        self.logger.debug("开始计算相关性...")
        
        try:
            # 获取Top币种
            symbols = await self._get_top_symbols()
            
            if not symbols:
                self.logger.warning("无法获取交易对列表")
                return
                
            # 计算与BTC的相关性
            correlations = await self._calculate_correlations(symbols)
            
            # 计算板块强度
            sector_strength = self._calculate_sector_strength(correlations)
            
            # 计算BTC主导率
            btc_dominance = self._calculate_btc_dominance(symbols)
            
            # 创建事件
            event = CorrelationEvent(
                correlations=correlations,
                sector_strength=sector_strength,
                btc_dominance=btc_dominance,
                timestamp=datetime.now(),
            )
            
            # 发布
            await self.publish("correlation", event)
            
            # 记录
            self._correlation_matrix = correlations
            self._sector_strength = sector_strength
            
            self.logger.info(
                f"相关性计算完成: BTC主导率 {btc_dominance:.1%}, "
                f"最强板块: {max(sector_strength.items(), key=lambda x: x[1])[0] if sector_strength else 'N/A'}"
            )
            
        except Exception as e:
            self.logger.error(f"相关性计算出错: {e}")
            
    async def _fetch_klines(self, symbol: str, timeframe: str, limit: int) -> list:
        """从路由器获取K线数据"""
        if self._exchange_router:
            for name, ex in self._exchange_router.exchanges.items():
                if ex.is_connected:
                    try:
                        klines = await ex.get_klines(symbol, timeframe, limit)
                        return [
                            [int(k.timestamp.timestamp() * 1000), k.open, k.high, k.low, k.close, k.volume]
                            for k in klines
                        ]
                    except Exception:
                        continue
            return []
        return await binance_client.fetch_klines(symbol, timeframe, limit)

    async def _get_top_symbols(self) -> List[str]:
        """获取Top交易对"""
        if self._exchange_router:
            for name, ex in self._exchange_router.exchanges.items():
                if ex.is_connected:
                    try:
                        return [s for s in ex.supported_symbols if ":USDT" in s][:40]
                    except Exception:
                        continue
            return []
        try:
            markets = await binance_client.fetch_markets()
            symbols = [m["symbol"] for m in markets if m["quote"] == "USDT" and m["type"] == "future"]
            return symbols[:40]
        except Exception as e:
            self.logger.error(f"获取交易对失败: {e}")
            return []
            
    async def _calculate_correlations(self, symbols: List[str]) -> Dict[str, float]:
        """计算与BTC的相关性"""
        correlations = {}

        # 获取BTC价格序列
        btc_klines = await self._fetch_klines("BTC/USDT:USDT", "1h", CORRELATION_LOOKBACK)

        if not btc_klines:
            return correlations

        btc_closes = [k[4] for k in btc_klines]

        # 计算BTC收益率
        btc_returns = np.diff(btc_closes) / btc_closes[:-1]

        for symbol in symbols:
            if "BTC" in symbol:
                continue

            try:
                klines = await self._fetch_klines(symbol, "1h", CORRELATION_LOOKBACK)
                
                if len(klines) < 50:
                    continue
                    
                closes = [k[4] for k in klines]
                returns = np.diff(closes) / closes[:-1]
                
                # 对齐长度
                min_len = min(len(btc_returns), len(returns))
                corr = np.corrcoef(btc_returns[-min_len:], returns[-min_len:])[0, 1]
                
                correlations[symbol] = float(corr) if not np.isnan(corr) else 0
                
            except Exception as e:
                self.logger.debug(f"计算{symbol}相关性失败: {e}")
                continue
                
        return correlations
        
    def _calculate_sector_strength(self, correlations: Dict[str, float]) -> Dict[str, float]:
        """
        计算板块强度
        板块强度 = 板块内与BTC高相关(>0.7)币种的比例
        """
        strength = {}
        
        for sector, coins in self._sectors.items():
            high_corr_count = 0
            total_count = 0
            
            for coin in coins:
                symbol = f"{coin}/USDT"
                corr = correlations.get(symbol, 0)
                
                if abs(corr) > 0.3:  # 有足够的数据
                    total_count += 1
                    if corr > CORRELATION_THRESHOLD:
                        high_corr_count += 1
                        
            if total_count > 0:
                strength[sector] = high_corr_count / total_count
            else:
                strength[sector] = 0
                
        return strength
        
    def _calculate_btc_dominance(self, symbols: List[str]) -> float:
        """计算BTC主导率"""
        # 简化：BTC与整体市场平均相关性
        if not self._correlation_matrix:
            return 0.5
            
        corrs = list(self._correlation_matrix.values())
        if not corrs:
            return 0.5
            
        return np.mean(corrs)
        
    def get_top_correlated(self, n: int = 5) -> List[tuple]:
        """获取与BTC最相关的币种"""
        sorted_corrs = sorted(
            self._correlation_matrix.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )
        return sorted_corrs[:n]
        
    def get_leading_sector(self) -> Optional[str]:
        """获取主导板块"""
        if not self._sector_strength:
            return None
            
        return max(self._sector_strength.items(), key=lambda x: x[1])[0]
