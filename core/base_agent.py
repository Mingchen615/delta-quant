"""
BaseAgent - Agent基类
所有Agent的父类，提供通用功能：
- 异步生命周期管理
- 消息收发
- 状态机
- 心跳检测
- 错误恢复
"""

import asyncio
import signal
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass, field

from loguru import logger
from core.message_bus import MessageBus, message_bus
from core.event_types import AgentStatusEvent, EventType


class AgentState(str, Enum):
    """Agent状态枚举"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class AgentConfig:
    """Agent配置"""
    name: str
    log_prefix: str
    interval: float = 60.0  # 执行间隔(秒)
    enabled: bool = True
    restart_max: int = 3
    restart_delay: float = 5.0


class BaseAgent(ABC):
    """
    Agent基类
    
    提供:
    - 异步生命周期: start() -> run() -> stop()
    - 消息收发: subscribe() / publish()
    - 状态机: IDLE -> RUNNING -> STOPPED -> FAILED
    - 心跳检测、错误恢复
    - 独立日志前缀
    """
    
    def __init__(
        self,
        config: AgentConfig,
        bus: Optional[MessageBus] = None,
    ):
        """
        初始化Agent
        
        Args:
            config: Agent配置
            bus: 消息总线实例
        """
        self.config = config
        self.bus = bus or message_bus
        
        # 状态
        self.state = AgentState.IDLE
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        
        # 错误恢复
        self._error_count = 0
        self._last_error: Optional[str] = None
        self._last_execution: Optional[datetime] = None
        
        # 订阅管理
        self._subscriptions: List[str] = []
        
        # 日志配置
        self.logger = logger
        self._setup_logger()
        
    def _setup_logger(self):
        """配置日志"""
        # 添加带有前缀的日志处理器
        self.logger = logger.bind(
            prefix=self.config.log_prefix,
            agent=self.config.name
        )
        
    @property
    def name(self) -> str:
        """Agent名称"""
        return self.config.name
    
    @property
    def log_prefix(self) -> str:
        """日志前缀"""
        return self.config.log_prefix
        
    @property
    def is_running(self) -> bool:
        """是否运行中"""
        return self._running
    
    async def start(self):
        """
        启动Agent
        状态: IDLE -> STARTING -> RUNNING
        """
        if self.state in (AgentState.RUNNING, AgentState.STARTING):
            self.logger.warning("Agent已在运行中")
            return
            
        self.state = AgentState.STARTING
        self._error_count = 0
        self._running = True
        
        # 订阅默认主题
        await self._setup_subscriptions()
        
        # 启动主循环
        self._task = asyncio.create_task(self._run_loop())
        
        # 启动心跳
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        self.state = AgentState.RUNNING
        await self._publish_status("running")
        self.logger.info(f"{self.config.name} Agent已启动")
        
    async def stop(self):
        """
        停止Agent
        状态: RUNNING -> STOPPING -> STOPPED
        """
        if self.state in (AgentState.STOPPED, AgentState.IDLE):
            return
            
        self.state = AgentState.STOPPING
        self._running = False
        
        # 取消任务
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
                
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
                
        # 清理订阅
        await self._cleanup_subscriptions()
        
        self.state = AgentState.STOPPED
        await self._publish_status("stopped")
        self.logger.info(f"{self.config.name} Agent已停止")
        
    async def restart(self):
        """重启Agent"""
        self.logger.info(f"{self.config.name} 正在重启...")
        await self.stop()
        await asyncio.sleep(self.config.restart_delay)
        await self.start()
        
    async def _run_loop(self):
        """
        Agent主循环
        包含错误处理和自动重启
        """
        while self._running:
            try:
                # 执行主逻辑
                await self.execute()
                self._last_execution = datetime.now()
                self._error_count = 0
                
                # 等待下一个执行周期
                await asyncio.sleep(self.config.interval)
                
            except asyncio.CancelledError:
                break
                
            except Exception as e:
                self._error_count += 1
                self._last_error = str(e)
                
                self.logger.error(f"执行出错: {e}")
                
                if self._error_count >= self.config.restart_max:
                    self.logger.error(
                        f"错误次数过多({self._error_count}/{self.config.restart_max})，"
                        f"Agent进入FAILED状态"
                    )
                    self.state = AgentState.FAILED
                    await self._publish_status("failed", error=str(e))
                    break
                    
                # 自动重启
                self.logger.info(f"将在 {self.config.restart_delay}秒后重试...")
                await asyncio.sleep(self.config.restart_delay)
                
    async def _heartbeat_loop(self):
        """心跳循环"""
        from core.event_types import AgentStatusEvent
        
        while self._running:
            try:
                # 发布心跳
                await self.bus.publish(
                    "agent.status",
                    AgentStatusEvent(
                        agent_name=self.name,
                        state=self.state.value,
                        last_execution=self._last_execution,
                        error_count=self._error_count,
                        error_message=self._last_error,
                    )
                )
                
                await asyncio.sleep(30)  # 30秒心跳
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"心跳出错: {e}")
                
    async def _setup_subscriptions(self):
        """设置订阅 - 子类可重写"""
        pass
        
    async def _cleanup_subscriptions(self):
        """清理订阅"""
        for sub_id in self._subscriptions:
            # 简化清理，实际可以从订阅返回的信息中获取topic
            pass
        self._subscriptions.clear()
        
    async def _publish_status(self, state: str, error: Optional[str] = None):
        """发布状态事件"""
        from core.event_types import AgentStatusEvent
        
        await self.bus.publish(
            "agent.status",
            AgentStatusEvent(
                agent_name=self.name,
                state=state,
                last_execution=self._last_execution,
                error_count=self._error_count,
                error_message=error,
            )
        )
        
    async def subscribe(self, topic: str, callback: Callable):
        """订阅主题，并启动消息消费"""
        sub_id = await self.bus.subscribe(topic, callback, subscriber_id=self.name)
        self._subscriptions.append(sub_id)
        self.logger.debug(f"订阅主题: {topic}")
        # 启动该订阅的消息消费任务
        asyncio.create_task(self._consume_loop(topic, sub_id, callback))
        
    async def _consume_loop(self, topic: str, subscriber_id: str, callback: Callable):
        """消费消息队列，调用回调"""
        queue = await self.bus.get_queue(topic, subscriber_id)
        if not queue:
            self.logger.warning(f"消费循环启动失败: 队列不存在 [{topic}:{subscriber_id}]")
            return
        self.logger.debug(f"消费循环已启动: [{topic}] subscriber={subscriber_id}")
        while self._running:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=1.0)
                self.logger.debug(f"收到消息 [{topic}], 调用回调")
                await callback(data)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"消息处理出错 [{topic}]: {e}")

    async def publish(self, topic: str, data: Any):
        """发布消息"""
        await self.bus.publish(topic, data)
        
    @abstractmethod
    async def execute(self):
        """
        执行Agent逻辑 - 子类必须实现
        每个执行周期调用一次
        """
        pass
        
    async def on_error(self, error: Exception):
        """
        错误处理回调 - 可重写
        """
        self.logger.error(f"Agent错误: {error}")
        
    def get_status(self) -> Dict[str, Any]:
        """获取Agent状态"""
        return {
            "name": self.name,
            "state": self.state.value,
            "last_execution": self._last_execution,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "interval": self.config.interval,
        }


class DataAgent(BaseAgent):
    """数据采集层Agent基类"""
    
    async def _setup_subscriptions(self):
        """数据Agent订阅市场数据"""
        await super()._setup_subscriptions()


class AnalysisAgent(BaseAgent):
    """分析决策层Agent基类"""
    
    async def _setup_subscriptions(self):
        """分析Agent订阅信号"""
        await super()._setup_subscriptions()


class RiskAgent(BaseAgent):
    """风控执行层Agent基类"""
    
    async def _setup_subscriptions(self):
        """风控Agent订阅交易提案"""
        await super()._setup_subscriptions()


class PositionAgent(BaseAgent):
    """持仓复盘层Agent基类"""
    
    async def _setup_subscriptions(self):
        """持仓Agent订阅持仓事件"""
        await super()._setup_subscriptions()
