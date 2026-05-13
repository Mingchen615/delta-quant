"""
7. 多空辩论 Agent
使用DeepSeek进行多空辩论
"""

import asyncio
import httpx
from datetime import datetime
from typing import Dict, Optional, List

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import SignalEvent, DebateEvent
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL, DEBATE_CONFIDENCE_THRESHOLD


class DebateAgent(BaseAgent):
    """
    多空辩论Agent
    收到SignalEvent后触发:
    - 构造Bull论证prompt
    - 构造Bear论证prompt
    - 两次调用DeepSeek API
    - 综合判断confidence > 60才放行
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="多空辩论",
            log_prefix="[多空辩论]",
            interval=0,  # 事件触发，不定期执行
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)
        
        self._pending_debates: List[SignalEvent] = []
        self._debate_cache: Dict[str, DebateEvent] = {}
        
    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("signal", self._on_signal)
        
    async def _on_signal(self, signal: SignalEvent):
        """接收信号事件"""
        if signal.direction == "neutral":
            return
            
        # 添加到辩论队列
        self._pending_debates.append(signal)
        self.logger.debug(f"收到信号加入辩论队列: {signal.symbol}")
        
        # 立即执行辩论
        await self._execute_debate(signal)
        
    async def execute(self):
        """执行待处理辩论"""
        # 检查待处理辩论
        if self._pending_debates:
            signal = self._pending_debates.pop(0)
            await self._execute_debate(signal)
            
    async def _execute_debate(self, signal: SignalEvent):
        """执行辩论"""
        self.logger.info(f"开始辩论: {signal.symbol} {signal.direction}")
        
        try:
            # 构建prompt
            bull_prompt = self._build_bull_prompt(signal)
            bear_prompt = self._build_bear_prompt(signal)
            
            # 并行执行辩论
            bull_result, bear_result = await asyncio.gather(
                self._call_deepseek(bull_prompt),
                self._call_deepseek(bear_prompt),
            )
            
            # 解析结果
            bull_conf = self._parse_confidence(bull_result, "bull")
            bear_conf = self._parse_confidence(bear_result, "bear")
            
            # 综合判断
            if signal.direction == "long":
                final_confidence = bull_conf * 0.6 + (1 - bear_conf) * 0.4
            else:
                final_confidence = bear_conf * 0.6 + (1 - bull_conf) * 0.4
                
            approved = final_confidence >= DEBATE_CONFIDENCE_THRESHOLD / 100
            
            # 创建辩论事件
            debate = DebateEvent(
                symbol=signal.symbol,
                direction=signal.direction,
                signal_score=signal.score,
                approved=approved,
                confidence=final_confidence * 100,
                bull_arguments=self._extract_arguments(bull_result),
                bull_confidence=bull_conf * 100,
                bear_arguments=self._extract_arguments(bear_result),
                bear_confidence=bear_conf * 100,
                summary=self._generate_summary(bull_result, bear_result, signal.direction),
                timestamp=datetime.now(),
            )
            
            # 缓存
            self._debate_cache[signal.symbol] = debate
            
            # 发布辩论结果
            await self.publish("debate", debate)
            
            # 日志
            status = "通过" if approved else "拒绝"
            self.logger.info(
                f"辩论完成: {signal.symbol} {signal.direction} "
                f"[{status}] 置信度: {debate.confidence:.1f}%"
            )
            
        except Exception as e:
            self.logger.error(f"辩论执行出错: {e}")
            
    def _build_bull_prompt(self, signal: SignalEvent) -> str:
        """构建做多论证prompt"""
        return f"""你是专业的加密货币分析师。请分析{signal.symbol}做多({signal.direction})的理由。

信号评分详情:
- 趋势分数: {signal.trend_score:.1f}/100
- 动量分数: {signal.momentum_score:.1f}/100  
- 波动率分数: {signal.volatility_score:.1f}/100
- 成交量分数: {signal.volume_score:.1f}/100
- 多时间框架分数: {signal.mtf_score:.1f}/100
- 信号总分: {signal.score:.1f}/100

请从以下角度给出3-5个做多的具体理由:
1. 技术面支持
2. 市场结构
3. 可能的催化剂

最后用JSON格式给出置信度评估:
{{"confidence": 0-100的数值, "key_reasons": ["理由1", "理由2", ...], "risk_factors": ["风险1", "风险2", ...]}}
"""

    def _build_bear_prompt(self, signal: SignalEvent) -> str:
        """构建做空论证prompt"""
        return f"""你是专业的加密货币分析师。请分析{signal.symbol}做空({signal.direction})的理由。

信号评分详情:
- 趋势分数: {signal.trend_score:.1f}/100
- 动量分数: {signal.momentum_score:.1f}/100  
- 波动率分数: {signal.volatility_score:.1f}/100
- 成交量分数: {signal.volume_score:.1f}/100
- 多时间框架分数: {signal.mtf_score:.1f}/100
- 信号总分: {signal.score:.1f}/100

请从以下角度给出3-5个做空的具体理由:
1. 技术面阻力
2. 市场风险
3. 可能的不利因素

最后用JSON格式给出置信度评估:
{{"confidence": 0-100的数值, "key_reasons": ["理由1", "理由2", ...], "risk_factors": ["风险1", "风险2", ...]}}
"""

    async def _call_deepseek(self, prompt: str) -> str:
        """调用DeepSeek API"""
        if not DEEPSEEK_API_KEY:
            self.logger.warning("DeepSeek API Key未设置，返回默认结果")
            return '{"confidence": 60, "key_reasons": ["模拟分析"], "risk_factors": []}'
            
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    DEEPSEEK_API_URL,
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": DEEPSEEK_MODEL,
                        "messages": [
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.7,
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    self.logger.error(f"API返回错误: {response.status_code}")
                    return '{"confidence": 50, "key_reasons": [], "risk_factors": []}'
                    
        except Exception as e:
            self.logger.error(f"API调用失败: {e}")
            return '{"confidence": 50, "key_reasons": [], "risk_factors": []}'
            
    def _parse_confidence(self, result: str, side: str) -> float:
        """解析置信度"""
        try:
            import json
            # 尝试提取JSON
            start = result.find("{")
            end = result.find("}") + 1
            if start >= 0 and end > start:
                data = json.loads(result[start:end])
                return float(data.get("confidence", 50)) / 100
        except:
            pass
            
        # 默认置信度
        return 0.5
        
    def _extract_arguments(self, result: str) -> List[str]:
        """提取论证"""
        try:
            import json
            start = result.find("{")
            end = result.find("}") + 1
            if start >= 0 and end > start:
                data = json.loads(result[start:end])
                return data.get("key_reasons", [])
        except:
            pass
            
        return []
        
    def _generate_summary(self, bull: str, bear: str, direction: str) -> str:
        """生成辩论摘要"""
        bull_conf = self._parse_confidence(bull, "bull")
        bear_conf = self._parse_confidence(bear, "bear")
        
        return f"Bull置信度: {bull_conf*100:.0f}%, Bear置信度: {bear_conf*100:.0f}%, 方向: {direction}"
        
    def get_debate(self, symbol: str) -> Optional[DebateEvent]:
        """获取辩论结果"""
        return self._debate_cache.get(symbol)
