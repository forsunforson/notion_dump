import datetime
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import yaml

from app.core.paths import config_dir, output_dir
from app.utils.jsonl_kv_store import upsert_jsonl
from app.utils.timezone_utils import load_profile_timezone

try:
    import yfinance as yf
except ImportError:
    yf = None


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StockPosition:
    name: str
    ticker: str
    currency: str
    count: Decimal


def _now_utc_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _to_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        return None
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


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class PortfolioSyncJob:
    def __init__(self, *, profile_path: Path | None = None, metrics_path: Path | None = None):
        self.profile_path = profile_path or (config_dir() / "profile.yaml")
        self.metrics_path = metrics_path or (output_dir() / "metrics.jsonl")
        self.tz = load_profile_timezone(self.profile_path)

    def run(self) -> int:
        if yf is None:
            logger.error("yfinance is not installed; cannot run portfolio_sync_job")
            return 2

        local_date = datetime.datetime.now(self.tz).date().isoformat()
        timestamp_utc = _now_utc_iso()

        try:
            profile = self._load_profile(self.profile_path)
        except Exception:
            logger.exception("Failed to load profile.yaml: %s", self.profile_path)
            return 1

        positions = self._extract_stock_positions(profile)
        if not positions:
            logger.warning("No stock positions found in profile.yaml (or missing ticker/currency)")

        tickers = sorted({p.ticker for p in positions})
        fx_tickers = sorted({self._fx_ticker(p.currency) for p in positions if self._needs_fx(p.currency)})
        all_tickers = tickers + fx_tickers

        prices = self._fetch_last_close_prices(all_tickers) if all_tickers else {}

        equity_details: list[dict[str, Any]] = []
        total_cny = Decimal("0")

        for p in positions:
            price = prices.get(p.ticker)
            if price is None:
                logger.warning("Missing market close price for %s (%s); skipping", p.name, p.ticker)
                continue

            fx_rate = Decimal("1")
            if self._needs_fx(p.currency):
                fx_t = self._fx_ticker(p.currency)
                fx_price = prices.get(fx_t)
                if fx_price is None:
                    logger.warning("Missing FX close price for %s (%s); skipping", p.currency, fx_t)
                    continue
                fx_rate = fx_price

            value_cny = price * p.count * fx_rate
            total_cny += value_cny

            equity_details.append(
                {
                    "name": p.name,
                    "ticker": p.ticker,
                    "price": float(price),
                    "count": int(p.count) if p.count == p.count.to_integral_value() else float(p.count),
                    "currency": p.currency,
                    "value_cny": float(_q2(value_cny)),
                }
            )

        record = {
            "date": local_date,
            "source": "portfolio_sync_job",
            "total_equity_value_cny": float(_q2(total_cny)),
            "equity_details": equity_details,
            "timestamp": timestamp_utc,
        }

        try:
            upsert_jsonl(self.metrics_path, record, key_fn=self._metrics_key)
        except Exception:
            logger.exception("Failed to upsert metrics.jsonl: %s", self.metrics_path)
            return 1

        logger.info(
            "Portfolio synced: date=%s positions=%d priced=%d total_cny=%s metrics_path=%s",
            local_date,
            len(positions),
            len(equity_details),
            record["total_equity_value_cny"],
            str(self.metrics_path),
        )
        return 0

    def _load_profile(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(str(path))
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError("profile.yaml must be a mapping")
        return data

    def _extract_stock_positions(self, profile: dict[str, Any]) -> list[StockPosition]:
        bss = profile.get("balance_sheet_structure")
        stock_items: list[dict[str, Any]] = []
        for detail_list in self._find_stock_detail_lists(bss):
            stock_items.extend([x for x in detail_list if isinstance(x, dict)])

        positions: list[StockPosition] = []
        for item in stock_items:
            name = (item.get("name") or "").strip() if isinstance(item.get("name"), str) else ""
            ticker = (item.get("ticker") or "").strip() if isinstance(item.get("ticker"), str) else ""
            currency = (item.get("currency") or "").strip().upper() if isinstance(item.get("currency"), str) else ""
            count = _to_decimal(item.get("stock_count"))

            if not name:
                logger.warning("Stock item missing name; skipping: %s", item)
                continue
            if not ticker or not currency or count is None:
                logger.warning("Stock item missing ticker/currency/stock_count; skipping: %s", item)
                continue
            if count <= 0:
                logger.warning("Stock item has non-positive stock_count; skipping: %s", item)
                continue

            positions.append(StockPosition(name=name, ticker=ticker, currency=currency, count=count))

        return positions

    def _find_stock_detail_lists(self, node: Any) -> list[list[Any]]:
        out: list[list[Any]] = []
        if isinstance(node, dict):
            if node.get("name") == "stock" and isinstance(node.get("detail"), list):
                out.append(node["detail"])
            for v in node.values():
                out.extend(self._find_stock_detail_lists(v))
        elif isinstance(node, list):
            for v in node:
                out.extend(self._find_stock_detail_lists(v))
        return out

    def _fetch_last_close_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        if not tickers:
            return {}

        try:
            df = yf.download(
                tickers=tickers,
                period="10d",
                interval="1d",
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

        def _last_close_one(d) -> Decimal | None:
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

    def _needs_fx(self, currency: str) -> bool:
        c = (currency or "").strip().upper()
        return c not in {"CNY", "RMB", "CNH"}

    def _fx_ticker(self, currency: str) -> str:
        c = (currency or "").strip().upper()
        return f"{c}CNY=X"

    def _metrics_key(self, item: dict) -> str | None:
        source = item.get("source")
        date = item.get("date")
        if not isinstance(source, str) or not source.strip():
            return None
        if not isinstance(date, str) or not date.strip():
            return None
        return f"{source.strip()}::{date.strip()}"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return PortfolioSyncJob().run()


if __name__ == "__main__":
    raise SystemExit(main())
