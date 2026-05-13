#!/usr/bin/env python3
"""
Delta Quant - 13 Agent量化交易系统
主入口文件
"""

import asyncio
import signal
import sys
from datetime import datetime
from typing import Dict, List

from loguru import logger

from config import (
    BINANCE_API_KEY, DEEPSEEK_API_KEY, BINANCE_TESTNET,
    LOG_FORMAT, LOG_LEVEL
)
from core import MessageBus, AgentState
from core.base_agent import BaseAgent, AgentConfig
from exchange.paper_trade import PaperTradeEngine

# 导入所有Agent
from agents import (
    # 数据采集层
    NewsAgent,
    WhaleAgent,
    CorrelationAgent,
    OrderFlowAgent,
    RegimeAgent,
    # 分析决策层
    SignalAgent,
    DebateAgent,
    DecisionAgent,
    # 风控执行层
    RiskAgent,
    PortfolioAgent,
    ExecutorAgent,
    # 持仓复盘层
    PositionAgent,
    ReviewAgent,
)


class DeltaQuantSystem:
    """
    Delta Quant系统主控
    管理13个Agent的启动、运行、状态监控
    """
    
    def __init__(self):
        # 消息总线
        self.bus = MessageBus()
        
        # 模拟交易引擎
        self.paper_engine = PaperTradeEngine()
        
        # Agent列表
        self.agents: Dict[str, BaseAgent] = {}
        
        # 运行状态
        self._running = False
        self._status_task: asyncio.Task = None
        
    def _setup_logging(self):
        """配置日志"""
        logger.remove()
        logger.add(
            sys.stderr,
            format=LOG_FORMAT,
            level=LOG_LEVEL,
            colorize=True,
        )
        # 同时输出到文件
        logger.add(
            "logs/delta_quant_{time:YYYY-MM-DD}.log",
            rotation="00:00",
            retention="7 days",
            format=LOG_FORMAT,
            level="DEBUG",
        )
        
    def _check_config(self):
        """检查配置"""
        missing = []
        
        if not BINANCE_API_KEY:
            missing.append("BINANCE_API_KEY")
        if not DEEPSEEK_API_KEY:
            logger.warning("DEEPSEEK_API_KEY未设置，辩论Agent将使用默认结果")
            
        if missing:
            logger.warning(f"以下配置未设置: {', '.join(missing)}")
            logger.warning("请在config/settings.py或环境变量中配置")
            
        if BINANCE_TESTNET:
            logger.info("🔧 运行模式: 模拟盘 (Testnet)")
        else:
            logger.info("🔴 运行模式: 实盘 (请谨慎!)")
            
    def _create_agents(self):
        """创建所有Agent"""
        configs = {
            # 数据采集层
            "news_agent": AgentConfig(
                name="新闻数据",
                log_prefix="[新闻数据]",
                interval=60,
            ),
            "whale_agent": AgentConfig(
                name="鲸鱼监控",
                log_prefix="[鲸鱼监控]",
                interval=5,
            ),
            "correlation_agent": AgentConfig(
                name="相关性计算",
                log_prefix="[相关性计算]",
                interval=300,
            ),
            "orderflow_agent": AgentConfig(
                name="订单流",
                log_prefix="[订单流]",
                interval=3,
            ),
            "regime_agent": AgentConfig(
                name="市场状态",
                log_prefix="[市场状态]",
                interval=60,
            ),
            # 分析决策层
            "signal_agent": AgentConfig(
                name="信号趋势",
                log_prefix="[信号趋势]",
                interval=300,
            ),
            "debate_agent": AgentConfig(
                name="多空辩论",
                log_prefix="[多空辩论]",
                interval=0,
            ),
            "decision_agent": AgentConfig(
                name="仓位决策",
                log_prefix="[仓位决策]",
                interval=0,
            ),
            # 风控执行层
            "risk_agent": AgentConfig(
                name="风控检查",
                log_prefix="[风控检查]",
                interval=0,
            ),
            "portfolio_agent": AgentConfig(
                name="组合优化",
                log_prefix="[组合优化]",
                interval=0,
            ),
            "executor_agent": AgentConfig(
                name="订单执行",
                log_prefix="[订单执行]",
                interval=0,
            ),
            # 持仓复盘层
            "position_agent": AgentConfig(
                name="持仓监控",
                log_prefix="[持仓监控]",
                interval=1,
            ),
            "review_agent": AgentConfig(
                name="复盘统计",
                log_prefix="[复盘统计]",
                interval=86400,
            ),
        }
        
        # 创建Agent实例
        self.agents["news_agent"] = NewsAgent(configs["news_agent"], bus=self.bus)
        self.agents["whale_agent"] = WhaleAgent(configs["whale_agent"], bus=self.bus)
        self.agents["correlation_agent"] = CorrelationAgent(configs["correlation_agent"], bus=self.bus)
        self.agents["orderflow_agent"] = OrderFlowAgent(configs["orderflow_agent"], bus=self.bus)
        self.agents["regime_agent"] = RegimeAgent(configs["regime_agent"], bus=self.bus)
        
        self.agents["signal_agent"] = SignalAgent(configs["signal_agent"], bus=self.bus)
        self.agents["debate_agent"] = DebateAgent(configs["debate_agent"], bus=self.bus)
        self.agents["decision_agent"] = DecisionAgent(configs["decision_agent"], bus=self.bus)
        
        self.agents["risk_agent"] = RiskAgent(configs["risk_agent"], bus=self.bus)
        self.agents["portfolio_agent"] = PortfolioAgent(configs["portfolio_agent"], bus=self.bus)
        self.agents["executor_agent"] = ExecutorAgent(
            configs["executor_agent"], 
            bus=self.bus,
            paper_engine=self.paper_engine
        )
        
        self.agents["position_agent"] = PositionAgent(
            configs["position_agent"],
            bus=self.bus,
            paper_engine=self.paper_engine
        )
        self.agents["review_agent"] = ReviewAgent(configs["review_agent"], bus=self.bus)
        
    async def start(self):
        """启动系统"""
        self._setup_logging()
        self._check_config()
        
        logger.info("=" * 70)
        logger.info("🚀 Delta Quant - 13 Agent量化交易系统 v8.0")
        logger.info("=" * 70)
        
        # 创建目录
        import os
        os.makedirs("logs", exist_ok=True)
        os.makedirs("data", exist_ok=True)
        
        # 初始化消息总线
        await self.bus.start()
        
        # 创建Agent
        self._create_agents()
        
        # 启动所有Agent
        logger.info("\n📦 启动Agent...")
        for name, agent in self.agents.items():
            await agent.start()
            
        self._running = True
        
        # 启动状态监控
        self._status_task = asyncio.create_task(self._status_loop())
        
        logger.info("\n" + "=" * 70)
        logger.info("✅ 系统启动成功!")
        logger.info("=" * 70)
        logger.info("\n按 Ctrl+C 停止系统\n")
        
    async def stop(self):
        """停止系统"""
        logger.info("\n正在停止系统...")
        self._running = False
        
        # 停止状态监控
        if self._status_task:
            self._status_task.cancel()
            try:
                await self._status_task
            except asyncio.CancelledError:
                pass
                
        # 停止所有Agent
        for name, agent in self.agents.items():
            await agent.stop()
            
        # 停止消息总线
        await self.bus.stop()
        
        # 打印最终统计
        self._print_final_stats()
        
        logger.info("\n系统已停止")
        
    async def _status_loop(self):
        """状态监控循环"""
        while self._running:
            self._print_status()
            await asyncio.sleep(10)
            
    def _print_status(self):
        """打印状态面板"""
        # 获取当前时间
        now = datetime.now().strftime("%H:%M:%S")
        
        # 构建表格
        header = f"\n{'='*70}"
        header += f"\n🔮 Delta Quant 状态面板 | {now}"
        header += f"\n{'='*70}"
        
        # Agent状态
        lines = ["\nAgent名称                  | 最后执行           | 状态"]
        lines.append("-" * 60)
        
        for name, agent in self.agents.items():
            status = agent.state.value.upper()
            last_exec = (
                agent._last_execution.strftime("%H:%M:%S")
                if agent._last_execution else "N/A"
            )
            
            # 状态颜色
            color = ""
            if status == "RUNNING":
                color = "🟢"
            elif status == "FAILED":
                color = "🔴"
            elif status == "STOPPED":
                color = "⚪"
            else:
                color = "🟡"
                
            lines.append(
                f"{color} {agent.name:<24}| {last_exec:<18}| {status}"
            )
            
        # 模拟账户状态
        stats = self.paper_engine.get_stats()
        footer = "\n" + "-" * 60
        footer += f"\n💰 模拟账户 | 余额: ${stats['balance']:.2f} | "
        footer += f"盈亏: ${stats['total_pnl']:.2f} ({stats.get('profit_pct', 0)*100:.2f}%)"
        footer += f" | 交易: {stats['total_trades']} | "
        footer += f"胜率: {stats.get('win_rate', 0)*100:.1f}%"
        
        # 持仓状态
        positions = self.paper_engine.get_positions()
        if positions:
            footer += "\n" + "-" * 60
            footer += "\n📊 当前持仓:"
            for symbol, pos in positions.items():
                pnl = self.paper_engine.get_unrealized_pnl(symbol, pos.entry_price)
                footer += f"\n  {symbol}: {pos.direction.upper()} "
                footer += f"@ ${pos.entry_price:.4f} x{pos.leverage} "
                footer += f"数量: {pos.quantity:.4f} "
                pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                footer += f"浮动盈亏: {pnl_str}"
        else:
            footer += "\n" + "-" * 60
            footer += "\n📊 当前持仓: 无"
            
        # 消息总线统计
        bus_stats = self.bus.get_stats()
        footer += f"\n📨 消息总线 | 发布: {bus_stats['published']} | "
        footer += f"投递: {bus_stats['delivered']} | "
        footer += f"丢弃: {bus_stats['dropped']}"
        
        footer += "\n" + "=" * 70
        
        # 打印
        print(header)
        for line in lines:
            print(line)
        print(footer)
        
    def _print_final_stats(self):
        """打印最终统计"""
        stats = self.paper_engine.get_stats()
        
        print("\n" + "=" * 70)
        print("📊 最终交易统计")
        print("=" * 70)
        print(f"总交易次数: {stats['total_trades']}")
        print(f"盈利次数: {stats['winning_trades']}")
        print(f"亏损次数: {stats['losing_trades']}")
        print(f"胜率: {stats.get('win_rate', 0)*100:.2f}%")
        print(f"总盈亏: ${stats['total_pnl']:.2f}")
        print(f"最终余额: ${stats['balance']:.2f}")
        print(f"最大回撤: {stats['max_drawdown']*100:.2f}%")
        print("=" * 70)


