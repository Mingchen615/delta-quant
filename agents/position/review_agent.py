"""
13. 复盘统计 Agent
记录交易、计算统计、生成报告
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from loguru import logger

from core.base_agent import BaseAgent, AgentConfig
from core.event_types import PositionEvent
from data.storage import Database, TradeRecord
from config import DATABASE_PATH


class ReviewAgent(BaseAgent):
    """
    复盘统计Agent
    
    功能:
    - 记录每笔交易日志
    - 计算胜率、盈亏比、Sharpe、最大回撤
    - 每日生成复盘报告
    - 输出到SQLite
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        default_config = AgentConfig(
            name="复盘统计",
            log_prefix="[复盘统计]",
            interval=86400,  # 每天生成报告
            enabled=True,
        )
        super().__init__(config or default_config, **kwargs)
        
        self._db: Optional[Database] = None
        self._open_trades: Dict[str, TradeRecord] = {}  # symbol -> trade
        
    async def _setup_subscriptions(self):
        """设置订阅"""
        await self.subscribe("position.opened", self._on_position_opened)
        await self.subscribe("position.closed", self._on_position_closed)
        
    async def execute(self):
        """生成复盘报告"""
        if not self._db:
            await self._init_db()
            
        # 生成日报
        await self._generate_daily_report()
        
    async def _init_db(self):
        """初始化数据库"""
        self._db = Database(str(DATABASE_PATH))
        await self._db.connect()
        
    async def _on_position_opened(self, event: PositionEvent):
        """持仓开仓"""
        trade = TradeRecord(
            symbol=event.symbol,
            direction=event.direction,
            entry_price=event.entry_price,
            quantity=event.quantity,
            leverage=event.leverage,
            stop_loss=event.stop_loss or 0,
            take_profit=event.take_profit or 0,
            entry_time=event.opened_at,
        )
        
        # 保存到数据库
        if self._db:
            trade.id = await self._db.save_trade(trade)
            
        self._open_trades[event.symbol] = trade
        
        self.logger.info(
            f"交易记录: 开仓 {event.symbol} {event.direction.upper()} "
            f"@ ${event.entry_price:.4f}"
        )
        
    async def _on_position_closed(self, event: PositionEvent):
        """持仓平仓"""
        symbol = event.symbol
        
        if symbol not in self._open_trades:
            self.logger.warning(f"平仓记录找不到开仓: {symbol}")
            return
            
        trade = self._open_trades[symbol]
        
        # 更新交易记录
        trade.exit_price = event.exit_price
        trade.exit_time = event.closed_at
        trade.pnl = event.realized_pnl
        trade.pnl_pct = event.unrealized_pnl_pct
        trade.close_reason = event.close_reason
        
        # 计算R数
        if trade.entry_price > 0:
            if trade.direction == "long":
                trade.notes = f"R={event.realized_pnl / (trade.entry_price * trade.quantity)}"
            else:
                trade.notes = f"R={event.realized_pnl / (trade.entry_price * trade.quantity)}"
                
        # 保存到数据库
        if self._db:
            await self._db.update_trade(trade)
            
        # 移除开仓记录
        del self._open_trades[symbol]
        
        self.logger.info(
            f"交易记录: 平仓 {symbol} {event.close_reason} "
            f"盈亏: ${event.realized_pnl:.2f} ({event.unrealized_pnl_pct*100:.2f}%)"
        )
        
        # 实时计算统计
        await self._log_stats()
        
    async def _generate_daily_report(self):
        """生成每日复盘报告"""
        if not self._db:
            return
            
        today = datetime.now().strftime("%Y-%m-%d")
        
        # 获取今日交易
        trades = await self._db.get_trades(
            start_date=f"{today}T00:00:00",
            end_date=f"{today}T23:59:59"
        )
        
        if not trades:
            self.logger.info("今日无交易")
            return
            
        # 计算统计
        stats = self._calculate_stats(trades)
        
        # 生成报告
        report = self._format_report(today, trades, stats)
        
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"📊 每日复盘报告 - {today}")
        self.logger.info(f"{'='*60}")
        self.logger.info(report)
        self.logger.info(f"{'='*60}")
        
    async def _log_stats(self):
        """记录实时统计"""
        if not self._db:
            return
            
        stats = await self._db.calculate_stats(days=7)
        
        self.logger.debug(
            f"近期统计: 交易{stats.get('total_trades', 0)}笔 "
            f"胜率{stats.get('win_rate', 0)*100:.1f}% "
            f"盈亏比{stats.get('profit_factor', 0):.2f} "
            f"最大回撤${stats.get('max_drawdown', 0):.2f}"
        )
        
    def _calculate_stats(self, trades: List[TradeRecord]) -> Dict:
        """计算统计数据"""
        if not trades:
            return {}
            
        total = len(trades)
        wins = sum(1 for t in trades if t.pnl > 0)
        losses = sum(1 for t in trades if t.pnl < 0)
        
        total_pnl = sum(t.pnl for t in trades)
        
        win_trades = [t for t in trades if t.pnl > 0]
        loss_trades = [t for t in trades if t.pnl < 0]
        
        avg_win = sum(t.pnl for t in win_trades) / len(win_trades) if win_trades else 0
        avg_loss = abs(sum(t.pnl for t in loss_trades)) / len(loss_trades) if loss_trades else 0
        
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / total if total > 0 else 0,
            "total_pnl": total_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": avg_win / avg_loss if avg_loss > 0 else 0,
        }
        
    def _format_report(self, date: str, trades: List[TradeRecord], stats: Dict) -> str:
        """格式化报告"""
        lines = []
        
        lines.append(f"交易次数: {stats.get('total_trades', 0)}")
        lines.append(f"盈利次数: {stats.get('wins', 0)}")
        lines.append(f"亏损次数: {stats.get('losses', 0)}")
        lines.append(f"胜率: {stats.get('win_rate', 0)*100:.1f}%")
        lines.append(f"总盈亏: ${stats.get('total_pnl', 0):.2f}")
        lines.append(f"平均盈利: ${stats.get('avg_win', 0):.2f}")
        lines.append(f"平均亏损: ${stats.get('avg_loss', 0):.2f}")
        lines.append(f"盈亏比: {stats.get('profit_factor', 0):.2f}")
        
        lines.append("\n交易明细:")
        for trade in trades:
            pnl_str = f"+${trade.pnl:.2f}" if trade.pnl >= 0 else f"-${abs(trade.pnl):.2f}"
            lines.append(
                f"  {trade.symbol} {trade.direction.upper()} "
                f"开${trade.entry_price:.4f} 平${trade.exit_price:.4f} "
                f"{trade.close_reason} {pnl_str}"
            )
            
        return "\n".join(lines)
        
    async def get_all_stats(self) -> Dict:
        """获取所有统计"""
        if not self._db:
            return {}
            
        return await self._db.calculate_stats(days=30)
