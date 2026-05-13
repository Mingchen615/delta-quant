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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["BinanceClient", "binance_client", "PaperTradeEngine"]