async def main():
    """主函数"""
    system = DeltaQuantSystem()
    
    # 信号处理
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        asyncio.create_task(system.stop())
        
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
        
    try:
        await system.start()
        
        # 保持运行
        while system._running:
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        pass
    finally:
        await system.stop()


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║                                                                  ║
    ║     ██████╗  ██████╗  ██████╗  ██████╗ ██████╗ ██╗   ██╗███████╗║
    ║     ██╔══██╗██╔════╝ ██╔════╝ ██╔══██╗██╔══██╗╚██╗ ██╔╝██╔════╝║
    ║     ██████╔╝██║  ███╗██║  ███╗██████╔╝██████╔╝ ╚████╔╝ ███████╗║
    ║     ██╔═══╝ ██║   ██║██║   ██║██╔══██╗██╔══██╗  ╚██╔╝  ╚════██║║
    ║     ██║     ╚██████╔╝╚██████╔╝██████╔╝██████╔╝   ██║   ███████║║
    ║     ╚═╝      ╚═════╝  ╚═════╝ ╚═════╝ ╚═════╝    ╚═╝   ╚══════╝║
    ║                                                                  ║
    ║              13 Agent量化交易系统 v8.0                            ║
    ║              异步架构 · Python 3.10+                              ║
    ║                                                                  ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)
    
    asyncio.run(main())
