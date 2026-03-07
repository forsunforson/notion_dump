import datetime
import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml

from app.core.paths import project_root as _project_root, output_dir
from app.services.notion_service import NotionService


PortfolioAction = Literal["BUY", "SELL", "DIVIDEND"]
PortfolioCurrency = Literal["HKD", "CNY", "USD"]


def _to_plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    return value


def _find_and_update_stock(
    data: dict,
    ticker: str,
    action: str,
    quantity: float,
) -> tuple[bool, Any, str]:
    """
    Find and update stock position in balance_sheet_structure.

    Returns: (success, old_value, yaml_path)
    """
    try:
        asset_detail = data.get("balance_sheet_structure", {}).get("asset_detail", [])
    except (TypeError, AttributeError):
        return False, None, ""

    liquid_assets = None
    for item in asset_detail:
        if isinstance(item, dict) and item.get("name") == "liquid assets":
            liquid_assets = item
            break

    if not liquid_assets:
        return False, None, ""

    try:
        equity_list = liquid_assets.get("detail", [])
    except (TypeError, AttributeError):
        return False, None, ""

    equity_item = None
    for item in equity_list:
        if isinstance(item, dict) and item.get("name") == "equity":
            equity_item = item
            break

    if not equity_item:
        return False, None, ""

    try:
        stock_list = equity_item.get("detail", [])
    except (TypeError, AttributeError):
        return False, None, ""

    stock_item = None
    for item in stock_list:
        if isinstance(item, dict) and item.get("name") == "stock":
            stock_item = item
            break

    if not stock_item:
        return False, None, ""

    try:
        detail_list = stock_item.get("detail", [])
    except (TypeError, AttributeError):
        return False, None, ""

    found_stock = None
    for item in detail_list:
        if isinstance(item, dict) and item.get("name") == ticker:
            found_stock = item
            break

    if found_stock:
        old_count = found_stock.get("stock_count", 0) or 0

        if action == "BUY":
            new_count = old_count + quantity
            found_stock["stock_count"] = new_count
        elif action == "SELL":
            new_count = old_count - quantity
            if new_count <= 0:
                detail_list.remove(found_stock)
            else:
                found_stock["stock_count"] = new_count
        elif action == "DIVIDEND":
            pass

        yaml_path = f"balance_sheet_structure.liquid_assets.equity.stock.{ticker}"
        return True, old_count, yaml_path
    else:
        if action == "BUY":
            new_stock = {"name": ticker, "stock_count": quantity}
            detail_list.append(new_stock)
            yaml_path = f"balance_sheet_structure.liquid_assets.equity.stock.{ticker}"
            return True, 0, yaml_path

    return False, None, ""


