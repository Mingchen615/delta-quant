"""
6. 信号趋势 Agent (核心)
扫描Top40币种，9因子加权评分
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import SignalEvent
from exchange.binance_client import binance_client
from data.indicators import IndicatorCalculator
from data.market_data import market_data_manager
from config import (
    SCAN_TOP_N, SIGNAL_THRESHOLD_MAIN, SIGNAL_THRESHOLD_ALT,
    FACTOR_WEIGHTS, MTF_TIMEFRAMES, MTF_WEIGHTS
)


class SignalAgent(BaseAgent):
    """
    信号趋势Agent (核心)
    每5分钟扫描Top40币种，9因子加权评分:
    1. 趋势 (EMA 20/50/200交叉)
    2. 动量 (RSI 14 + MACD)
    3. 波动率 (布林带宽度 + ATR)
    4. 成交量 (CVD累积成交量差)
    5. 持仓量变化 (OI变化率)
    6. 资金费率 (Funding Rate方向)
    7. 清算信号 (大额清算方向)
    8. 多时间框架一致性 (15m/1h/4h信号同向)
    9. 新闻情绪 (从NewsAgent获取)
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="信号趋势",
            log_prefix="[信号趋势]",
            interval=300,  # 5分钟
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)
        
        self._signals: Dict[str, SignalEvent] = {}
        self._sentiment_score: float = 0
        
    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("sentiment", self._on_sentiment)
        
    async def _on_sentiment(self, event):
        """接收情绪事件"""
        self._sentiment_score = event.score
        self.logger.debug(f"接收情绪分数: {event.score:.2f}")
        
    async def execute(self):
        """执行信号扫描"""
        self.logger.info("开始信号扫描...")
        
        try:
            # 获取Top币种
            symbols = await self._get_top_symbols()
            
            self.logger.info(f"扫描 {len(symbols)} 个币种...")
            
            for symbol in symbols:
                try:
                    signal = await self._analyze_symbol(symbol)
                    
                    if signal and signal.score > 0:
                        self._signals[symbol] = signal
                        
                        # 发布信号
                        await self.publish("signal", signal)
                        
                        # 打印高分信号
                        threshold = (
                            SIGNAL_THRESHOLD_MAIN if signal.is_mainstream 
                            else SIGNAL_THRESHOLD_ALT
                        )
                        if signal.score >= threshold:
                            self.logger.info(
                                f"📊 {symbol} {signal.direction.upper()} "
                                f"信号分数: {signal.score:.1f} "
                                f"(阈值: {threshold})"
                            )
                            
                except Exception as e:
                    self.logger.error(f"分析{symbol}出错: {e}")
                    continue
                    
            self.logger.info(f"信号扫描完成，有效信号: {len(self._signals)}")
            
        except Exception as e:
            self.logger.error(f"信号扫描出错: {e}")
            
    async def _get_top_symbols(self) -> List[str]:
        """获取Top币种"""
        try:
            markets = await binance_client.fetch_markets()
            symbols = [
                m["symbol"] for m in markets
                if m["quote"] == "USDT" and m["type"] == "future"
            ]
            
            # 按成交量排序，取Top N
            tickers = await binance_client.fetch_tickers(symbols[:100])
            
            sorted_symbols = sorted(
                symbols,
                key=lambda s: tickers.get(s, {}).get("quoteVolume", 0),
                reverse=True
            )
            
            return sorted_symbols[:SCAN_TOP_N]
            
        except Exception as e:
            self.logger.error(f"获取Top币种失败: {e}")
            return ["BTC/USDT", "ETH/USDT"]
            
    async def _analyze_symbol(self, symbol: str) -> Optional[SignalEvent]:
        """分析单个币种"""
        # 获取多时间框架K线
        mtf_klines = {}
        for tf in MTF_TIMEFRAMES:
            klines = await binance_client.fetch_klines(symbol, tf, 100)
            mtf_klines[tf] = klines
            
        if not mtf_klines.get("1h"):
            return None
            
        # 计算各因子
        factor_scores = await self._calculate_factors(symbol, mtf_klines)
        
        # 加权总分
        total_score = sum(
            factor_scores.get(f, 0) * FACTOR_WEIGHTS.get(f, 0)
            for f in FACTOR_WEIGHTS.keys()
        ) / sum(FACTOR_WEIGHTS.values())
        
        # 多时间框架确认
        mtf_signals = await self._get_mtf_signals(mtf_klines)
        mtf_score = self._calculate_mtf_score(mtf_signals)
        
        total_score = total_score * 0.9 + mtf_score * 0.1
        
        # 判断方向
        direction = self._determine_direction(factor_scores)
        
        # 判断是否主流币
        is_mainstream = symbol in ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
        
        return SignalEvent(
            symbol=symbol,
            direction=direction,
            score=min(total_score * 100, 100),  # 归一化到0-100
            confidence=mtf_score * 100,
            factor_scores=factor_scores,
            factor_weights=FACTOR_WEIGHTS.copy(),
            trend_score=factor_scores.get("trend", 0) * 100,
            momentum_score=factor_scores.get("momentum", 0) * 100,
            volatility_score=factor_scores.get("volatility", 0) * 100,
            volume_score=factor_scores.get("volume", 0) * 100,
            oi_score=factor_scores.get("open_interest", 0) * 100,
            funding_rate_score=factor_scores.get("funding_rate", 0) * 100,
            liquidation_score=factor_scores.get("liquidation", 0) * 100,
            mtf_score=mtf_score * 100,
            sentiment_score=(self._sentiment_score + 1) * 50,  # 归一化
            mtf_signals=mtf_signals,
            is_mainstream=is_mainstream,
            timestamp=datetime.now(),
        )
        
    async def _calculate_factors(
        self,
        symbol: str,
        mtf_klines: Dict[str, List]
    ) -> Dict[str, float]:
        """计算9个因子"""
        klines = mtf_klines.get("1h", [])
        
        if len(klines) < 50:
            return {}
            
        highs = [k[2] for k in klines]
        lows = [k[3] for k in klines]
        closes = [k[4] for k in klines]
        volumes = [k[5] for k in klines]
        
        scores = {}
        
        # 1. 趋势因子 (EMA交叉)
        ema_cross = IndicatorCalculator.ema_cross(closes, 20, 50)
        if ema_cross == "golden_cross":
            scores["trend"] = 0.8
        elif ema_cross == "death_cross":
            scores["trend"] = 0.2
        else:
            ema20 = IndicatorCalculator.ema(closes, 20) or 0
            ema50 = IndicatorCalculator.ema(closes, 50) or 0
            scores["trend"] = 0.5 + (ema20 - ema50) / ema50 * 5  # 相对位置
            
        # 2. 动量因子 (RSI + MACD)
        rsi = IndicatorCalculator.rsi(closes, 14) or 50
        macd = IndicatorCalculator.macd(closes)
        macd_signal = 0.5
        if macd:
            macd_signal = 0.5 + (macd.macd - macd.signal) / abs(macd.signal) * 0.5 if macd.signal else 0.5
            
        scores["momentum"] = (rsi / 100 + macd_signal) / 2
        
        # 3. 波动率因子
        boll = IndicatorCalculator.bollinger_bands(closes)
        atr = IndicatorCalculator.atr(highs, lows, closes)
        
        if boll and atr:
            # 布林带宽度适中最好
            bandwidth = boll.bandwidth
            vol_score = 0.5
            if 0.03 < bandwidth < 0.08:  # 适中波动
                vol_score = 0.7
            elif bandwidth <= 0.03:  # 低波动
                vol_score = 0.4
            else:  # 高波动
                vol_score = 0.5
                
            scores["volatility"] = vol_score
        else:
            scores["volatility"] = 0.5
            
        # 4. 成交量因子
        recent_vol = sum(volumes[-10:]) / 10
        avg_vol = sum(volumes[-50:]) / 50
        vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1
        scores["volume"] = min(vol_ratio / 2, 1)  # 放量是好信号
        
        # 5. 持仓量因子 (简化，合约才有)
        scores["open_interest"] = 0.5  # 默认中性
        
        # 6. 资金费率因子
        try:
            fr = await binance_client.fetch_funding_rate(symbol)
            funding_rate = fr.get("fundingRate", 0)
            # 正费率->空头主导->做空有利
            scores["funding_rate"] = 0.5 - funding_rate * 100
        except:
            scores["funding_rate"] = 0.5
            
        # 7. 清算因子 (简化)
        scores["liquidation"] = 0.5  # 默认中性
        
        # 8. 多时间框架因子 (后面单独计算)
        scores["mtf"] = 0.5
        
        # 9. 情绪因子
        scores["sentiment"] = (self._sentiment_score + 1) / 2
        
        return scores
        
    async def _get_mtf_signals(self, mtf_klines: Dict[str, List]) -> Dict[str, str]:
        """获取多时间框架信号"""
        signals = {}
        
        for tf in MTF_TIMEFRAMES:
            klines = mtf_klines.get(tf, [])
            
            if len(klines) < 50:
                signals[tf] = "neutral"
                continue
                
            closes = [k[4] for k in klines]
            
            # EMA交叉
            ema_cross = IndicatorCalculator.ema_cross(closes, 20, 50)
            
            if ema_cross == "golden_cross":
                signals[tf] = "long"
            elif ema_cross == "death_cross":
                signals[tf] = "short"
            else:
                # RSI判断
                rsi = IndicatorCalculator.rsi(closes, 14)
                if rsi and rsi > 60:
                    signals[tf] = "long"
                elif rsi and rsi < 40:
                    signals[tf] = "short"
                else:
                    signals[tf] = "neutral"
                    
        return signals
        
    def _calculate_mtf_score(self, mtf_signals: Dict[str, str]) -> float:
        """计算多时间框架得分"""
        if not mtf_signals:
            return 0.5
            
        score = 0
        for tf, signal in mtf_signals.items():
            weight = MTF_WEIGHTS.get(tf, 0.33)
            
            if signal == "long":
                score += weight
            elif signal == "short":
                score -= weight
                
        return (score + 1) / 2  # 归一化到0-1
        
    def _determine_direction(self, factor_scores: Dict[str, float]) -> str:
        """判断交易方向"""
        # 综合各因子
        trend = factor_scores.get("trend", 0.5)
        momentum = factor_scores.get("momentum", 0.5)
        volume = factor_scores.get("volume", 0.5)
        
        avg = (trend + momentum + volume) / 3
        
        if avg > 0.55:
            return "long"
        elif avg < 0.45:
            return "short"
        else:
            return "neutral"
            
    def get_top_signals(self, direction: str = "long", n: int = 5) -> List[SignalEvent]:
        """获取高分信号"""
        filtered = [
            s for s in self._signals.values()
            if s.direction == direction and s.score > 0
        ]
        return sorted(filtered, key=lambda x: x.score, reverse=True)[:n]
