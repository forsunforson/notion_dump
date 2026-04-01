import datetime
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
 
import yaml
 
from app.core.paths import config_dir, output_dir
from app.services.finance_service import FinanceService
from app.services.event_store import write_metrics_event
from app.utils.timezone_utils import load_profile_timezone
 
logger = logging.getLogger(__name__)
 
 
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
 
 
def _norm_currency(v: Any) -> str:
    if isinstance(v, str) and v.strip():
        c = v.strip().upper()
        if c in {"RMB", "CNY", "CNH"}:
            return "CNY"
        return c
    return "CNY"
 
 
def _needs_fx(currency: str) -> bool:
    return _norm_currency(currency) != "CNY"
 
 
def _fx_ticker(currency: str) -> str:
    return f"{_norm_currency(currency)}CNY=X"
 
 
def _safe_name(node: Any) -> str:
    if isinstance(node, dict) and isinstance(node.get("name"), str):
        return node["name"].strip()
    return ""
 
 
def _find_first_named_node(node: Any, *, target_name: str) -> dict[str, Any] | None:
    if isinstance(node, dict):
        if isinstance(node.get("name"), str) and node["name"].strip().lower() == target_name.lower():
            return node
        for v in node.values():
            found = _find_first_named_node(v, target_name=target_name)
            if found is not None:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _find_first_named_node(v, target_name=target_name)
            if found is not None:
                return found
    return None
 
 
def collect_market_inputs(node: Any) -> tuple[set[str], set[str]]:
    tickers: set[str] = set()
    currencies: set[str] = set()
 
    def _walk(n: Any) -> None:
        if isinstance(n, list):
            for x in n:
                _walk(x)
            return
        if not isinstance(n, dict):
            return
 
        detail = n.get("detail")
        if isinstance(detail, list):
            for x in detail:
                _walk(x)
            return
 
        ticker = n.get("ticker")
        stock_count = _to_decimal(n.get("stock_count"))
        if isinstance(ticker, str) and ticker.strip() and stock_count is not None and stock_count > 0:
            tickers.add(ticker.strip())
            currencies.add(_norm_currency(n.get("currency")))
            return
 
        option_count = _to_decimal(n.get("option_count"))
        price = _to_decimal(n.get("price"))
        if option_count is not None and option_count > 0 and price is not None and price >= 0:
            currencies.add(_norm_currency(n.get("currency")))
            return
 
    _walk(node)
    return tickers, currencies
 
 
def calculate_node_value(
    node: Any,
    *,
    live_prices: dict[str, Decimal],
    fx_rates: dict[str, Decimal],
) -> Decimal:
    if isinstance(node, list):
        total = Decimal("0")
        for child in node:
            total += calculate_node_value(child, live_prices=live_prices, fx_rates=fx_rates)
        return total
 
    if not isinstance(node, dict):
        return Decimal("0")
 
    detail = node.get("detail")
    if isinstance(detail, list):
        total = Decimal("0")
        for child in detail:
            total += calculate_node_value(child, live_prices=live_prices, fx_rates=fx_rates)
        return total
 
    ticker = node.get("ticker")
    stock_count = _to_decimal(node.get("stock_count"))
    if isinstance(ticker, str) and ticker.strip() and stock_count is not None and stock_count > 0:
        t = ticker.strip()
        price = live_prices.get(t)
        if price is None:
            logger.warning("Missing market price for ticker=%s node=%s", t, _safe_name(node) or t)
            return Decimal("0")
        currency = _norm_currency(node.get("currency"))
        if _needs_fx(currency) and currency not in fx_rates:
            logger.warning("Missing FX rate for currency=%s (ticker=%s)", currency, _fx_ticker(currency))
            return Decimal("0")
        fx = fx_rates.get(currency, Decimal("1"))
        return price * stock_count * fx
 
    option_count = _to_decimal(node.get("option_count"))
    price = _to_decimal(node.get("price"))
    if option_count is not None and option_count > 0 and price is not None and price >= 0:
        currency = _norm_currency(node.get("currency"))
        if _needs_fx(currency) and currency not in fx_rates:
            logger.warning("Missing FX rate for currency=%s (ticker=%s)", currency, _fx_ticker(currency))
            return Decimal("0")
        fx = fx_rates.get(currency, Decimal("1"))
        return price * option_count * fx
 
    v = _to_decimal(node.get("value"))
    return v if v is not None else Decimal("0")
 
 
