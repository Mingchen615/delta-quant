"""Exchange模块 - 延迟加载"""


def __getattr__(name):
    if name == "BinanceClient":
        from .binance_client import BinanceClient
        return BinanceClient
    elif name == "binance_client":
        from .binance_client import binance_client
        return binance_client
    elif name == "PaperTradeEngine":
        from .paper_trade import PaperTradeEngine
        return PaperTradeEngine
    elif name == "BaseExchange":
        from .base_exchange import BaseExchange
        return BaseExchange
    elif name == "BinanceExchange":
        from .binance_exchange import BinanceExchange
        return BinanceExchange
    elif name == "OKXExchange":
        from .okx_exchange import OKXExchange
        return OKXExchange
    elif name == "ExchangeRouter":
        from .exchange_router import ExchangeRouter
        return ExchangeRouter
    elif name == "CredentialManager":
        from .credentials import CredentialManager
        return CredentialManager
    elif name == "QRAuthManager":
        from .qr_auth import QRAuthManager
        return QRAuthManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "BinanceClient", "binance_client", "PaperTradeEngine",
    "BaseExchange", "BinanceExchange", "OKXExchange",
    "ExchangeRouter", "CredentialManager", "QRAuthManager",
]
