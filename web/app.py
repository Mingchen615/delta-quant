"""
Delta Quant v9.0 - Web管理界面
FastAPI应用，提供交易监控、扫码接入、一键操作
"""

import asyncio
import concurrent.futures
import time
import hashlib
import secrets
from pathlib import Path
from typing import Optional

from loguru import logger

try:
    from fastapi import FastAPI, Request, Depends
    from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from config import WEB_HOST, WEB_PORT, LIVE_TRADE, set_live_trade, toggle_live_trade, MASTER_PASSWORD

STATIC_DIR = Path(__file__).parent / "static"

# 价格缓存
_price_cache = {}
_price_cache_time = 0

# 主事件循环引用（在main.py中设置，用于跨线程调用ccxt）
_main_loop: asyncio.AbstractEventLoop = None


def set_main_loop(loop: asyncio.AbstractEventLoop):
    """设置主事件循环引用（由main.py在启动时调用）"""
    global _main_loop
    _main_loop = loop


async def _safe_get_ticker(ex, symbol: str):
    """安全获取ticker，通过主事件循环执行ccxt调用"""
    if not _main_loop:
        return None
    try:
        future = asyncio.run_coroutine_threadsafe(
            ex.get_ticker(symbol), _main_loop
        )
        return await asyncio.wrap_future(future)
    except Exception:
        # 符号格式不匹配时尝试转换
        alt = symbol.replace("/USDT:USDT", "/USDT") if ":USDT" in symbol else symbol.replace("/USDT", "/USDT:USDT")
        if alt != symbol:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    ex.get_ticker(alt), _main_loop
                )
                return await asyncio.wrap_future(future)
            except Exception:
                pass
        return None

# 认证token存储 (token -> expiry_timestamp)
_auth_tokens = {}
_TOKEN_EXPIRE = 86400  # 24小时

security = HTTPBearer(auto_error=False)


def _create_token() -> str:
    token = secrets.token_urlsafe(32)
    _auth_tokens[token] = time.time() + _TOKEN_EXPIRE
    return token


def _verify_token(token: str) -> bool:
    if not MASTER_PASSWORD:
        return True  # 未设置密码，跳过验证
    expiry = _auth_tokens.get(token)
    if expiry and time.time() < expiry:
        return True
    # 清理过期token
    _auth_tokens.pop(token, None)
    return False


def _check_auth(request: Request) -> bool:
    """检查请求是否已认证"""
    if not MASTER_PASSWORD:
        return True
    # 从header或cookie获取token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return _verify_token(auth[7:])
    return False


