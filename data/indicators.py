"""
技术指标计算库
使用pandas和numpy计算各种技术指标
"""

import numpy as np
import pandas as pd
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


# =============================================================================
# DataFrame-based indicator functions (v3.0)
# =============================================================================

def calc_macd(df, fast=12, slow=26, signal=9):
    """计算MACD指标（DataFrame版本）"""
    import pandas as pd
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    df['macd'] = ema_fast - ema_slow
    df['macd_signal'] = df['macd'].ewm(span=signal, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    df['macd_above_zero'] = df['macd'] > 0
    df['macd_golden_cross'] = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
    df['macd_death_cross'] = (df['macd'] < df['macd_signal']) & (df['macd'].shift(1) >= df['macd_signal'].shift(1))
    # MACD面积（用于背驰检测）
    df['macd_area'] = df['macd_hist'].abs().rolling(window=5).sum()
    return df


def calc_boll(df, period=20, std_dev=2):
    """计算布林带（DataFrame版本）"""
    df['boll_mid'] = df['close'].rolling(window=period).mean()
    boll_std = df['close'].rolling(window=period).std()
    df['boll_upper'] = df['boll_mid'] + std_dev * boll_std
    df['boll_lower'] = df['boll_mid'] - std_dev * boll_std
    # 布林带位置 0=下轨 1=上轨
    boll_range = df['boll_upper'] - df['boll_lower']
    df['boll_position'] = (df['close'] - df['boll_lower']) / boll_range.replace(0, 1)
    df['boll_position'] = df['boll_position'].clip(0, 1)
    # 布林中轨斜率
    df['boll_mid_slope'] = df['boll_mid'].pct_change(3)
    return df


def calc_kdj(df, n=9, m1=3, m2=3):
    """计算KDJ指标（DataFrame版本）"""
    low_n = df['low'].rolling(window=n).min()
    high_n = df['high'].rolling(window=n).max()
    rsv = (df['close'] - low_n) / (high_n - low_n).replace(0, 1) * 100

    df['kdj_k'] = rsv.ewm(com=m1 - 1, adjust=False).mean()
    df['kdj_d'] = df['kdj_k'].ewm(com=m2 - 1, adjust=False).mean()
    df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']
    df['kdj_golden_cross'] = (df['kdj_k'] > df['kdj_d']) & (df['kdj_k'].shift(1) <= df['kdj_d'].shift(1))
    df['kdj_death_cross'] = (df['kdj_k'] < df['kdj_d']) & (df['kdj_k'].shift(1) >= df['kdj_d'].shift(1))
    return df


def calc_volume(df, period=20):
    """计算成交量指标（DataFrame版本）"""
    df['vol_ma'] = df['volume'].rolling(window=period).mean()
    df['vol_ratio'] = df['volume'] / df['vol_ma'].replace(0, 1)
    df['vol_surge'] = df['vol_ratio'] > 1.5
    return df


def calc_atr(df, period=14):
    """计算ATR（DataFrame版本，v3新增）"""
    high = df['high']
    low = df['low']
    prev_close = df['close'].shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['tr'] = tr
    df['atr'] = tr.rolling(window=period).mean()
    return df


def calc_adx(df, period=14):
    """计算ADX（DataFrame版本，v3新增）"""
    high = df['high']
    low = df['low']
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    plus_dm = high - prev_high
    minus_dm = prev_low - low
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    atr = df.get('atr')
    if atr is None:
        df = calc_atr(df, period)
        atr = df['atr']

    atr_safe = atr.replace(0, 1)
    plus_di = 100 * plus_dm.rolling(window=period).mean() / atr_safe
    minus_di = 100 * minus_dm.rolling(window=period).mean() / atr_safe

    di_sum = plus_di + minus_di
    di_sum = di_sum.replace(0, 1)
    dx = 100 * (plus_di - minus_di).abs() / di_sum

    df['adx'] = dx.rolling(window=period).mean()
    df['adx_pos'] = plus_di
    df['adx_neg'] = minus_di
    return df


def calc_rsi_v3(df, window=14):
    """RSI + 20根K线背离检测（v3新增，替换旧calc_rsi）"""
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss.replace(0, 1)
    df['rsi'] = 100 - (100 / (1 + rs))
    df['rsi_overbought'] = df['rsi'] > 70
    df['rsi_oversold'] = df['rsi'] < 30
    # 20根K线背离检测
    df['rsi_bullish_divergence'] = (
        (df['low'] < df['low'].shift(20)) &
        (df['rsi'] > df['rsi'].shift(20)) &
        (df['rsi'] < 40)
    )
    df['rsi_bearish_divergence'] = (
        (df['high'] > df['high'].shift(20)) &
        (df['rsi'] < df['rsi'].shift(20)) &
        (df['rsi'] > 60)
    )
    return df


def find_swing_points(df, lookback=3):
    """找Swing High/Low用于背驰检测（v3新增）"""
    import numpy as np
    df = df.copy()
    df['swing_high'] = np.nan
    df['swing_low'] = np.nan
    highs = df['high'].values
    lows = df['low'].values
    for i in range(lookback, len(df) - lookback):
        is_high = all(
            highs[i] >= highs[i - j] and highs[i] >= highs[i + j]
            for j in range(1, lookback + 1)
        )
        is_low = all(
            lows[i] <= lows[i - j] and lows[i] <= lows[i + j]
            for j in range(1, lookback + 1)
        )
        if is_high:
            df.iat[i, df.columns.get_loc('swing_high')] = highs[i]
        if is_low:
            df.iat[i, df.columns.get_loc('swing_low')] = lows[i]
    return df


def calc_divergence_v3(df):
    """v3: 基于Swing点的背驰检测"""
    import numpy as np
    df = find_swing_points(df, lookback=3)

    df['divergence_bull'] = False
    df['divergence_bear'] = False

    swing_lows = df[df['swing_low'].notna()].index.tolist()
    if len(swing_lows) >= 2:
        last_sl = swing_lows[-1]
        prev_sl = swing_lows[-2]
        if (df.loc[last_sl, 'low'] < df.loc[prev_sl, 'low'] and
                df.loc[last_sl, 'macd_area'] < df.loc[prev_sl, 'macd_area'] and
                df.loc[last_sl, 'macd_hist'] < 0):
            df.at[df.index[-1], 'divergence_bull'] = True

    swing_highs = df[df['swing_high'].notna()].index.tolist()
    if len(swing_highs) >= 2:
        last_sh = swing_highs[-1]
        prev_sh = swing_highs[-2]
        if (df.loc[last_sh, 'high'] > df.loc[prev_sh, 'high'] and
                df.loc[last_sh, 'macd_area'] < df.loc[prev_sh, 'macd_area'] and
                df.loc[last_sh, 'macd_hist'] > 0):
            df.at[df.index[-1], 'divergence_bear'] = True

    return df


def full_analysis(df):
    """完整技术分析（v3更新版）"""
    df = calc_macd(df)
    df = calc_boll(df)
    df = calc_kdj(df)
    df = calc_rsi_v3(df)
    df = calc_volume(df)
    df = calc_atr(df)
    df = calc_adx(df)
    df = calc_divergence_v3(df)
    return df
