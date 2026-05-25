"""
事件日志收集器
收集Agent发布的事件，供Web界面展示
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from collections import deque


class EventCollector:
    """事件收集器 - 订阅消息总线，记录最近事件"""

    def __init__(self, max_events: int = 200):
        self._events: deque = deque(maxlen=max_events)
        self._orders: deque = deque(maxlen=100)
        self._lock = asyncio.Lock()
        self._consume_tasks: List[asyncio.Task] = []
        self._running = False

    async def subscribe_to_bus(self, bus, topics: List[str]):
        """订阅消息总线并启动消费循环"""
        self._running = True
        for topic in topics:
            sub_id = await bus.subscribe(
                topic, self._make_callback(topic), subscriber_id=f"event_collector"
            )
            task = asyncio.create_task(self._consume_loop(bus, topic, sub_id))
            self._consume_tasks.append(task)

    def _make_callback(self, topic: str):
        async def callback(data):
            await self.on_event(topic, data)
        return callback

    async def _consume_loop(self, bus, topic: str, subscriber_id: str):
        """消费消息队列"""
        queue = await bus.get_queue(topic, subscriber_id)
        if not queue:
            return
        while self._running:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=1.0)
                await self.on_event(topic, data)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[EventCollector] 消费出错 [{topic}]: {e}")

    async def stop(self):
        """停止消费"""
        self._running = False
        for task in self._consume_tasks:
            task.cancel()
        self._consume_tasks.clear()

    async def on_event(self, topic: str, data: Any):
        """通用事件回调"""
        event = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "topic": topic,
            "data": self._serialize(data),
        }
        async with self._lock:
            self._events.appendleft(event)

    async def on_order(self, data: Any):
        """订单事件回调"""
        async with self._lock:
            self._orders.appendleft({
                "time": datetime.now().strftime("%H:%M:%S"),
                "data": self._serialize(data),
            })

    def get_events(self, topic: str = None, limit: int = 50) -> List[Dict]:
        """获取最近事件"""
        events = list(self._events)
        if topic:
            events = [e for e in events if e["topic"] == topic]
        return events[:limit]

    def get_orders(self, limit: int = 50) -> List[Dict]:
        """获取最近订单"""
        return list(self._orders)[:limit]

    def get_agent_activity(self, limit: int = 30) -> List[Dict]:
        """获取Agent活动摘要"""
        activity = []
        for e in list(self._events)[:100]:
            topic = e["topic"]
            d = e["data"]
            if topic == "signal":
                activity.append({
                    "time": e["time"],
                    "agent": "信号趋势",
                    "action": "扫描信号",
                    "detail": f"{d.get('symbol','')} {d.get('direction','')} 分数:{d.get('score',0):.1f}",
                    "type": "signal",
                })
            elif topic == "debate":
                status = "通过" if d.get("approved") else "拒绝"
                activity.append({
                    "time": e["time"],
                    "agent": "多空辩论",
                    "action": f"辩论{status}",
                    "detail": f"{d.get('symbol','')} {d.get('direction','')} 置信度:{d.get('confidence',0):.1f}%",
                    "type": "debate",
                })
            elif topic == "trade_proposal":
                activity.append({
                    "time": e["time"],
                    "agent": "仓位决策",
                    "action": "交易提案",
                    "detail": f"{d.get('symbol','')} {d.get('direction','')} 杠杆:{d.get('leverage',0)}x 仓位:{d.get('position_pct',0)*100:.1f}%",
                    "type": "decision",
                })
            elif topic == "risk_check":
                status = "通过" if d.get("approved") else "拒绝"
                reasons = d.get("rejected_reasons", [])
                detail = status
                if reasons:
                    detail += f" - {reasons[0]}"
                activity.append({
                    "time": e["time"],
                    "agent": "风控检查",
                    "action": f"风控{status}",
                    "detail": detail,
                    "type": "risk",
                })
            elif topic == "portfolio_check":
                activity.append({
                    "time": e["time"],
                    "agent": "组合优化",
                    "action": "组合通过",
                    "detail": f"{d.get('symbol','')}",
                    "type": "portfolio",
                })
            elif topic in ("order_filled", "order_submitted"):
                activity.append({
                    "time": e["time"],
                    "agent": "订单执行",
                    "action": "下单" if topic == "order_submitted" else "成交",
                    "detail": f"{d.get('symbol','')} {d.get('side','')} 数量:{d.get('filled_quantity',0):.4f} 价格:{d.get('avg_fill_price',0):.2f}",
                    "type": "order",
                })
            elif topic == "order_failed":
                activity.append({
                    "time": e["time"],
                    "agent": "订单执行",
                    "action": "下单失败",
                    "detail": f"{d.get('symbol','')} {d.get('error','')}",
                    "type": "error",
                })
            elif topic == "whale_activity":
                activity.append({
                    "time": e["time"],
                    "agent": "鲸鱼监控",
                    "action": "大单",
                    "detail": f"{d.get('symbol','')} {d.get('direction','')} ${d.get('quote_quantity',0):,.0f}",
                    "type": "whale",
                })
            elif topic == "order_flow":
                activity.append({
                    "time": e["time"],
                    "agent": "订单流",
                    "action": "订单流",
                    "detail": f"{d.get('symbol','')} 不平衡:{d.get('imbalance',0):.2f}",
                    "type": "orderflow",
                })
            elif topic == "position.opened":
                activity.append({
                    "time": e["time"],
                    "agent": "持仓监控",
                    "action": "开仓",
                    "detail": f"{d.get('symbol','')} {d.get('direction','')} 入场:${d.get('entry_price',0):.4f}",
                    "type": "position",
                })
            elif topic == "position.closed":
                activity.append({
                    "time": e["time"],
                    "agent": "持仓监控",
                    "action": "平仓",
                    "detail": f"{d.get('symbol','')} 盈亏:${d.get('realized_pnl',0):.2f} {d.get('close_reason','')}",
                    "type": "position",
                })
            if len(activity) >= limit:
                break
        return activity

    def _serialize(self, data: Any) -> Dict:
        """序列化事件数据"""
        if hasattr(data, "model_dump"):
            return data.model_dump(mode="json")
        elif hasattr(data, "__dict__"):
            return {k: str(v) for k, v in data.__dict__.items() if not k.startswith("_")}
        elif isinstance(data, dict):
            return data
        return {"value": str(data)}