class NetWorthSyncJob:
    def __init__(self, *, profile_path: Path | None = None, metrics_path: Path | None = None):
        self.profile_path = profile_path or (config_dir() / "profile.yaml")
        self.metrics_path = metrics_path or (output_dir() / "metrics.jsonl")
        self.tz = load_profile_timezone(self.profile_path)
 
    def run(self) -> int:
        finance = FinanceService()
        if not finance.is_available():
            logger.error("finance_service unavailable; cannot run net_worth_sync_job")
            return 2
 
        local_date = datetime.datetime.now(self.tz).date().isoformat()
        timestamp_utc = _now_utc_iso()
 
        try:
            profile = self._load_profile(self.profile_path)
        except Exception:
            logger.exception("Failed to load profile.yaml: %s", self.profile_path)
            return 1
 
        bss = profile.get("balance_sheet_structure")
        if not isinstance(bss, dict):
            logger.warning("profile.yaml missing balance_sheet_structure mapping; writing zeros")
            bss = {}
 
        asset_detail = bss.get("asset_detail")
        liability_detail = bss.get("liability_detail")
 
        tickers_a, currencies_a = collect_market_inputs(asset_detail)
        tickers_l, currencies_l = collect_market_inputs(liability_detail)
        tickers = sorted(tickers_a | tickers_l)
        currencies = {c for c in (currencies_a | currencies_l) if _needs_fx(c)}
        fx_tickers = sorted({_fx_ticker(c) for c in currencies})
 
        prices = finance.last_close_prices(tickers + fx_tickers) if (tickers or fx_tickers) else {}
 
        live_prices: dict[str, Decimal] = {}
        for t in tickers:
            p = prices.get(t)
            if p is None:
                logger.warning("No price data for ticker=%s", t)
            else:
                live_prices[t] = p
 
        fx_rates: dict[str, Decimal] = {"CNY": Decimal("1")}
        for c in currencies:
            t = _fx_ticker(c)
            p = prices.get(t)
            if p is None:
                logger.warning("No FX data for currency=%s (ticker=%s)", c, t)
                continue
            fx_rates[c] = p
 
        total_assets = calculate_node_value(asset_detail, live_prices=live_prices, fx_rates=fx_rates)
        total_liabilities = calculate_node_value(liability_detail, live_prices=live_prices, fx_rates=fx_rates)
        net_worth = total_assets - total_liabilities
 
        liquid_assets_cny = Decimal("0")
        liquid_node = _find_first_named_node(asset_detail, target_name="liquid assets")
        if liquid_node is not None:
            liquid_assets_cny = calculate_node_value(liquid_node, live_prices=live_prices, fx_rates=fx_rates)
 
        record = {
            "date": local_date,
            "source": "net_worth_sync_job",
            "net_worth_cny": float(_q2(net_worth)),
            "total_assets_cny": float(_q2(total_assets)),
            "total_liabilities_cny": float(_q2(total_liabilities)),
            "liquid_assets_cny": float(_q2(liquid_assets_cny)),
            "timestamp": timestamp_utc,
        }
 
        try:
            write_metrics_event(self.metrics_path, record)
        except Exception:
            logger.exception("Failed to append metrics.jsonl: %s", self.metrics_path)
            return 1
 
        logger.info(
            "Net worth synced: date=%s tickers=%d total_assets=%s total_liabilities=%s net_worth=%s metrics_path=%s",
            local_date,
            len(tickers),
            record["total_assets_cny"],
            record["total_liabilities_cny"],
            record["net_worth_cny"],
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
 
def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return NetWorthSyncJob().run()
 
 
if __name__ == "__main__":
    raise SystemExit(main())
