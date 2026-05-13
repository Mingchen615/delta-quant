"""
数据库存储模块
使用aiosqlite进行异步数据存储
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import aiosqlite
from loguru import logger


@dataclass
class TradeRecord:
    """交易记录"""
    id: Optional[int] = None
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0
    exit_price: float = 0
    quantity: float = 0
    leverage: int = 20
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    pnl: float = 0
    pnl_pct: float = 0
    commission: float = 0
    stop_loss: float = 0
    take_profit: float = 0
    close_reason: str = ""
    signal_score: float = 0
    debate_confidence: float = 0
    notes: str = ""


@dataclass
class DailyStats:
    """每日统计"""
    date: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0
    win_rate: float = 0
    avg_win: float = 0
    avg_loss: float = 0
    profit_factor: float = 0
    max_drawdown: float = 0
    sharpe: float = 0


class Database:
    """
    数据库管理
    存储交易记录、统计数据
    """
    
    def __init__(self, db_path: str = "data/delta_quant.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        
    async def connect(self):
        """连接数据库"""
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._create_tables()
        logger.info(f"[数据库] 已连接到 {self.db_path}")
        
    async def close(self):
        """关闭连接"""
        if self._conn:
            await self._conn.close()
            logger.info("[数据库] 连接已关闭")
            
    async def _create_tables(self):
        """创建表"""
        async with self._conn.executescript("""
            -- 交易记录表
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL DEFAULT 0,
                quantity REAL NOT NULL,
                leverage INTEGER DEFAULT 20,
                entry_time TEXT,
                exit_time TEXT,
                pnl REAL DEFAULT 0,
                pnl_pct REAL DEFAULT 0,
                commission REAL DEFAULT 0,
                stop_loss REAL DEFAULT 0,
                take_profit REAL DEFAULT 0,
                close_reason TEXT DEFAULT '',
                signal_score REAL DEFAULT 0,
                debate_confidence REAL DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- 每日统计表
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                total_pnl REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                avg_win REAL DEFAULT 0,
                avg_loss REAL DEFAULT 0,
                profit_factor REAL DEFAULT 0,
                max_drawdown REAL DEFAULT 0,
                sharpe REAL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- 信号记录表
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                score REAL NOT NULL,
                confidence REAL DEFAULT 0,
                factors TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- 鲸鱼活动记录表
            CREATE TABLE IF NOT EXISTS whale_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                quote_quantity REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- 创建索引
            CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);
            CREATE INDEX IF NOT EXISTS idx_trades_exit_time ON trades(exit_time);
            CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
            CREATE INDEX IF NOT EXISTS idx_whale_symbol ON whale_activity(symbol);
        """):
            await self._conn.commit()
            
    async def save_trade(self, trade: TradeRecord) -> int:
        """保存交易记录"""
        async with self._lock:
            cursor = await self._conn.execute("""
                INSERT INTO trades (
                    symbol, direction, entry_price, exit_price, quantity, leverage,
                    entry_time, exit_time, pnl, pnl_pct, commission, stop_loss, take_profit,
                    close_reason, signal_score, debate_confidence, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.symbol, trade.direction, trade.entry_price, trade.exit_price,
                trade.quantity, trade.leverage,
                trade.entry_time.isoformat() if trade.entry_time else None,
                trade.exit_time.isoformat() if trade.exit_time else None,
                trade.pnl, trade.pnl_pct, trade.commission, trade.stop_loss, trade.take_profit,
                trade.close_reason, trade.signal_score, trade.debate_confidence, trade.notes
            ))
            await self._conn.commit()
            return cursor.lastrowid
            
    async def update_trade(self, trade: TradeRecord):
        """更新交易记录"""
        async with self._lock:
            await self._conn.execute("""
                UPDATE trades SET
                    exit_price = ?, exit_time = ?, pnl = ?, pnl_pct = ?,
                    commission = ?, close_reason = ?, notes = ?
                WHERE id = ?
            """, (
                trade.exit_price,
                trade.exit_time.isoformat() if trade.exit_time else None,
                trade.pnl, trade.pnl_pct,
                trade.commission, trade.close_reason, trade.notes,
                trade.id
            ))
            await self._conn.commit()
            
    async def get_trades(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> List[TradeRecord]:
        """获取交易记录"""
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if start_date:
            query += " AND entry_time >= ?"
            params.append(start_date)
        if end_date:
            query += " AND entry_time <= ?"
            params.append(end_date)
            
        query += " ORDER BY entry_time DESC LIMIT ?"
        params.append(limit)
        
        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            
        trades = []
        for row in rows:
            trades.append(TradeRecord(
                id=row["id"],
                symbol=row["symbol"],
                direction=row["direction"],
                entry_price=row["entry_price"],
                exit_price=row["exit_price"],
                quantity=row["quantity"],
                leverage=row["leverage"],
                entry_time=datetime.fromisoformat(row["entry_time"]) if row["entry_time"] else None,
                exit_time=datetime.fromisoformat(row["exit_time"]) if row["exit_time"] else None,
                pnl=row["pnl"],
                pnl_pct=row["pnl_pct"],
                commission=row["commission"],
                stop_loss=row["stop_loss"],
                take_profit=row["take_profit"],
                close_reason=row["close_reason"],
                signal_score=row["signal_score"],
                debate_confidence=row["debate_confidence"],
                notes=row["notes"],
            ))
        return trades
        
    async def save_signal(
        self,
        symbol: str,
        direction: str,
        score: float,
        confidence: float = 0,
        factors: Optional[Dict] = None
    ):
        """保存信号记录"""
        async with self._lock:
            await self._conn.execute("""
                INSERT INTO signals (symbol, direction, score, confidence, factors)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, direction, score, confidence, json.dumps(factors or {})))
            await self._conn.commit()
            
    async def save_whale_activity(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        price: float,
        quote_quantity: float
    ):
        """保存鲸鱼活动"""
        async with self._lock:
            await self._conn.execute("""
                INSERT INTO whale_activity (symbol, direction, quantity, price, quote_quantity)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, direction, quantity, price, quote_quantity))
            await self._conn.commit()
            
    async def calculate_stats(self, days: int = 30) -> Dict[str, Any]:
        """计算统计数据"""
        start_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        # 获取所有平仓交易
        async with self._conn.execute("""
            SELECT * FROM trades 
            WHERE exit_time IS NOT NULL AND exit_time >= ?
            ORDER BY exit_time
        """, (start_date,)) as cursor:
            rows = await cursor.fetchall()
            
        if not rows:
            return {"trades": 0}
            
        trades = [dict(row) for row in rows]
        
        # 计算统计
        total_trades = len(trades)
        wins = sum(1 for t in trades if t["pnl"] > 0)
        losses = sum(1 for t in trades if t["pnl"] < 0)
        total_pnl = sum(t["pnl"] for t in trades)
        
        win_trades = [t for t in trades if t["pnl"] > 0]
        loss_trades = [t for t in trades if t["pnl"] < 0]
        
        avg_win = sum(t["pnl"] for t in win_trades) / len(win_trades) if win_trades else 0
        avg_loss = abs(sum(t["pnl"] for t in loss_trades)) / len(loss_trades) if loss_trades else 0
        
        total_wins = sum(t["pnl"] for t in win_trades)
        total_losses = abs(sum(t["pnl"] for t in loss_trades))
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # 计算最大回撤
        cumulative = 0
        max_drawdown = 0
        peak = 0
        for t in trades:
            cumulative += t["pnl"]
            if cumulative > peak:
                peak = cumulative
            drawdown = peak - cumulative
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                
        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / total_trades if total_trades > 0 else 0,
            "total_pnl": total_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "avg_r": total_pnl / total_trades if total_trades > 0 else 0,
        }
