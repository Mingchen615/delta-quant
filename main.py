#!/usr/bin/env python3
"""
Delta Quant v9.0 - 双平台量化交易系统
主入口文件
"""

import asyncio
import signal
import sys
import threading
from datetime import datetime
from typing import Dict

from loguru import logger

from config import (
    BINANCE_API_KEY, DEEPSEEK_API_KEY,
    OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE,
    LIVE_TRADE, WEB_HOST, WEB_PORT,
    LOG_FORMAT, LOG_LEVEL,
)
from core import MessageBus, AgentState
from core.base_agent import BaseAgent, AgentConfig
from core.event_log import EventCollector
from exchange.paper_trade import PaperTradeEngine

# 交易所层
from exchange.binance_exchange import BinanceExchange
from exchange.okx_exchange import OKXExchange
from exchange.exchange_router import ExchangeRouter
from exchange.credentials import CredentialManager
from exchange.qr_auth import QRAuthManager

# 导入所有Agent
from agents import (
    NewsAgent, WhaleAgent, CorrelationAgent, OrderFlowAgent, RegimeAgent,
    ArbitrageAgent,
    SignalAgent, DebateAgent, DecisionAgent,
    RiskAgent, PortfolioAgent, ExecutorAgent,
    PositionAgent, ReviewAgent,
)


