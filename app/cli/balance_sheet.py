import argparse
import datetime
import json
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import yaml

from app.core.paths import config_dir
from app.services.finance_service import FinanceService

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


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v.strip()
    return json.dumps(v, ensure_ascii=False)


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


def _find_stock_detail_lists(node: Any) -> list[list[Any]]:
    out: list[list[Any]] = []
    if isinstance(node, dict):
        if node.get("name") == "stock" and isinstance(node.get("detail"), list):
            out.append(node["detail"])
        for v in node.values():
            out.extend(_find_stock_detail_lists(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_find_stock_detail_lists(v))
    return out


def _extract_stock_positions(balance_sheet_structure: Any) -> tuple[list[StockPosition], list[str]]:
    stock_items: list[dict[str, Any]] = []
    for detail_list in _find_stock_detail_lists(balance_sheet_structure):
        for x in detail_list:
            if isinstance(x, dict):
                stock_items.append(x)

    positions: list[StockPosition] = []
    skipped_names: list[str] = []
    for item in stock_items:
        name = _fmt_value(item.get("name"))
        ticker = _fmt_value(item.get("ticker"))
        currency = _fmt_value(item.get("currency")).upper()
        count = _to_decimal(item.get("stock_count"))

        if name:
            if not ticker or not currency or count is None or count <= 0:
                skipped_names.append(name)
                continue
        else:
            continue

        positions.append(StockPosition(name=name, ticker=ticker, currency=currency, count=count))

    return positions, skipped_names


def _needs_fx(currency: str) -> bool:
    c = (currency or "").strip().upper()
    return c not in {"CNY", "RMB", "CNH"}


def _fx_ticker(currency: str) -> str:
    c = (currency or "").strip().upper()
    return f"{c}CNY=X"


def _last_price(finance: FinanceService, ticker: str) -> Decimal | None:
    return finance.last_price(ticker)


def _print_balance_sheet(balance_sheet_structure: dict[str, Any]) -> None:
    def _print_node(node: Any, indent: str = "") -> None:
        if isinstance(node, dict):
            name = _fmt_value(node.get("name"))
            value = _fmt_value(node.get("value"))
            if name:
                if value:
                    print(f"{indent}- {name}: {value}")
                else:
                    print(f"{indent}- {name}")
            else:
                print(f"{indent}- (unnamed)")

            if name == "stock" and isinstance(node.get("detail"), list):
                for s in node["detail"]:
                    if not isinstance(s, dict):
                        continue
                    n = _fmt_value(s.get("name"))
                    ticker = _fmt_value(s.get("ticker"))
                    currency = _fmt_value(s.get("currency"))
                    count = _fmt_value(s.get("stock_count"))
                    extra: list[str] = []
                    if ticker:
                        extra.append(f"ticker={ticker}")
                    if currency:
                        extra.append(f"currency={currency}")
                    if count:
                        extra.append(f"count={count}")
                    suffix = f" ({', '.join(extra)})" if extra else ""
                    print(f"{indent}  - {n}{suffix}")
                return

            detail = node.get("detail")
            if isinstance(detail, list):
                for child in detail:
                    _print_node(child, indent + "  ")
        elif isinstance(node, list):
            for child in node:
                _print_node(child, indent)

    asset = balance_sheet_structure.get("asset_detail")
    liab = balance_sheet_structure.get("liability_detail")

    print("Assets")
    print("------------------------------------------")
    _print_node(asset, "")
    print("")
    print("Liabilities")
    print("------------------------------------------")
    _print_node(liab, "")


def _print_portfolio_realtime(balance_sheet_structure: dict[str, Any]) -> int:
    positions, skipped_names = _extract_stock_positions(balance_sheet_structure)

    print("")
    print("Portfolio (Realtime) - Valuation in CNY")
    print("------------------------------------------")

    if not positions:
        if skipped_names:
            print("skipped: missing ticker/currency/stock_count in profile.yaml")
            print("positions:", ", ".join([str(x) for x in skipped_names if x]))
        else:
            print("skipped: no stock positions found in profile.yaml")
        return 0

    finance = FinanceService()
    if not finance.is_available():
        print("finance_service unavailable in current python environment")
        return 2

    fx_needed = sorted({_fx_ticker(p.currency) for p in positions if _needs_fx(p.currency)})
    fx_rates: dict[str, Decimal] = {}
    for fx in fx_needed:
        r = _last_price(finance, fx)
        if r is not None:
            fx_rates[fx] = r

    rows: list[dict[str, Any]] = []
    total_cny = Decimal("0")

    for p in positions:
        price = _last_price(finance, p.ticker)
        if price is None:
            rows.append(
                {
                    "name": p.name,
                    "ticker": p.ticker,
                    "currency": p.currency,
                    "count": p.count,
                    "error": "price_unavailable",
                }
            )
            continue

        fx = Decimal("1")
        if _needs_fx(p.currency):
            fx_t = _fx_ticker(p.currency)
            fx = fx_rates.get(fx_t) or Decimal("0")
            if fx <= 0:
                rows.append(
                    {
                        "name": p.name,
                        "ticker": p.ticker,
                        "currency": p.currency,
                        "count": p.count,
                        "price": price,
                        "error": f"fx_unavailable({fx_t})",
                    }
                )
                continue

        value_cny = price * p.count * fx
        total_cny += value_cny

        rows.append(
            {
                "name": p.name,
                "ticker": p.ticker,
                "currency": p.currency,
                "count": p.count,
                "price": price,
                "fx_to_cny": fx,
                "value_cny": value_cny,
            }
        )

    ts = _now_utc_iso()
    print(f"as_of_utc: {ts}")
    print(f"total_equity_value_cny: {_q2(total_cny)}")
    print("")

    headers = ["name", "ticker", "currency", "count", "price", "fx_to_cny", "value_cny", "status"]
    print(" | ".join(headers))
    print("-" * 100)
    for r in rows:
        status = "ok" if not r.get("error") else str(r.get("error"))
        count = r.get("count")
        price = r.get("price")
        fx = r.get("fx_to_cny")
        vc = r.get("value_cny")
        parts = [
            str(r.get("name", "")),
            str(r.get("ticker", "")),
            str(r.get("currency", "")),
            str(count) if isinstance(count, Decimal) else "",
            str(price) if isinstance(price, Decimal) else "",
            str(fx) if isinstance(fx, Decimal) else "",
            str(_q2(vc)) if isinstance(vc, Decimal) else "",
            status,
        ]
        print(" | ".join(parts))

    return 0


def _load_profile(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("profile.yaml must be a mapping")
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="chronofold-balance-sheet")
    p.add_argument("--profile-path", type=str, default=str(config_dir() / "profile.yaml"))
    p.add_argument("--realtime", action="store_true")
    p.add_argument("--no-realtime", action="store_true")
    args = p.parse_args(argv)

    profile_path = Path(args.profile_path).expanduser()
    if not profile_path.exists():
        print(f"❌ profile.yaml not found: {profile_path}")
        return 1

    try:
        profile = _load_profile(profile_path)
    except Exception:
        print(f"❌ failed to read profile.yaml: {profile_path}")
        return 1

    bss = profile.get("balance_sheet_structure")
    if not isinstance(bss, dict):
        print("❌ balance_sheet_structure not found in profile.yaml")
        return 1

    _print_balance_sheet(bss)

    do_realtime = True
    if args.no_realtime:
        do_realtime = False
    if args.realtime:
        do_realtime = True

    if do_realtime:
        rc = _print_portfolio_realtime(bss)
        return rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
