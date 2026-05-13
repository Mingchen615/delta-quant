"""
技术指标计算库
使用pandas和numpy计算各种技术指标
"""

import numpy as np
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass


@dataclass
class EMAResult:
    """EMA结果"""
    ema_short: float
    ema_mid: float
    ema_long: float


@dataclass
class MACDResult:
    """MACD结果"""
    macd: float
    signal: float
    histogram: float


@dataclass
class BollingerResult:
    """布林带结果"""
    upper: float
    middle: float
    lower: float
    bandwidth: float


@dataclass
class ATRResult:
    """ATR结果"""
    atr: float
    tr: float
    atr_percentile: float


class IndicatorCalculator:
    """
    技术指标计算器
    提供完整的技术分析指标
    """
    
    @staticmethod
    def sma(values: List[float], period: int) -> Optional[float]:
        """简单移动平均"""
        if len(values) < period:
            return None
        return sum(values[-period:]) / period
        
    @staticmethod
    def ema(values: List[float], period: int) -> Optional[float]:
        """
        指数移动平均
        EMA = (Close - EMA_prev) * k + EMA_prev
        k = 2 / (period + 1)
        """
        if len(values) < period:
            return None
            
        k = 2 / (period + 1)
        # 初始化为SMA
        ema = sum(values[:period]) / period
        
        for value in values[period:]:
            ema = (value - ema) * k + ema
            
        return ema
        
    @staticmethod
    def ema_cross(closes: List[float], short: int, long: int) -> str:
        """
        EMA交叉判断
        返回: "golden_cross", "death_cross", "neutral"
        """
        ema_short = IndicatorCalculator.ema(closes, short)
        ema_long = IndicatorCalculator.ema(closes, long)
        
        if ema_short is None or ema_long is None:
            return "neutral"
            
        # 前一根K线
        if len(closes) > short:
            prev_short = IndicatorCalculator.ema(closes[:-1], short)
            prev_long = IndicatorCalculator.ema(closes[:-1], long)
            
            if prev_short and prev_long:
                # 金叉
                if prev_short <= prev_long and ema_short > ema_long:
                    return "golden_cross"
                # 死叉
                if prev_short >= prev_long and ema_short < ema_long:
                    return "death_cross"
                    
        return "neutral"
        
    @staticmethod
    def rsi(closes: List[float], period: int = 14) -> Optional[float]:
        """
        RSI相对强弱指数
        RSI = 100 - (100 / (1 + RS))
        RS = 平均涨幅 / 平均跌幅
        """
        if len(closes) < period + 1:
            return None
            
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100
            
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return float(rsi)
        
    @staticmethod
    def macd(
        closes: List[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Optional[MACDResult]:
        """
        MACD指标
        MACD = EMA(fast) - EMA(slow)
        Signal = EMA(MACD)
        Histogram = MACD - Signal
        """
        if len(closes) < slow + signal:
            return None
            
        ema_fast = IndicatorCalculator.ema(closes, fast)
        ema_slow = IndicatorCalculator.ema(closes, slow)
        
        if ema_fast is None or ema_slow is None:
            return None
            
        macd_line = ema_fast - ema_slow
        
        # 计算Signal需要历史MACD值，这里简化处理
        # 实际应该计算完整的MACD序列
        macd_values = []
        for i in range(slow, len(closes)):
            ef = IndicatorCalculator.ema(closes[:i+1], fast)
            es = IndicatorCalculator.ema(closes[:i+1], slow)
            if ef and es:
                macd_values.append(ef - es)
                
        if len(macd_values) < signal:
            return MACDResult(
                macd=macd_line,
                signal=macd_line,
                histogram=0
            )
            
        signal_line = IndicatorCalculator.ema(macd_values, signal)
        
        return MACDResult(
            macd=macd_line,
            signal=signal_line or macd_line,
            histogram=macd_line - (signal_line or macd_line)
        )
        
    @staticmethod
    def bollinger_bands(
        closes: List[float],
        period: int = 20,
        std_dev: float = 2
    ) -> Optional[BollingerResult]:
        """
        布林带
        中轨 = SMA
        上轨 = 中轨 + 2*STD
        下轨 = 中轨 - 2*STD
        """
        if len(closes) < period:
            return None
            
        recent = closes[-period:]
        middle = np.mean(recent)
        std = np.std(recent)
        
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        
        # 带宽 = (上轨 - 下轨) / 中轨
        bandwidth = (upper - lower) / middle if middle != 0 else 0
        
        return BollingerResult(
            upper=float(upper),
            middle=float(middle),
            lower=float(lower),
            bandwidth=float(bandwidth)
        )
        
    @staticmethod
    def atr(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> Optional[ATRResult]:
        """
        ATR平均真实波幅
        TR = max(H-L, |H-PC|, |L-PC|)
        ATR = SMA(TR, period)
        """
        if len(highs) < period + 1:
            return None
            
        tr_list = []
        for i in range(1, len(highs)):
            high = highs[i]
            low = lows[i]
            prev_close = closes[i-1]
            
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
            
        if len(tr_list) < period:
            return None
            
        atr = np.mean(tr_list[-period:])
        
        # 计算ATR百分位
        atr_history = np.array(tr_list[-100:]) if len(tr_list) > 100 else np.array(tr_list)
        atr_percentile = float((atr_history < atr).sum() / len(atr_history) * 100)
        
        return ATRResult(
            atr=float(atr),
            tr=float(tr_list[-1]),
            atr_percentile=atr_percentile
        )
        
    @staticmethod
    def adx(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> Optional[float]:
        """
        ADX平均趋向指数
        衡量趋势强度，不区分方向
        """
        if len(highs) < period * 2 + 1:
            return None
            
        # 计算+DM和-DM
        plus_dm = []
        minus_dm = []
        
        for i in range(1, len(highs)):
            high_diff = highs[i] - highs[i-1]
            low_diff = lows[i-1] - lows[i]
            
            if high_diff > low_diff and high_diff > 0:
                plus_dm.append(high_diff)
                minus_dm.append(0)
            elif low_diff > high_diff and low_diff > 0:
                plus_dm.append(0)
                minus_dm.append(low_diff)
            else:
                plus_dm.append(0)
                minus_dm.append(0)
                
        # 计算TR和ATR
        atr_result = IndicatorCalculator.atr(highs, lows, closes, period)
        if not atr_result:
            return None
            
        # 计算+DI和-DI
        plus_di = np.mean(plus_dm[-period:]) / atr_result.atr * 100
        minus_di = np.mean(minus_dm[-period:]) / atr_result.atr * 100
        
        # 计算DX
        di_sum = plus_di + minus_di
        if di_sum == 0:
            return 0
            
        dx = abs(plus_di - minus_di) / di_sum * 100
        
        # ADX是DX的平滑
        adx = IndicatorCalculator.ema([dx] * period, period) or dx
        
        return float(adx)
        
    @staticmethod
    def volume_profile(
        prices: List[float],
        volumes: List[float],
        bins: int = 20
    ) -> Dict[str, float]:
        """
        成交量分布
        返回价格区间的成交量
        """
        if len(prices) != len(volumes) or len(prices) == 0:
            return {}
            
        price_min = min(prices)
        price_max = max(prices)
        
        if price_max == price_min:
            return {"middle": sum(p * v for p, v in zip(prices, volumes)) / sum(volumes)}
            
        bin_size = (price_max - price_min) / bins
        profile = {}
        
        for price, volume in zip(prices, volumes):
            bin_idx = min(int((price - price_min) / bin_size), bins - 1)
            bin_price = price_min + (bin_idx + 0.5) * bin_size
            
            if bin_price not in profile:
                profile[bin_price] = 0
            profile[bin_price] += volume
            
        return profile
        
    @staticmethod
    def calculate_all(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float]
    ) -> Dict[str, any]:
        """
        计算所有常用指标
        """
        result = {}
        
        # EMA
        result["ema_20"] = IndicatorCalculator.ema(closes, 20)
        result["ema_50"] = IndicatorCalculator.ema(closes, 50)
        result["ema_200"] = IndicatorCalculator.ema(closes, 200)
        result["ema_cross"] = IndicatorCalculator.ema_cross(closes, 20, 50)
        
        # RSI
        result["rsi"] = IndicatorCalculator.rsi(closes, 14)
        
        # MACD
        result["macd"] = IndicatorCalculator.macd(closes)
        
        # 布林带
        result["bollinger"] = IndicatorCalculator.bollinger_bands(closes)
        
        # ATR
        result["atr"] = IndicatorCalculator.atr(highs, lows, closes)
        
        # ADX
        result["adx"] = IndicatorCalculator.adx(highs, lows, closes)
        
        return result
