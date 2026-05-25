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
from data.indicators import IndicatorCalculator, full_analysis
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
        self._exchange_router = None

    def set_router(self, router):
        """设置交易所路由器"""
        self._exchange_router = router

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
        
    async def execute(self):
        """判断市场状态"""
        try:
            # 主要分析BTC
            regime = await self._analyze_regime("BTC/USDT")

            if regime:
                # v3: 分析15m趋势方向
                trend_direction, trend_scores = await self._analyze_trend_direction()

                regime.trend_direction = trend_direction
                regime.trend_scores = trend_scores

                self._current_regime = regime
                await self.publish("regime", regime)

                self.logger.info(
                    f"市场状态: {regime.regime.upper()} "
                    f"(ADX: {regime.adx:.1f}, ATR: {regime.atr:.2f}, "
                    f"ATR百分位: {regime.atr_percentile:.0f}%, "
                    f"趋势方向: {trend_direction})"
                )

        except Exception as e:
            self.logger.error(f"市场状态判断出错: {e}")
            
    async def _analyze_regime(self, symbol: str) -> Optional[RegimeEvent]:
        """分析市场状态"""
        try:
            # 获取K线数据
            klines = await self._fetch_klines(symbol, "1h", 100)
            
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

    async def _analyze_trend_direction(self):
        """v3: 分析15m趋势方向"""
        import pandas as pd
        trend_scores = {}

        for symbol in self._symbols:
            try:
                klines = await self._fetch_klines(symbol, "15m", 100)
                if not klines or len(klines) < 50:
                    trend_scores[symbol] = 0
                    continue

                import pandas as pd
                df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df = full_analysis(df)
                score = self._determine_trend(df)
                trend_scores[symbol] = score
            except Exception as e:
                self.logger.warning(f"分析{symbol} 15m趋势出错: {e}")
                trend_scores[symbol] = 0

        # 用BTC的趋势分数决定全局方向
        btc_score = trend_scores.get("BTC/USDT", 0)
        if btc_score >= 3:
            direction = "UP"
        elif btc_score <= -3:
            direction = "DOWN"
        else:
            direction = "NEUTRAL"

        return direction, trend_scores

    def _determine_trend(self, df) -> int:
        """15m趋势方向判断（v3核心规则）"""
        import pandas as pd
        last = df.iloc[-1]
        score = 0

        # BOLL中轨斜率
        boll_slope = last.get('boll_mid_slope', 0)
        if pd.notna(boll_slope):
            if boll_slope > 0.001:
                score += 2
            elif boll_slope < -0.001:
                score -= 2

        # 价格 vs BOLL中轨
        boll_mid = last.get('boll_mid', 0)
        if pd.notna(boll_mid) and boll_mid > 0:
            if last['close'] > boll_mid:
                score += 1
            elif last['close'] < boll_mid:
                score -= 1

        # MACD方向
        if last.get('macd_above_zero', False):
            score += 1
        else:
            score -= 1

        # 近3根15m K线是否有金叉/死叉
        if len(df) >= 3:
            recent = df.iloc[-3:]
            if recent.get('macd_golden_cross', pd.Series([False])).any():
                score += 2
            if recent.get('macd_death_cross', pd.Series([False])).any():
                score -= 2

        # RSI
        rsi = last.get('rsi', 50)
        if pd.notna(rsi):
            if rsi > 50:
                score += 1
            elif rsi < 50:
                score -= 1

        # ADX方向
        adx = last.get('adx', 0)
        if pd.notna(adx) and adx > 20:
            adx_pos = last.get('adx_pos', 0)
            adx_neg = last.get('adx_neg', 0)
            if pd.notna(adx_pos) and pd.notna(adx_neg):
                if adx_pos > adx_neg:
                    score += 2
                else:
                    score -= 2

        return score
        
    def get_current_regime(self) -> Optional[RegimeEvent]:
        """获取当前市场状态"""
        return self._current_regime
        
    def is_trending(self) -> bool:
        """是否趋势市场"""
        return self._current_regime is not None and self._current_regime.regime == "trend"
        
    def is_high_volatility(self) -> bool:
        """是否高波动市场"""
        return self._current_regime is not None and self._current_regime.regime == "high_volatility"