def _write_changelog(
    yaml_path: str,
    old_value: Any,
    new_value: Any,
    reason: str,
) -> None:
    changelog_path = output_dir() / "profile_changelog.jsonl"
    changelog_path.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "yaml_path": yaml_path,
        "old_value": _to_plain(old_value),
        "new_value": _to_plain(new_value),
        "reason": reason,
        "source": "update_portfolio_skill",
    }
    with open(changelog_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def log_portfolio_transaction(
    ticker: str,
    action: str,
    price: float,
    quantity: float,
    currency: str = "HKD",
    notes: str = "",
) -> str:
    """
    When user mentions buying, selling or dividends of stocks/options, call this tool to record the transaction.

    :param ticker: Stock name or code (e.g., "心动公司", "02400", "美团", "长安B")
    :param action: Must be "BUY", "SELL" or "DIVIDEND"
    :param price: Transaction unit price
    :param quantity: Transaction quantity (number of shares)
    :param currency: Currency, defaults to HKD (Hong Kong Dollar),可选 CNY (人民币), USD (美元)
    :param notes: User's original message and emotional notes
    """
    if not ticker or not str(ticker).strip():
        return "Error: ticker is required."

    if action not in ("BUY", "SELL", "DIVIDEND"):
        return f"Error: action must be BUY, SELL or DIVIDEND, got {action}"

    if price is None or price <= 0:
        return f"Error: price must be a positive number, got {price}"

    if quantity is None or quantity <= 0:
        return f"Error: quantity must be a positive number, got {quantity}"

    currency = currency.upper()
    if currency not in ("HKD", "CNY", "USD"):
        return f"Error: currency must be HKD, CNY or USD, got {currency}"

    action = action.upper()
    ticker = str(ticker).strip()

    try:
        total_amount = round(price * quantity, 2)
    except (TypeError, ValueError) as e:
        return f"Error calculating total_amount: {str(e)}"

    notes_str = str(notes) if notes else ""

    yaml_update_note = ""
    notion_result = None

    try:
        notion = NotionService()
        notion_result = notion.append_portfolio_ledger(
            ticker=ticker,
            action=action,
            price=price,
            quantity=quantity,
            currency=currency,
            total_amount=total_amount,
            notes=notes_str,
        )
    except ValueError as e:
        if "NOTION_PORTFOLIO_LEDGER_DB_ID" in str(e):
            return f"Error: Portfolio Ledger database not configured. Please set NOTION_PORTFOLIO_LEDGER_DB_ID environment variable."
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error recording transaction: {str(e)}"

    captured_at = notion_result.get("captured_at", "") if notion_result else ""
    page_id = notion_result.get("page_id", "") if notion_result else ""
    url = notion_result.get("url", "") if notion_result else ""

    profile_updated = False
    old_value = None
    yaml_path = ""

    try:
        root = _project_root()
        profile_path = Path(os.getenv("PROFILE_YAML_PATH") or (root / "config" / "profile.yaml"))

        if profile_path.exists():
            try:
                from ruamel.yaml import YAML
                from ruamel.yaml.comments import CommentedMap

                ryaml = YAML()
                ryaml.preserve_quotes = True
                ryaml.indent(mapping=2, sequence=4, offset=2)
                with open(profile_path, "r", encoding="utf-8") as f:
                    data = ryaml.load(f)

                if isinstance(data, dict):
                    success, old_value, yaml_path = _find_and_update_stock(
                        data, ticker, action, quantity
                    )

                    if success:
                        with open(profile_path, "w", encoding="utf-8") as f:
                            ryaml.dump(data, f)

                        new_value = old_value + quantity if action == "BUY" else old_value - quantity
                        if action == "SELL":
                            new_value = old_value - quantity

                        changelog_reason = f"Telegram 自动捕获交易: {action} {int(quantity)} 股"
                        _write_changelog(yaml_path, old_value, new_value, changelog_reason)
                        profile_updated = True
            except Exception as e:
                yaml_update_note = f"(注：本地 Profile 更新失败，请检查 YAML 格式: {str(e)})"
    except Exception as e:
        yaml_update_note = f"(注：本地 Profile 更新失败，请检查 YAML 格式: {str(e)})"

    suffix = url or page_id
    base_msg = f"交易已记录：[{action}] {ticker} {int(quantity)}股 @ {price} {currency} (总额: {total_amount} {currency})，时间：{captured_at[:10]}"
    if suffix:
        base_msg += f"，Notion：{suffix}"
    if yaml_update_note:
        base_msg += f" {yaml_update_note}"

    return base_msg


LOG_PORTFOLIO_TRANSACTION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "log_portfolio_transaction",
        "description": "Record stock/options buy, sell or dividend transactions to Portfolio Ledger. Must be called when user mentions adding position, reducing position, closing position, or dividend.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock name or code (e.g., '心动公司', '02400', '美团', '长安B', '字节期权')"
                },
                "action": {
                    "type": "string",
                    "enum": ["BUY", "SELL", "DIVIDEND"],
                    "description": "Transaction type: BUY (加仓/买入), SELL (减仓/卖出/清仓), DIVIDEND (分红)"
                },
                "price": {
                    "type": "number",
                    "description": "Transaction unit price"
                },
                "quantity": {
                    "type": "number",
                    "description": "Transaction quantity (number of shares)"
                },
                "currency": {
                    "type": "string",
                    "enum": ["HKD", "CNY", "USD"],
                    "description": "Currency, defaults to HKD for Hong Kong stocks, CNY for A-shares, USD for US stocks"
                },
                "notes": {
                    "type": "string",
                    "description": "User's original message and emotional notes"
                }
            },
            "required": ["ticker", "action", "price", "quantity"]
        }
    }
}