def create_app(
    router=None,
    credential_manager=None,
    qr_auth_manager=None,
    paper_engine=None,
    agents: dict = None,
    event_collector=None,
):
    """创建FastAPI应用"""
    if not HAS_FASTAPI:
        logger.error("[Web] FastAPI未安装，Web界面不可用")
        return None

    app = FastAPI(
        title="Delta Quant v9.0",
        description="双平台量化交易系统管理界面",
        version="9.0.0",
    )

    app.state.router = router
    app.state.credential_manager = credential_manager
    app.state.qr_auth_manager = qr_auth_manager
    app.state.paper_engine = paper_engine
    app.state.agents = agents or {}
    app.state.event_collector = event_collector

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # --- 页面路由 ---

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if _check_auth(request):
            return RedirectResponse("/paper")
        return RedirectResponse("/login")

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return _render_page("login.html")

    @app.get("/paper", response_class=HTMLResponse)
    async def paper_page(request: Request):
        return _render_page("paper.html")

    @app.get("/live", response_class=HTMLResponse)
    async def live_page(request: Request):
        return _render_page("live.html")

    @app.get("/connect", response_class=HTMLResponse)
    async def connect_page(request: Request):
        return _render_page("connect.html")

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page(request: Request):
        return RedirectResponse("/paper")

    # --- 认证API ---

    @app.post("/api/login")
    async def api_login(request: Request):
        body = await request.json()
        password = body.get("password", "")
        if not MASTER_PASSWORD:
            # 未设置密码，直接放行
            token = _create_token()
            return {"success": True, "token": token}
        if password == MASTER_PASSWORD:
            token = _create_token()
            return {"success": True, "token": token}
        return {"success": False, "error": "密码错误"}

    # --- API路由 ---

    @app.get("/api/status")
    async def api_status():
        """系统状态"""
        agent_status = {}
        if agents:
            for name, agent in agents.items():
                agent_status[name] = {
                    "name": agent.name,
                    "state": agent.state.value,
                    "last_execution": (
                        agent._last_execution.isoformat()
                        if agent._last_execution else None
                    ),
                    "error_count": agent._error_count,
                }

        exchange_status = {}
        if router:
            for name, ex in router.exchanges.items():
                exchange_status[name] = {
                    "connected": ex.is_connected,
                    "name": ex.exchange_name,
                }

        return {
            "version": "9.0.0",
            "agents": agent_status,
            "exchanges": exchange_status,
        }

    @app.get("/api/balance")
    async def api_balance():
        """账户余额"""
        if not router:
            return {"error": "路由器未初始化"}
        if _main_loop:
            future = asyncio.run_coroutine_threadsafe(
                router.get_all_balances(), _main_loop
            )
            balances = await asyncio.wrap_future(future)
        else:
            balances = await router.get_all_balances()
        return {
            name: {
                "total": b.total,
                "free": b.free,
                "used": b.used,
                "unrealized_pnl": b.unrealized_pnl,
            }
            for name, b in balances.items()
        }

    @app.get("/api/positions")
    async def api_positions(request: Request):
        """当前持仓（支持 ?mode=paper 或 ?mode=live 过滤）"""
        mode = request.query_params.get("mode", "")
        result = {}

        # 真实交易所持仓
        if router and mode != "paper":
            if _main_loop:
                future = asyncio.run_coroutine_threadsafe(
                    router.get_all_positions(), _main_loop
                )
                positions = await asyncio.wrap_future(future)
            else:
                positions = await router.get_all_positions()
            for exchange_name, pos_list in positions.items():
                result[exchange_name] = [
                    {
                        "symbol": p.symbol,
                        "side": p.side,
                        "contracts": p.contracts,
                        "entry_price": p.entry_price,
                        "mark_price": p.mark_price,
                        "unrealized_pnl": p.unrealized_pnl,
                        "leverage": p.leverage,
                    }
                    for p in pos_list
                ]

        # 模拟盘持仓
        if paper_engine and mode != "live":
            paper_positions = paper_engine.get_positions()
            if paper_positions:
                paper_list = []
                for sym, pos in paper_positions.items():
                    # 尝试获取当前价格计算未实现盈亏
                    mark_price = pos.entry_price
                    unrealized_pnl = 0.0
                    if router:
                        for ex in router.exchanges.values():
                            if not ex.is_connected:
                                continue
                            ticker = await _safe_get_ticker(ex, sym)
                            if ticker:
                                mark_price = ticker.last
                                unrealized_pnl = paper_engine.get_unrealized_pnl(sym, mark_price)
                                break
                    paper_list.append({
                        "symbol": pos.symbol,
                        "side": pos.direction,
                        "contracts": pos.quantity,
                        "entry_price": pos.entry_price,
                        "mark_price": mark_price,
                        "unrealized_pnl": unrealized_pnl,
                        "leverage": pos.leverage,
                    })
                result["paper"] = paper_list

        return result

    @app.get("/api/tickers")
    async def api_tickers():
        """实时价格行情"""
        global _price_cache, _price_cache_time
        if time.time() - _price_cache_time < 3:
            return _price_cache

        symbols = [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
            "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT",
        ]
        result = {}
        if router:
            for name, ex in router.exchanges.items():
                if not ex.is_connected:
                    continue
                # OKX使用合约符号格式
                is_okx = name == "okx"
                for sym in symbols:
                    fetch_sym = sym if not is_okx else sym.replace("/USDT", "/USDT:USDT")
                    ticker = await _safe_get_ticker(ex, fetch_sym)
                    if ticker:
                        result[sym] = {
                            "price": ticker.last,
                            "change": 0,
                            "volume": ticker.quote_volume,
                        }
                break  # 只从一个交易所获取价格
        _price_cache = result
        _price_cache_time = time.time()
        return result

    @app.get("/api/signals")
    async def api_signals():
        """Agent信号"""
        signals = []
        if agents:
            for name, agent in agents.items():
                if hasattr(agent, '_last_signal'):
                    sig = agent._last_signal
                    if sig:
                        signals.append({
                            "agent": name,
                            "symbol": getattr(sig, 'symbol', ''),
                            "direction": getattr(sig, 'direction', ''),
                            "strength": getattr(sig, 'strength', 0),
                            "time": getattr(sig, 'timestamp', ''),
                        })
        return signals

    @app.get("/api/risk")
    async def api_risk():
        """风控指标"""
        risk_info = {
            "daily_pnl": 0,
            "daily_pnl_pct": 0,
            "max_drawdown": 0,
            "open_positions": 0,
            "total_exposure": 0,
        }
        if router:
            try:
                positions = await router.get_all_positions()
                total_pnl = 0
                pos_count = 0
                for pos_list in positions.values():
                    for p in pos_list:
                        total_pnl += p.unrealized_pnl
                        pos_count += 1
                risk_info["daily_pnl"] = total_pnl
                risk_info["open_positions"] = pos_count
            except Exception:
                pass

        if agents and 'risk' in agents:
            agent = agents['risk']
            if hasattr(agent, '_daily_pnl'):
                risk_info["daily_pnl"] = agent._daily_pnl
            if hasattr(agent, '_daily_pnl_pct'):
                risk_info["daily_pnl_pct"] = agent._daily_pnl_pct

        return risk_info

    @app.get("/api/mode")
    async def api_get_mode():
        """获取当前交易模式"""
        return {
            "mode": "live" if LIVE_TRADE else "paper",
            "live_trade": LIVE_TRADE,
        }

    @app.post("/api/mode")
    async def api_set_mode(request: Request):
        """切换交易模式"""
        body = await request.json()
        mode = body.get("mode", "")

        if mode == "live":
            set_live_trade(True)
        elif mode == "paper":
            set_live_trade(False)
        elif mode == "toggle":
            toggle_live_trade()
        else:
            return {"error": f"无效模式: {mode}，支持 live/paper/toggle"}

        return {
            "mode": "live" if LIVE_TRADE else "paper",
            "live_trade": LIVE_TRADE,
            "message": f"已切换到{'实盘' if LIVE_TRADE else '模拟盘'}模式",
        }

    @app.get("/api/agent-activity")
    async def api_agent_activity():
        """Agent活动日志"""
        if not event_collector:
            return []
        return event_collector.get_agent_activity(limit=30)

    @app.get("/api/order-history")
    async def api_order_history():
        """订单历史"""
        orders = []
        if paper_engine:
            stats = paper_engine.get_stats()
            orders.append({
                "type": "paper_stats",
                "balance": stats["balance"],
                "total_pnl": stats["total_pnl"],
                "win_rate": stats.get("win_rate", 0),
                "total_trades": stats["total_trades"],
            })
        if event_collector:
            raw = event_collector.get_events(topic="order_filled", limit=20)
            for e in raw:
                d = e.get("data", {})
                orders.append({
                    "time": e["time"],
                    "symbol": d.get("symbol", ""),
                    "side": d.get("side", ""),
                    "quantity": d.get("filled_quantity", 0),
                    "price": d.get("avg_fill_price", 0),
                    "status": d.get("status", ""),
                    "order_id": d.get("order_id", ""),
                })
        return orders

    @app.get("/api/paper-stats")
    async def api_paper_stats():
        """模拟盘统计"""
        if not paper_engine:
            return {"error": "模拟盘未初始化"}
        return paper_engine.get_stats()

    @app.post("/api/trade")
    async def api_trade(request: Request):
        """手动下单"""
        from exchange.base_exchange import OrderParams
        body = await request.json()

        if not router:
            return {"error": "路由器未初始化"}

        try:
            params = OrderParams(
                symbol=body["symbol"],
                side=body["side"],
                order_type=body.get("order_type", "market"),
                amount=float(body["amount"]),
                price=float(body["price"]) if body.get("price") else None,
                leverage=int(body.get("leverage", 20)),
                margin_mode=body.get("margin_mode", "cross"),
                exchange=body.get("exchange", "auto"),
            )
            if _main_loop:
                future = asyncio.run_coroutine_threadsafe(
                    router.route_order(params), _main_loop
                )
                order = await asyncio.wrap_future(future)
            else:
                order = await router.route_order(params)
            return {
                "success": True,
                "order_id": order.order_id,
                "exchange": order.exchange,
                "symbol": order.symbol,
                "side": order.side,
                "amount": order.amount,
                "price": order.average,
                "status": order.status,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/api/emergency-close")
    async def api_emergency_close():
        """紧急全平"""
        if not router:
            return {"error": "路由器未初始化"}
        if _main_loop:
            future = asyncio.run_coroutine_threadsafe(
                router.close_all_positions(), _main_loop
            )
            results = await asyncio.wrap_future(future)
        else:
            results = await router.close_all_positions()
        return {"results": results}

    @app.get("/api/connect/qr/{exchange_name}")
    async def api_qr_code(exchange_name: str):
        """获取扫码QR Code"""
        if not qr_auth_manager:
            return {"error": "扫码管理器未初始化"}
        qr_base64 = qr_auth_manager.generate_qr_base64(exchange_name)
        return {
            "exchange": exchange_name,
            "qr_base64": qr_base64,
            "url": qr_auth_manager.get_instructions(exchange_name),
        }

    @app.post("/api/connect/verify")
    async def api_verify_connect(request: Request):
        """验证并接入交易所"""
        body = await request.json()
        exchange_name = body.get("exchange")
        api_key = body.get("api_key", "")
        api_secret = body.get("api_secret", "")
        passphrase = body.get("passphrase", "")

        if not router:
            return {"error": "路由器未初始化"}

        if exchange_name not in router.exchanges:
            if exchange_name == "binance":
                from exchange.binance_exchange import BinanceExchange
                exchange = BinanceExchange()
                router.register("binance", exchange)
            elif exchange_name == "okx":
                from exchange.okx_exchange import OKXExchange
                exchange = OKXExchange()
                router.register("okx", exchange)
            else:
                return {"error": f"不支持的交易所: {exchange_name}"}
        else:
            exchange = router.exchanges[exchange_name]

        if qr_auth_manager:
            if _main_loop:
                future = asyncio.run_coroutine_threadsafe(
                    qr_auth_manager.connect_exchange(exchange, api_key, api_secret, passphrase),
                    _main_loop,
                )
                success, message = await asyncio.wrap_future(future)
            else:
                success, message = await qr_auth_manager.connect_exchange(
                    exchange, api_key, api_secret, passphrase
                )
            return {"success": success, "exchange": exchange_name, "message": message}
        return {"error": "扫码管理器未初始化"}

    @app.get("/api/credentials/status")
    async def api_credential_status():
        """凭证状态"""
        if not credential_manager:
            return {"error": "凭证管理器未初始化"}
        return {
            "binance": credential_manager.has_credentials("binance"),
            "okx": credential_manager.has_credentials("okx"),
        }

    def _render_page(filename: str) -> HTMLResponse:
        """渲染HTML页面"""
        filepath = STATIC_DIR / filename
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            return HTMLResponse(content)
        return HTMLResponse(f"<h1>页面不存在: {filename}</h1>", status_code=404)

    return app


def run_web_server(app, host: str = WEB_HOST, port: int = WEB_PORT):
    """启动Web服务器"""
    import uvicorn
    logger.info(f"[Web] 启动Web服务器: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
