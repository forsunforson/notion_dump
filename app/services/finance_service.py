import os
import logging
from decimal import Decimal, InvalidOperation
from typing import Any
import datetime
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except Exception:
    yf = None


def _to_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, Decimal):
        return v
    try:
        if isinstance(v, (int, float)):
            return Decimal(str(v))
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            return Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    return None


class FinanceService:
    def __init__(self, *, data_source: str | None = None):
        self.data_source = (data_source or os.getenv("FINANCE_DATA_SOURCE") or "yfinance").strip().lower()

    def is_available(self) -> bool:
        if (os.getenv("CHRONOFOLD_DISABLE_YFINANCE") or "").strip() == "1":
            return False
        if self.data_source == "yfinance":
            return yf is not None
        return False

    def last_close_prices(
        self,
        tickers: list[str],
        *,
        period: str = "10d",
        interval: str = "1d",
    ) -> dict[str, Decimal]:
        if not tickers or not self.is_available():
            return {}
        if self.data_source != "yfinance":
            return {}

        try:
            df = yf.download(
                tickers=tickers,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False,
            )
        except Exception:
            logger.exception("yfinance download failed for tickers=%s", tickers)
            return {}

        if df is None or getattr(df, "empty", True):
            logger.warning("yfinance returned empty data for tickers=%s", tickers)
            return {}

        prices: dict[str, Decimal] = {}
        nlevels = getattr(getattr(df, "columns", None), "nlevels", 1)

        def _last_close_one(d: Any) -> Decimal | None:
            try:
                close = d["Close"]
                close = close.dropna()
                if getattr(close, "empty", True):
                    return None
                return _to_decimal(close.iloc[-1])
            except Exception:
                return None

        if len(tickers) == 1 and nlevels == 1:
            p = _last_close_one(df)
            if p is not None:
                prices[tickers[0]] = p
            return prices

        for t in tickers:
            try:
                sub = df[t]
            except Exception:
                continue
            p = _last_close_one(sub)
            if p is not None:
                prices[t] = p

        return prices

    def daily_pct_change(
        self,
        symbol: str,
        *,
        period: str = "10d",
        interval: str = "1d",
    ) -> float | None:
        if not symbol.strip() or not self.is_available():
            return None
        if self.data_source != "yfinance":
            return None

        try:
            df = yf.download(
                symbol.strip(),
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False,
            )
        except Exception as e:
            logger.warning("Failed to fetch %s via yfinance: %s", symbol, str(e))
            return None

        close = self._extract_close_series(df, symbol.strip())
        if close is None:
            return None
        try:
            close = close.dropna()
            if len(close) < 2:
                return None
            last = float(close.iloc[-1])
            prev = float(close.iloc[-2])
            if prev <= 0:
                return None
            return (last / prev) - 1.0
        except Exception as e:
            logger.warning("Failed to parse %s history: %s", symbol, str(e))
            return None

    def pct_change_vs_prev_close(
        self,
        symbol: str,
        *,
        tz_name: str = "Asia/Hong_Kong",
    ) -> float | None:
        if not symbol.strip() or not self.is_available():
            return None
        if self.data_source != "yfinance":
            return None

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("Asia/Hong_Kong")

        sym = symbol.strip()
        try:
            obj = yf.Ticker(sym)
        except Exception:
            return None

        last = self._realtime_last_price_float(obj)
        prev = self._prev_trading_close_float(obj, tz)

        if last is None or last <= 0 or prev is None or prev <= 0:
            return None

        return (last / prev) - 1.0

    def hstech_beta_line(self, date_local, *, symbol: str = "3067.HK") -> str | None:
        pct = self.daily_pct_change(symbol, period="10d", interval="1d")
        if pct is None:
            return None

        if pct >= 0.02:
            tag = "大涨"
        elif pct <= -0.02:
            tag = "大跌"
        else:
            tag = "平盘"

        return f"大盘水位 (Beta)： 3067.HK (恒生科技 ETF) 当日表现 {tag} ({pct:+.2%})"

    def last_price(self, ticker: str) -> Decimal | None:
        t = (ticker or "").strip()
        if not t or not self.is_available():
            return None
        if self.data_source != "yfinance":
            return None

        try:
            obj = yf.Ticker(t)
            fi = getattr(obj, "fast_info", None)
            if fi:
                p = fi.get("last_price")
                if p is None:
                    p = fi.get("regular_market_price")
                if p is None:
                    p = fi.get("previous_close")
                d = _to_decimal(p)
                if d is not None:
                    return d

            h = obj.history(period="1d", interval="1m")
            if h is not None and not getattr(h, "empty", True):
                s = h.get("Close")
                if s is not None:
                    s = s.dropna()
                    if not getattr(s, "empty", True):
                        d = _to_decimal(s.iloc[-1])
                        if d is not None:
                            return d

            h = obj.history(period="10d", interval="1d")
            if h is not None and not getattr(h, "empty", True):
                s = h.get("Close")
                if s is not None:
                    s = s.dropna()
                    if not getattr(s, "empty", True):
                        d = _to_decimal(s.iloc[-1])
                        if d is not None:
                            return d
        except Exception:
            return None
        return None

    @staticmethod
    def _realtime_last_price_float(obj: Any) -> float | None:
        try:
            h = obj.history(period="1d", interval="1m")
            if h is None or getattr(h, "empty", True):
                return None
            s = h.get("Close")
            if s is None:
                return None
            s = s.dropna()
            if getattr(s, "empty", True):
                return None
            v = float(s.iloc[-1])
            return v if v > 0 else None
        except Exception:
            return None

    @staticmethod
    def _prev_trading_close_float(obj: Any, tz: ZoneInfo) -> float | None:
        try:
            today = datetime.datetime.now(tz).date()
            h = obj.history(period="14d", interval="1d")
            if h is None or getattr(h, "empty", True):
                return None
            s = h.get("Close")
            if s is None:
                return None
            s = s.dropna()
            if getattr(s, "empty", True):
                return None

            items: list[tuple[datetime.date, float]] = []
            for idx, v in s.items():
                d = None
                try:
                    if getattr(idx, "tzinfo", None) is not None:
                        d = idx.tz_convert(tz).date()
                    else:
                        d = idx.date()
                except Exception:
                    try:
                        d = datetime.date.fromisoformat(str(idx)[:10])
                    except Exception:
                        d = None
                if d is None:
                    continue
                try:
                    fv = float(v)
                except Exception:
                    continue
                if fv > 0:
                    items.append((d, fv))

            items.sort(key=lambda x: x[0])
            prev_items = [x for x in items if x[0] < today]
            if not prev_items:
                return None
            return prev_items[-1][1]
        except Exception:
            return None

    def _extract_close_series(self, df: Any, symbol: str) -> Any | None:
        try:
            if df is None or (hasattr(df, "empty") and df.empty):
                return None
            cols = getattr(df, "columns", None)
            if cols is not None and hasattr(cols, "names") and cols.names and len(cols.names) > 1:
                try:
                    if symbol in getattr(cols, "get_level_values")(0):
                        return df[symbol]["Close"]
                    if symbol in getattr(cols, "get_level_values")(-1):
                        return df[("Close", symbol)]
                except Exception:
                    pass
            if "Close" in df:
                return df["Close"]
            return None
        except Exception:
            return None
