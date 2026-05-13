"""
异步消息总线
基于asyncio.Queue的pub/sub实现
支持通配符订阅和背压控制
"""

import asyncio
import re
from typing import Dict, List, Callable, Any, Set, Optional
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger
from collections import defaultdict


@dataclass
class Subscription:
    """订阅记录"""
    topic: str
    callback: Callable
    subscriber_id: str
    created_at: datetime = field(default_factory=datetime.now)
    active: bool = True


class MessageBus:
    """
    异步消息总线
    实现发布-订阅模式，支持通配符匹配
    """
    
    def __init__(self, max_queue_size: int = 1000):
        """
        初始化消息总线
        
        Args:
            max_queue_size: 每个订阅者的最大队列长度
        """
        self._subscribers: Dict[str, List[Subscription]] = defaultdict(list)
        self._queues: Dict[str, asyncio.Queue] = {}
        self._max_queue_size = max_queue_size
        self._lock = asyncio.Lock()
        self._running = False
        self._message_count = 0
        self._stats = {
            "published": 0,
            "delivered": 0,
            "dropped": 0,
        }
        
    async def start(self):
        """启动消息总线"""
        self._running = True
        logger.info("[消息总线] 消息总线已启动")
        
    async def stop(self):
        """停止消息总线"""
        self._running = False
        # 清空所有队列
        for queue in self._queues.values():
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        logger.info(f"[消息总线] 消息总线已停止, 共发布 {self._stats['published']} 条消息")
        
    def _match_topic(self, pattern: str, topic: str) -> bool:
        """
        匹配topic，支持通配符
        支持:
            - exact: "market.btc" 精确匹配
            - wildcard: "market.*" 匹配单层
            - glob: "market.#" 匹配多层
        """
        if pattern == topic:
            return True
        
        # 转换为正则
        regex = pattern.replace(".", r"\\.").replace("*", "[^.]+").replace("#", ".+")
        regex = f"^{regex}$"
        
        return bool(re.match(regex, topic))
    
    async def subscribe(
        self, 
        topic: str, 
        callback: Callable[[Any], None],
        subscriber_id: Optional[str] = None
    ) -> str:
        """
        订阅主题
        
        Args:
            topic: 主题名称，支持通配符
            callback: 回调函数
            subscriber_id: 订阅者ID
            
        Returns:
            订阅ID
        """
        async with self._lock:
            if subscriber_id is None:
                subscriber_id = f"sub_{len(self._subscribers[topic])}_{datetime.now().timestamp()}"
                
            sub = Subscription(
                topic=topic,
                callback=callback,
                subscriber_id=subscriber_id
            )
            
            self._subscribers[topic].append(sub)
            
            # 为每个订阅者创建独立队列
            queue_key = f"{topic}:{subscriber_id}"
            self._queues[queue_key] = asyncio.Queue(maxsize=self._max_queue_size)
            
            logger.debug(f"[消息总线] 订阅成功: {topic} by {subscriber_id}")
            return subscriber_id
        
    async def unsubscribe(self, topic: str, subscriber_id: str):
        """取消订阅"""
        async with self._lock:
            subs = self._subscribers.get(topic, [])
            for sub in subs:
                if sub.subscriber_id == subscriber_id:
                    sub.active = False
                    
            # 清理队列
            queue_key = f"{topic}:{subscriber_id}"
            if queue_key in self._queues:
                del self._queues[queue_key]
                
            logger.debug(f"[消息总线] 取消订阅: {topic} by {subscriber_id}")
            
    async def publish(self, topic: str, data: Any):
        """
        发布消息到主题
        
        Args:
            topic: 主题名称
            data: 消息数据
        """
        if not self._running:
            return
            
        self._message_count += 1
        self._stats["published"] += 1
        
        async with self._lock:
            # 查找所有匹配的订阅者
            matched_subs = []
            for pattern, subs in self._subscribers.items():
                if self._match_topic(pattern, topic):
                    matched_subs.extend([s for s in subs if s.active])
        
        # 发送到所有匹配的队列
        for sub in matched_subs:
            queue_key = f"{sub.topic}:{sub.subscriber_id}"
            if queue_key in self._queues:
                try:
                    self._queues[queue_key].put_nowait(data)
                    self._stats["delivered"] += 1
                except asyncio.QueueFull:
                    # 队列满，丢弃旧消息
                    try:
                        self._queues[queue_key].get_nowait()
                        self._queues[queue_key].put_nowait(data)
                        self._stats["dropped"] += 1
                        logger.warning(f"[消息总线] 队列已满，丢弃旧消息: {sub.subscriber_id}")
                    except asyncio.QueueEmpty:
                        pass
                        
        logger.debug(f"[消息总线] 发布: {topic}, 匹配 {len(matched_subs)} 个订阅者")
        
    async def get_queue(self, topic: str, subscriber_id: str) -> asyncio.Queue:
        """获取订阅者的消息队列"""
        queue_key = f"{topic}:{subscriber_id}"
        return self._queues.get(queue_key)
        
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self._stats.copy()
    
    def get_subscriber_count(self, topic: Optional[str] = None) -> int:
        """获取订阅者数量"""
        if topic:
            return len(self._subscribers.get(topic, []))
        return sum(len(subs) for subs in self._subscribers.values())


# 全局消息总线实例
message_bus = MessageBus()
