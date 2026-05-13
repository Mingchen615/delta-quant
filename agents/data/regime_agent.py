"""
5. 市场状态 Agent
判断市场状态：趋势/震荡/高波动
"""

import asyncio
from datetime import datetime
from typing import Optional, List

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import RegimeEvent
from exchange.binance_client import binance_client
from data.indicators import IndicatorCalculator
from config import ADX_TREND_THRESHOLD, ADX_RANGING_THRESHOLD, ATR_MULTIPLIER_HIGH


class RegimeAgent(BaseAgent):
    """
    市场状态判断Agent
    - 基于ATR+ADX判断市场状态
    - 趋势市(ADX>25, ATR扩大)
    - 震荡市(ADX<20, ATR收缩)
    - 高波动(ATR>2倍均值)
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="市场状态",
            log_prefix="[市场状态]",
            interval=60,  # 1分钟
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)
        
        self._current_regime: Optional[RegimeEvent] = None
        self._symbols = ["BTC/USDT", "ETH/USDT"]
        
    async def execute(self):
        """判断市场状态"""
        try:
            # 主要分析BTC
            regime = await self._analyze_regime("BTC/USDT")
            
            if regime:
                self._current_regime = regime
                await self.publish("regime", regime)
                
                self.logger.info(
                    f"市场状态: {regime.regime.upper()} "
                    f"(ADX: {regime.adx:.1f}, ATR: {regime.atr:.2f}, "
                    f"ATR百分位: {regime.atr_percentile:.0f}%)"
                )
                
        except Exception as e:
            self.logger.error(f"市场状态判断出错: {e}")
            
    async def _analyze_regime(self, symbol: str) -> Optional[RegimeEvent]:
        """分析市场状态"""
        try:
            # 获取K线数据
            klines = await binance_client.fetch_klines(symbol, "1h", 100)
            
            if not klines or len(klines) < 50:
                return None
                
            highs = [k[2] for k in klines]
            lows = [k[3] for k in klines]
            closes = [k[4] for k in klines]
            volumes = [k[5] for k in klines]
            
            # 计算ATR
            atr_result = IndicatorCalculator.atr(highs, lows, closes)
            
            if not atr_result:
                return None
                
            # 计算ADX
            adx = IndicatorCalculator.adx(highs, lows, closes)
            
            if adx is None:
                adx = 0
                
            # 判断状态
            regime_type = self._determine_regime(
                adx, atr_result.atr, atr_result.atr_percentile
            )
            
            return RegimeEvent(
                regime=regime_type,
                adx=float(adx),
                atr=float(atr_result.atr),
                atr_percentile=float(atr_result.atr_percentile),
                timestamp=datetime.now(),
            )
            
        except Exception as e:
            self.logger.error(f"分析{symbol}市场状态出错: {e}")
            return None
            
    def _determine_regime(
        self,
        adx: float,
        atr: float,
        atr_percentile: float
    ) -> str:
        """
        判断市场状态
        """
        # 高波动优先判断
        if atr_percentile > 80:
            return "high_volatility"
            
        # 趋势判断
        if adx > ADX_TREND_THRESHOLD:
            return "trend"
            
        # 震荡判断
        if adx < ADX_RANGING_THRESHOLD:
            return "ranging"
            
        # 中间区域
        return "mixed"
        
    def get_current_regime(self) -> Optional[RegimeEvent]:
        """获取当前市场状态"""
        return self._current_regime
        
    def is_trending(self) -> bool:
        """是否趋势市场"""
        return self._current_regime is not None and self._current_regime.regime == "trend"
        
    def is_high_volatility(self) -> bool:
        """是否高波动市场"""
        return self._current_regime is not None and self._current_regime.regime == "high_volatility"