class DeltaQuantSystem:
    """
    Delta Quant v9.0 系统主控
    管理14个Agent的启动、运行、状态监控
    支持币安+OKX双平台实盘交易
    """

    def __init__(self):
        # 消息总线
        self.bus = MessageBus()

        # 事件日志收集器
        self.event_collector = EventCollector()

        # 模拟交易引擎
        self.paper_engine = PaperTradeEngine()

        # 交易所路由器
        self.router = ExchangeRouter()

        # 凭证管理
        self.credential_manager = CredentialManager()

        # 扫码授权
        self.qr_auth_manager = QRAuthManager()

        # Agent列表
        self.agents: Dict[str, BaseAgent] = {}

        # 运行状态
        self._running = False
        self._status_task: asyncio.Task = None
        self._web_thread = None

    def _setup_logging(self):
        """配置日志"""
        logger.remove()
        logger.add(
            sys.stderr,
            format=LOG_FORMAT,
            level=LOG_LEVEL,
            colorize=True,
        )
        logger.add(
            "logs/delta_quant_{time:YYYY-MM-DD}.log",
            rotation="00:00",
            retention="7 days",
            format=LOG_FORMAT,
            level="DEBUG",
        )

    def _check_config(self):
        """检查配置"""
        if LIVE_TRADE:
            logger.info("🔴 运行模式: 实盘 (请谨慎!)")
        else:
            logger.info("🔧 运行模式: 模拟盘")

        if not BINANCE_API_KEY and not self.credential_manager.has_credentials("binance"):
            logger.warning("币安API Key未配置")
        if not OKX_API_KEY and not self.credential_manager.has_credentials("okx"):
            logger.warning("OKX API Key未配置")

    async def _init_exchanges(self):
        """初始化交易所连接 - 只注册有有效凭证的交易所"""
        # 币安 - 优先用加密存储的凭证
        binance_creds = self.credential_manager.load_credentials("binance")
        api_key = binance_creds.get("api_key") or BINANCE_API_KEY
        api_secret = binance_creds.get("api_secret") or ""

        if api_key:
            binance = BinanceExchange(api_key, api_secret)
            self.router.register("binance", binance)

        # OKX - 优先用加密存储的凭证
        okx_creds = self.credential_manager.load_credentials("okx")
        okx_key = okx_creds.get("api_key") or OKX_API_KEY
        okx_secret = okx_creds.get("api_secret") or OKX_API_SECRET
        okx_pass = okx_creds.get("passphrase") or OKX_PASSPHRASE

        if okx_key:
            okx = OKXExchange(okx_key, okx_secret, okx_pass)
            self.router.register("okx", okx)

        # 连接所有交易所
        results = await self.router.connect_all()
        for name, success in results.items():
            if success:
                # 验证API Key是否真正有效（尝试获取余额）
                try:
                    ex = self.router.exchanges[name]
                    balance = await ex.get_balance()
                    logger.info(f"✅ {name} 连接成功, 余额: ${balance.total:.2f}")
                except Exception as e:
                    # API Key无效，标记为未连接
                    ex._connected = False
                    logger.warning(f"⚠️ {name} API Key无效，已跳过: {str(e)[:100]}")
            else:
                logger.warning(f"⚠️ {name} 连接失败")

    def _create_agents(self):
        """创建所有Agent"""
        configs = {
            "news_agent": AgentConfig(name="新闻数据", log_prefix="[新闻数据]", interval=60),
            "whale_agent": AgentConfig(name="鲸鱼监控", log_prefix="[鲸鱼监控]", interval=5),
            "correlation_agent": AgentConfig(name="相关性计算", log_prefix="[相关性计算]", interval=300),
            "orderflow_agent": AgentConfig(name="订单流", log_prefix="[订单流]", interval=3),
            "regime_agent": AgentConfig(name="市场状态", log_prefix="[市场状态]", interval=60),
            "arbitrage_agent": AgentConfig(name="跨平台套利", log_prefix="[套利]", interval=1),
            "signal_agent": AgentConfig(name="信号趋势", log_prefix="[信号趋势]", interval=300),
            "debate_agent": AgentConfig(name="多空辩论", log_prefix="[多空辩论]", interval=60),
            "decision_agent": AgentConfig(name="仓位决策", log_prefix="[仓位决策]", interval=60),
            "risk_agent": AgentConfig(name="风控检查", log_prefix="[风控检查]", interval=60),
            "portfolio_agent": AgentConfig(name="组合优化", log_prefix="[组合优化]", interval=60),
            "executor_agent": AgentConfig(name="订单执行", log_prefix="[订单执行]", interval=60),
            "position_agent": AgentConfig(name="持仓监控", log_prefix="[持仓监控]", interval=1),
            "review_agent": AgentConfig(name="复盘统计", log_prefix="[复盘统计]", interval=86400),
        }

        # 数据采集层
        self.agents["news_agent"] = NewsAgent(configs["news_agent"], bus=self.bus)
        self.agents["whale_agent"] = WhaleAgent(configs["whale_agent"], bus=self.bus)
        self.agents["correlation_agent"] = CorrelationAgent(configs["correlation_agent"], bus=self.bus)
        self.agents["orderflow_agent"] = OrderFlowAgent(configs["orderflow_agent"], bus=self.bus)
        self.agents["regime_agent"] = RegimeAgent(configs["regime_agent"], bus=self.bus)
        self.agents["arbitrage_agent"] = ArbitrageAgent(configs["arbitrage_agent"], bus=self.bus)

        # 分析决策层
        self.agents["signal_agent"] = SignalAgent(configs["signal_agent"], bus=self.bus)
        self.agents["debate_agent"] = DebateAgent(configs["debate_agent"], bus=self.bus)
        self.agents["decision_agent"] = DecisionAgent(configs["decision_agent"], bus=self.bus)

        # 风控执行层
        self.agents["risk_agent"] = RiskAgent(configs["risk_agent"], bus=self.bus)
        self.agents["portfolio_agent"] = PortfolioAgent(configs["portfolio_agent"], bus=self.bus)
        self.agents["executor_agent"] = ExecutorAgent(
            configs["executor_agent"], bus=self.bus, paper_engine=self.paper_engine
        )

        # 持仓复盘层
        self.agents["position_agent"] = PositionAgent(
            configs["position_agent"], bus=self.bus, paper_engine=self.paper_engine
        )
        self.agents["review_agent"] = ReviewAgent(configs["review_agent"], bus=self.bus)

        # 设置路由器到需要双平台的Agent
        for name in ["whale_agent", "orderflow_agent", "risk_agent",
                      "position_agent", "executor_agent", "arbitrage_agent",
                      "signal_agent", "correlation_agent", "regime_agent"]:
            agent = self.agents.get(name)
            if agent and hasattr(agent, "set_router"):
                agent.set_router(self.router)

    async def start(self):
        """启动系统"""
        self._setup_logging()
        self._check_config()

        logger.info("=" * 70)
        logger.info("🚀 Delta Quant v9.0 - 双平台量化交易系统")
        logger.info("=" * 70)

        # 创建目录
        import os
        os.makedirs("logs", exist_ok=True)
        os.makedirs("data", exist_ok=True)

        # 初始化消息总线
        await self.bus.start()

        # 订阅事件收集器到关键事件
        await self.event_collector.subscribe_to_bus(self.bus, [
            "signal", "debate", "trade_proposal",
            "risk_check", "portfolio_check",
            "order_submitted", "order_filled", "order_failed",
            "whale_activity", "order_flow",
            "position.opened", "position.closed",
        ])

        # 初始化交易所
        await self._init_exchanges()

        # 创建Agent
        self._create_agents()

        # 启动所有Agent
        logger.info("\n📦 启动Agent...")
        for name, agent in self.agents.items():
            await agent.start()

        self._running = True

        # 启动状态监控
        self._status_task = asyncio.create_task(self._status_loop())

        # 启动Web服务器（可选）
        self._start_web_server()

        logger.info("\n" + "=" * 70)
        logger.info("✅ 系统启动成功!")
        logger.info("=" * 70)
        logger.info(f"模式: {'实盘' if LIVE_TRADE else '模拟盘'}")
        logger.info(f"交易所: {', '.join(self.router.exchanges.keys())}")
        logger.info(f"Agent数量: {len(self.agents)}")
        logger.info("\n按 Ctrl+C 停止系统\n")

    def _start_web_server(self):
        """启动Web服务器（在后台线程）"""
        try:
            from web.app import create_app, run_web_server, set_main_loop
            # 设置主事件循环引用，让Web线程中的ccxt调用路由回主线程
            set_main_loop(asyncio.get_event_loop())
            app = create_app(
                router=self.router,
                credential_manager=self.credential_manager,
                qr_auth_manager=self.qr_auth_manager,
                paper_engine=self.paper_engine,
                agents=self.agents,
                event_collector=self.event_collector,
            )
            if app:
                self._web_thread = threading.Thread(
                    target=run_web_server,
                    args=(app, WEB_HOST, WEB_PORT),
                    daemon=True,
                )
                self._web_thread.start()
                logger.info(f"🌐 Web管理界面: http://{WEB_HOST}:{WEB_PORT}")
        except ImportError:
            logger.info("Web界面依赖未安装，跳过Web服务")
        except Exception as e:
            logger.warning(f"Web服务启动失败: {e}")

    async def stop(self):
        """停止系统"""
        logger.info("\n正在停止系统...")
        self._running = False

        if self._status_task:
            self._status_task.cancel()
            try:
                await self._status_task
            except asyncio.CancelledError:
                pass

        # 停止所有Agent
        for name, agent in self.agents.items():
            await agent.stop()

        # 停止事件收集器
        await self.event_collector.stop()

        # 断开交易所
        await self.router.disconnect_all()

        # 停止消息总线
        await self.bus.stop()

        self._print_final_stats()
        logger.info("\n系统已停止")

    async def emergency_close_all(self):
        """紧急全平所有持仓"""
        logger.warning("⚠️ 紧急全平所有持仓!")
        results = await self.router.close_all_positions()
        for r in results:
            if "error" in r:
                logger.error(f"平仓失败: {r}")
            else:
                logger.info(f"平仓成功: {r}")
        return results

    async def _status_loop(self):
        """状态监控循环"""
        while self._running:
            self._print_status()
            await asyncio.sleep(10)

    def _print_status(self):
        """打印状态面板"""
        now = datetime.now().strftime("%H:%M:%S")

        header = f"\n{'='*70}"
        header += f"\n🔮 Delta Quant v9.0 状态面板 | {now}"
        header += f"\n{'='*70}"

        lines = ["\nAgent名称                  | 最后执行           | 状态"]
        lines.append("-" * 60)

        for name, agent in self.agents.items():
            status = agent.state.value.upper()
            last_exec = (
                agent._last_execution.strftime("%H:%M:%S")
                if agent._last_execution else "N/A"
            )

            if status == "RUNNING":
                color = "🟢"
            elif status == "FAILED":
                color = "🔴"
            elif status == "STOPPED":
                color = "⚪"
            else:
                color = "🟡"

            lines.append(f"{color} {agent.name:<24}| {last_exec:<18}| {status}")

        # 交易所状态
        footer = "\n" + "-" * 60
        footer += "\n💱 交易所:"
        for name, ex in self.router.exchanges.items():
            status = "已连接" if ex.is_connected else "未连接"
            icon = "🟢" if ex.is_connected else "🔴"
            footer += f" {icon}{name}:{status}"

        # 模拟账户状态（非实盘模式）
        if not LIVE_TRADE:
            stats = self.paper_engine.get_stats()
            footer += f"\n💰 模拟账户 | 余额: ${stats['balance']:.2f} | "
            footer += f"盈亏: ${stats['total_pnl']:.2f} ({stats.get('profit_pct', 0)*100:.2f}%)"
            footer += f" | 交易: {stats['total_trades']} | "
            footer += f"胜率: {stats.get('win_rate', 0)*100:.1f}%"

        # 套利统计
        arb_agent = self.agents.get("arbitrage_agent")
        if arb_agent and hasattr(arb_agent, "get_stats"):
            arb_stats = arb_agent.get_stats()
            footer += f"\n📊 套利 | 机会: {arb_stats.get('total_opportunities', 0)} | "
            footer += f"累计利润: {arb_stats.get('total_profit_pct', 0):.4%}"

        # 消息总线统计
        bus_stats = self.bus.get_stats()
        footer += f"\n📨 消息总线 | 发布: {bus_stats['published']} | "
        footer += f"投递: {bus_stats['delivered']} | "
        footer += f"丢弃: {bus_stats['dropped']}"

        footer += "\n" + "=" * 70

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

    loop = asyncio.get_event_loop()

    def signal_handler():
        asyncio.create_task(system.stop())

    import platform
    if platform.system() != "Windows":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

    try:
        await system.start()

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
    ║     ╚═╝      ╚═════╝  ╚═════╝  ╚═════╝  ╚═════╝    ╚═╝   ╚══════╝║
    ║                                                                  ║
    ║              双平台量化交易系统 v9.0                               ║
    ║              币安 + OKX · 异步架构 · Python 3.10+                 ║
    ║                                                                  ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)

    asyncio.run(main())
