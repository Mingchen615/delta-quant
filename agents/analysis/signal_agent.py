"""
6. 信号趋势 Agent (核心) - v3重写
15m定方向 → 5m找入场 → 1m确认
"""

import asyncio
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import SignalEvent
from exchange.binance_client import binance_client
from data.indicators import full_analysis
from data.market_data import market_data_manager
from config import (
    SCAN_TOP_N, SIGNAL_THRESHOLD_MAIN, SIGNAL_THRESHOLD_ALT,
    MAX_POSITIONS, TRADING_V3,
)


class SignalAgent(BaseAgent):
    """
    信号趋势Agent (v3核心重写)
    分层评分+方向锁定:
    1. 15m趋势方向（从RegimeEvent获取）
    2. 5m信号评分（只在趋势方向上计分）
    3. 1m确认（近3根K线需2根同方向）
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
        self._exchange_router = None
        self._position_count: int = 0
        self._paused: bool = False
        self._current_trend: str = "NEUTRAL"  # 从RegimeAgent获取
        self._current_regime = None

    def set_router(self, router):
        """设置交易所路由器"""
        self._exchange_router = router

    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("sentiment", self._on_sentiment)
        await self.subscribe("position.opened", self._on_position_opened)
        await self.subscribe("position.closed", self._on_position_closed)
        await self.subscribe("regime", self._on_regime)

    async def _on_sentiment(self, event):
        """接收情绪事件"""
        self._sentiment_score = event.score
        self.logger.debug(f"接收情绪分数: {event.score:.2f}")

    async def _on_position_opened(self, event):
        """持仓开仓 - 更新计数"""
        self._position_count += 1
        self._check_position_slots()

    async def _on_position_closed(self, event):
        """持仓平仓 - 更新计数并恢复扫描"""
        self._position_count = max(0, self._position_count - 1)
        if self._paused and self._position_count < MAX_POSITIONS:
            self._paused = False
            self.logger.info(f"仓位空出({self._position_count}/{MAX_POSITIONS})，恢复信号扫描")

    async def _on_regime(self, event):
        """接收市场状态事件，获取15m趋势方向"""
        self._current_trend = event.trend_direction
        self._current_regime = event
        self.logger.debug(f"接收趋势方向: {self._current_trend}")

    def _check_position_slots(self):
        """检查仓位是否已满"""
        if self._position_count >= MAX_POSITIONS:
            if not self._paused:
                self._paused = True
                self.logger.info(f"仓位已满({self._position_count}/{MAX_POSITIONS})，暂停信号扫描")

    async def execute(self):
        """执行信号扫描"""
        if self._paused:
            self.logger.debug(f"仓位已满({self._position_count}/{MAX_POSITIONS})，跳过扫描")
            return

        # v3: 第1关 - 15m趋势方向
        if self._current_trend == "NEUTRAL":
            self.logger.info("15m趋势不明(NEUTRAL)，跳过本轮扫描")
            return

        self.logger.info(f"开始信号扫描 (趋势方向: {self._current_trend})...")

        try:
            symbols = await self._get_top_symbols()
            self.logger.info(f"扫描 {len(symbols)} 个币种...")

            for symbol in symbols:
                try:
                    signal = await self._analyze_symbol(symbol)

                    if signal and signal.score > 0:
                        self._signals[symbol] = signal
                        await self.publish("signal", signal)

                        threshold = (
                            SIGNAL_THRESHOLD_MAIN if signal.is_mainstream
                            else SIGNAL_THRESHOLD_ALT
                        )
                        if signal.score >= threshold:
                            self.logger.info(
                                f"📊 {symbol} {signal.direction.upper()} "
                                f"信号分数: {signal.score:.1f} "
                                f"趋势: {signal.trend} "
                                f"ATR: {signal.atr:.4f} "
                                f"(阈值: {threshold})"
                            )

                except Exception as e:
                    self.logger.error(f"分析{symbol}出错: {e}")
                    continue

            self.logger.info(f"信号扫描完成，有效信号: {len(self._signals)}")

        except Exception as e:
            self.logger.error(f"信号扫描出错: {e}")

    async def _fetch_klines(self, symbol: str, timeframe: str, limit: int) -> list:
        """从路由器或binance_client获取K线数据"""
        if self._exchange_router:
            for name, ex in self._exchange_router.exchanges.items():
                if not ex.is_connected:
                    continue
                try:
                    klines = await ex.get_klines(symbol, timeframe, limit)
                    return [
                        [int(k.timestamp.timestamp() * 1000), k.open, k.high, k.low, k.close, k.volume]
                        for k in klines
                    ]
                except Exception as e:
                    self.logger.warning(f"{name} get_klines失败 {symbol}: {e}")
                    continue
            raise RuntimeError(f"所有交易所获取 {symbol} K线失败")
        return await binance_client.fetch_klines(symbol, timeframe, limit)

    async def _get_top_symbols(self) -> List[str]:
        """获取Top币种"""
        if self._exchange_router:
            for name, ex in self._exchange_router.exchanges.items():
                if ex.is_connected:
                    try:
                        symbols = [s for s in ex.supported_symbols if ":USDT" in s]
                        return symbols[:SCAN_TOP_N]
                    except Exception:
                        continue
            return ["BTC/USDT:USDT", "ETH/USDT:USDT"]

        try:
            markets = await binance_client.fetch_markets()
            symbols = [
                m["symbol"] for m in markets
                if m["quote"] == "USDT" and m["type"] == "future"
            ]
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
        """v3: 分层分析单个币种"""
        # 获取3个时间框架K线
        klines_15m = await self._fetch_klines(symbol, "15m", 100)
        klines_5m = await self._fetch_klines(symbol, "5m", 100)
        klines_1m = await self._fetch_klines(symbol, "1m", 30)

        if not klines_5m or len(klines_5m) < 50:
            return None

        # 构建DataFrame并计算指标
        df_5m = pd.DataFrame(klines_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_5m = full_analysis(df_5m)

        df_1m = pd.DataFrame(klines_1m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_1m = full_analysis(df_1m)

        df_15m = None
        if klines_15m and len(klines_15m) >= 50:
            df_15m = pd.DataFrame(klines_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_15m = full_analysis(df_15m)

        # === 第1关：15m趋势方向（从RegimeAgent获取）===
        trend = self._current_trend
        if trend == "NEUTRAL":
            return None  # 不开仓

        # === 第2关：5m ADX过滤 ===
        last_5m = df_5m.iloc[-1]
        adx = last_5m.get('adx', 0)
        if pd.isna(adx):
            adx = 0
        min_adx = TRADING_V3.get('min_adx', 20)
        if adx < min_adx:
            self.logger.debug(f"{symbol} ADX={adx:.1f} < {min_adx}，趋势太弱")
            return None

        # ATR值
        atr = last_5m.get('atr', 0)
        if pd.isna(atr) or atr <= 0:
            atr = (last_5m['high'] - last_5m['low']) * 0.5

        # 成交量比率
        vol_ratio = last_5m.get('vol_ratio', 0)
        if pd.isna(vol_ratio):
            vol_ratio = 0

        # === 第3关：5m信号评分（只在趋势方向上计分）===
        prev_5m = df_5m.iloc[-2]
        last_1m = df_1m.iloc[-1]

        if trend == "UP":
            score, reasons = self._score_long(
                last_5m, prev_5m, last_1m, df_1m, vol_ratio, df_15m, adx
            )
        else:  # DOWN
            score, reasons = self._score_short(
                last_5m, prev_5m, last_1m, df_1m, vol_ratio, df_15m, adx
            )

        # 缩量扣分
        min_vol = TRADING_V3.get('min_vol_ratio', 1.0)
        if vol_ratio < min_vol and f'缩量' not in ' '.join(reasons):
            score -= 10
            reasons.append(f'5m缩量({vol_ratio:.1f}x)')

        score = max(0, min(score, 100))

        action = "HOLD"
        min_strength = TRADING_V3.get('min_signal_strength', 70)
        if score >= min_strength:
            action = "LONG" if trend == "UP" else "SHORT"

        is_mainstream = symbol in ["BTC/USDT", "ETH/USDT", "BNB/USDT", "BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"]

        adx_15m = 0
        if df_15m is not None and len(df_15m) > 0:
            adx_15m = df_15m.iloc[-1].get('adx', 0)
            if pd.isna(adx_15m):
                adx_15m = 0

        return SignalEvent(
            symbol=symbol,
            direction="long" if action == "LONG" else ("short" if action == "SHORT" else "neutral"),
            score=score,
            confidence=score,
            factor_scores={},
            factor_weights={},
            trend_score=25 if trend == "UP" else (-25 if trend == "DOWN" else 0),
            momentum_score=0,
            volatility_score=0,
            volume_score=vol_ratio * 20,
            oi_score=0,
            funding_rate_score=0,
            liquidation_score=0,
            mtf_score=0,
            sentiment_score=(self._sentiment_score + 1) * 50,
            mtf_signals={},
            is_mainstream=is_mainstream,
            timestamp=datetime.now(),
            # v3新增
            trend=trend,
            atr=float(atr),
            adx=float(adx_15m),
            vol_ratio=float(vol_ratio),
        )

    def _score_long(self, last, prev, last_1m, df_1m, vol_ratio, df_15m, adx):
        """v3: 做多评分"""
        score = 0
        reasons = []

        # 15m趋势确认 (25分)
        score += 25
        reasons.append('15m趋势向上')

        # 5m MACD
        if last.get('macd_golden_cross', False) and last.get('macd_above_zero', False):
            score += 20
            reasons.append('5m零轴上金叉')
        elif last.get('macd_golden_cross', False):
            score += 12
            reasons.append('5m金叉')
        if (last.get('macd_hist', 0) > 0 and prev.get('macd_hist', 0) > 0 and
                last.get('macd_hist', 0) < prev.get('macd_hist', 0)):
            score += 5
            reasons.append('5m MACD柱缩短')

        # 5m Swing底背驰
        if last.get('divergence_bull', False):
            score += 20
            reasons.append('5m底背驰(Swing)')

        # 5m BOLL位置
        boll_pos = last.get('boll_position', 0.5)
        if pd.notna(boll_pos):
            if boll_pos < 0.2:
                score += 15
                reasons.append('5m BOLL下轨')
            elif prev.get('close', 0) < prev.get('boll_mid', 0) and last['close'] > last.get('boll_mid', 0):
                score += 12
                reasons.append('5m回踩中轨反弹')
            elif boll_pos < 0.35:
                score += 5
                reasons.append('5m BOLL偏低')

        # 5m KDJ
        if last.get('kdj_golden_cross', False) and last.get('kdj_k', 50) < 30:
            score += 15
            reasons.append('5m KDJ低位金叉')
        elif last.get('kdj_golden_cross', False):
            score += 8
            reasons.append('5m KDJ金叉')
        if last.get('kdj_j', 50) > 20 and prev.get('kdj_j', 50) < 20:
            score += 10
            reasons.append('5m KDJ低位拐头')

        # 5m RSI
        if last.get('rsi_oversold', False):
            score += 10
            reasons.append('5m RSI超卖')
        if last.get('rsi_bullish_divergence', False):
            score += 15
            reasons.append('5m RSI底背离')

        # 成交量
        if last.get('vol_surge', False):
            score += 10
            reasons.append(f'5m放量({vol_ratio:.1f}x)')
        elif vol_ratio >= 1.0:
            score += 3
            reasons.append('5m量能正常')

        # 1m确认（3根K线中2根收阳）
        recent = df_1m.tail(3)
        bullish = sum(1 for _, r in recent.iterrows() if r['close'] > r['open'])
        if bullish >= 2:
            score += 8
            reasons.append('1m连续收阳确认')
        if last_1m.get('kdj_golden_cross', False) or last_1m.get('macd_golden_cross', False):
            score += 5
            reasons.append('1m指标金叉')

        # ADX趋势强度加分
        if pd.notna(adx) and adx > 25:
            score += 5
            reasons.append(f'ADX={adx:.0f}趋势强')

        return score, reasons

    def _score_short(self, last, prev, last_1m, df_1m, vol_ratio, df_15m, adx):
        """v3: 做空评分"""
        score = 0
        reasons = []

        score += 25
        reasons.append('15m趋势向下')

        if last.get('macd_death_cross', False) and not last.get('macd_above_zero', True):
            score += 20
            reasons.append('5m零轴下死叉')
        elif last.get('macd_death_cross', False):
            score += 12
            reasons.append('5m死叉')
        if (last.get('macd_hist', 0) < 0 and prev.get('macd_hist', 0) < 0 and
                last.get('macd_hist', 0) > prev.get('macd_hist', 0)):
            score += 5
            reasons.append('5m MACD柱缩短')

        if last.get('divergence_bear', False):
            score += 20
            reasons.append('5m顶背驰(Swing)')

        boll_pos = last.get('boll_position', 0.5)
        if pd.notna(boll_pos):
            if boll_pos > 0.8:
                score += 15
                reasons.append('5m BOLL上轨')
            elif boll_pos > 0.7:
                score += 5
                reasons.append('5m BOLL偏高')

        if last.get('kdj_death_cross', False) and last.get('kdj_k', 50) > 70:
            score += 15
            reasons.append('5m KDJ高位死叉')
        elif last.get('kdj_death_cross', False):
            score += 8
            reasons.append('5m KDJ死叉')
        if last.get('kdj_j', 50) < 80 and prev.get('kdj_j', 50) > 80:
            score += 10
            reasons.append('5m KDJ高位拐头')

        if last.get('rsi_overbought', False):
            score += 10
            reasons.append('5m RSI超买')
        if last.get('rsi_bearish_divergence', False):
            score += 15
            reasons.append('5m RSI顶背离')

        if last.get('vol_surge', False):
            score += 10
            reasons.append(f'5m放量({vol_ratio:.1f}x)')
        elif vol_ratio >= 1.0:
            score += 3
            reasons.append('5m量能正常')

        recent = df_1m.tail(3)
        bearish = sum(1 for _, r in recent.iterrows() if r['close'] < r['open'])
        if bearish >= 2:
            score += 8
            reasons.append('1m连续收阴确认')
        if last_1m.get('kdj_death_cross', False) or last_1m.get('macd_death_cross', False):
            score += 5
            reasons.append('1m指标死叉')

        if pd.notna(adx) and adx > 25:
            score += 5
            reasons.append(f'ADX={adx:.0f}趋势强')

        return score, reasons

    def get_top_signals(self, direction: str = "long", n: int = 5) -> List[SignalEvent]:
        """获取高分信号"""
        filtered = [
            s for s in self._signals.values()
            if s.direction == direction and s.score > 0
        ]
        return sorted(filtered, key=lambda x: x.score, reverse=True)[:n]
