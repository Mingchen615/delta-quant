"""
Core模块 - 系统核心组件
包含消息总线、事件类型、Agent基类等
"""

from .base_agent import BaseAgent, AgentState
from .message_bus import MessageBus, message_bus
from .event_types import (
    MarketDataEvent,
    SignalEvent,
    DebateEvent,
    TradeProposal,
    RiskCheckResult,
    OrderEvent,
    PositionEvent,
    AgentStatusEvent,
    WhaleActivityEvent,
    SentimentEvent,
    CorrelationEvent,
    OrderFlowEvent,
    RegimeEvent,
    EventType,
)

__all__ = [
    "BaseAgent",
    "AgentState",
    "MessageBus",
    "message_bus",
    "MarketDataEvent",
    "SignalEvent",
    "DebateEvent",
    "TradeProposal",
    "RiskCheckResult",
    "OrderEvent",
    "PositionEvent",
    "AgentStatusEvent",
    "WhaleActivityEvent",
    "SentimentEvent",
    "CorrelationEvent",
    "OrderFlowEvent",
    "RegimeEvent",
    "EventType",
]
