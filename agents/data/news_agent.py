"""
1. 新闻数据 Agent
监控加密货币新闻，分析市场情绪
"""

import asyncio
import httpx
from datetime import datetime
from typing import Dict, Optional, List

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import SentimentEvent, EventType
from config import CRYPTOPANIC_API_KEY, CRYPTOPANIC_API_URL


class NewsAgent(BaseAgent):
    """
    新闻情绪分析Agent
    - 抓取CryptoPanic新闻
    - 分析情绪（正面/负面/中性）
    - 输出情绪分数到消息总线
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="新闻数据",
            log_prefix="[新闻数据]",
            interval=60,  # 60秒检查一次
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)
        
        self._sentiment_cache: Dict[str, SentimentEvent] = {}
        self._last_fetch: Optional[datetime] = None
        
    async def execute(self):
        """执行新闻抓取和情绪分析"""
        self.logger.debug("开始抓取新闻...")
        
        try:
            # 获取新闻
            news = await self._fetch_news()
            
            if news:
                # 分析情绪
                sentiment = self._analyze_sentiment(news)
                
                # 发布情绪事件
                await self.publish("sentiment", sentiment)
                
                self.logger.info(
                    f"情绪分析完成: {sentiment.sentiment} "
                    f"(score: {sentiment.score:.2f}, 来源: {len(sentiment.sources)})"
                )
            else:
                self.logger.debug("暂无新新闻")
                
        except Exception as e:
            self.logger.error(f"新闻抓取出错: {e}")
            
    async def _fetch_news(self) -> List[Dict]:
        """抓取新闻"""
        if not CRYPTOPANIC_API_KEY:
            self.logger.warning("未设置CryptoPanic API Key，生成模拟数据")
            return self._generate_mock_news()
            
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    CRYPTOPANIC_API_URL,
                    params={
                        "auth_token": CRYPTOPANIC_API_KEY,
                        "kind": "news",
                        "currencies": "BTC,ETH",
                        "public": "true",
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("results", [])
                    
        except Exception as e:
            self.logger.error(f"API请求失败: {e}")
            
        return []
        
    def _generate_mock_news(self) -> List[Dict]:
        """生成模拟新闻数据"""
        return [
            {"title": "BTC突破新高", "source": {"name": "Mock"}, "votes": {"positive": 100}},
            {"title": "ETH升级进展顺利", "source": {"name": "Mock"}, "votes": {"positive": 80}},
        ]
        
    def _analyze_sentiment(self, news: List[Dict]) -> SentimentEvent:
        """
        分析新闻情绪
        
        基于投票计算情绪分数
        - positive: 正面
        - negative: 负面
        - neutral: 中性
        """
        total_score = 0
        sources = []
        
        for item in news:
            votes = item.get("votes", {})
            positive = votes.get("positive", 0)
            negative = votes.get("negative", 0)
            
            if positive + negative > 0:
                score = (positive - negative) / (positive + negative)
                total_score += score
                
            if "source" in item:
                sources.append(item["source"].get("name", ""))
                
        # 计算平均分数
        if news:
            avg_score = total_score / len(news)
        else:
            avg_score = 0
            
        # 判断情绪
        if avg_score > 0.1:
            sentiment = "bullish"
        elif avg_score < -0.1:
            sentiment = "bearish"
        else:
            sentiment = "neutral"
            
        return SentimentEvent(
            sentiment=sentiment,
            score=avg_score,
            sources=list(set(sources)),
            timestamp=datetime.now(),
        )
        
    def get_cached_sentiment(self) -> Optional[SentimentEvent]:
        """获取缓存的情绪数据"""
        cached = list(self._sentiment_cache.values())
        if cached:
            return cached[-1]
        return None
