import datetime
import os
from pathlib import Path
from typing import Any, Literal

from app.core.paths import project_root as _project_root, output_dir
from app.utils.jsonl_event_store import append_jsonl_record
from app.utils.plain import to_plain


PortfolioAction = Literal["BUY", "SELL", "DIVIDEND"]
PortfolioCurrency = Literal["HKD", "CNY", "USD"]


def _find_item_by_name(items: Any, name: str) -> tuple[dict | None, int]:
    if not isinstance(items, list):
        return None, -1
    for i, item in enumerate(items):
        if isinstance(item, dict) and item.get("name") == name:
            return item, i
    return None, -1


def _ensure_named_child(parent: dict, list_key: str, name: str) -> dict:
    items = parent.get(list_key)
    if not isinstance(items, list):
        items = []
        parent[list_key] = items
    found, _ = _find_item_by_name(items, name)
    if found is not None:
        return found
    new_node: dict = {"name": name}
    items.append(new_node)
    return new_node


def _coerce_number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _find_stock_holding(items: Any, ticker: str) -> tuple[dict | None, int]:
    if not isinstance(items, list):
        return None, -1
    ticker_str = str(ticker).strip()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        item_ticker = str(item.get("ticker") or "").strip()
        if name == ticker_str or item_ticker == ticker_str:
            return item, i
    return None, -1


def _update_balance_sheet(
    data: dict,
    ticker: str,
    action: str,
    quantity: float,
    cash_impact: float,
) -> dict:
    """
    Atomic double-entry bookkeeping update in-place:
    - BUY: cash -= cash_impact, stock_count += quantity
    - SELL: cash += cash_impact, stock_count -= quantity (remove holding if <= 0)
    - DIVIDEND: cash += cash_impact (stock_count unchanged)
    """
    changes: dict[str, Any] = {
        "stock_changed": False,
        "old_stock": None,
        "new_stock": None,
        "stock_yaml_path": f"balance_sheet_structure.asset_detail[liquid assets].equity.stock[{ticker}].stock_count",
        "cash_changed": False,
        "old_cash": None,
        "new_cash": None,
        "cash_yaml_path": "balance_sheet_structure.asset_detail[liquid assets].checking account.value",
        "errors": [],
    }

    try:
        cash_impact = float(cash_impact)
    except (TypeError, ValueError):
        changes["errors"].append("cash_impact is missing or not a number")
        return changes

    balance_sheet = data.get("balance_sheet_structure")
    if not isinstance(balance_sheet, dict):
        changes["errors"].append("balance_sheet_structure is missing or not a mapping")
        return changes

    asset_detail = balance_sheet.get("asset_detail")
    if not isinstance(asset_detail, list):
        changes["errors"].append("balance_sheet_structure.asset_detail is missing or not a list")
        return changes

    liquid_assets = _ensure_named_child(balance_sheet, "asset_detail", "liquid assets")
    liquid_detail = liquid_assets.get("detail")
    if not isinstance(liquid_detail, list):
        liquid_detail = []
        liquid_assets["detail"] = liquid_detail

    checking_account, _ = _find_item_by_name(liquid_detail, "checking account")
    if checking_account is None:
        checking_account = {"name": "checking account", "value": 0.0}
        liquid_detail.append(checking_account)

    old_cash = _coerce_number(checking_account.get("value"), default=0.0)
    changes["old_cash"] = old_cash

    if action == "BUY":
        new_cash = old_cash - cash_impact
    elif action in ("SELL", "DIVIDEND"):
        new_cash = old_cash + cash_impact
    else:
        changes["errors"].append(f"unsupported action: {action}")
        return changes

    checking_account["value"] = new_cash
    changes["cash_changed"] = True
    changes["new_cash"] = new_cash

    if action == "DIVIDEND":
        return changes

    equity = _ensure_named_child(liquid_assets, "detail", "equity")
    equity_detail = equity.get("detail")
    if not isinstance(equity_detail, list):
        equity_detail = []
        equity["detail"] = equity_detail

    stock_container = _ensure_named_child(equity, "detail", "stock")
    holdings = stock_container.get("detail")
    if not isinstance(holdings, list):
        holdings = []
        stock_container["detail"] = holdings

    holding, idx = _find_stock_holding(holdings, ticker)
    if holding is None:
        if action == "SELL":
            changes["errors"].append(f"holding not found for SELL: {ticker}")
            checking_account["value"] = old_cash
            changes["cash_changed"] = False
            changes["new_cash"] = None
            return changes
        holding = {"name": ticker, "stock_count": 0}
        holdings.append(holding)

    old_stock = _coerce_number(holding.get("stock_count"), default=0.0)
    changes["old_stock"] = old_stock

    if action == "BUY":
        new_stock = old_stock + quantity
        holding["stock_count"] = new_stock
        changes["stock_changed"] = True
        changes["new_stock"] = new_stock
        return changes

    if action == "SELL":
        new_stock = old_stock - quantity
        if new_stock <= 0:
            try:
                holdings.pop(idx)
            except Exception:
                try:
                    holdings.remove(holding)
                except ValueError:
                    pass
            changes["stock_changed"] = True
            changes["new_stock"] = 0.0
            return changes

        holding["stock_count"] = new_stock
        changes["stock_changed"] = True
        changes["new_stock"] = new_stock
        return changes

    return changes


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
        "old_value": to_plain(old_value),
        "new_value": to_plain(new_value),
        "reason": reason,
        "source": "update_portfolio_skill",
    }
    append_jsonl_record(
        changelog_path,
        event,
        required_fields=("timestamp", "yaml_path", "reason", "source"),
        drop_null=False,
    )


def log_portfolio_transaction(
    ticker: str,
    action: str,
    price: float,
    quantity: float,
    cash_impact: float,
    currency: str = "HKD",
    notes: str = "",
) -> str:
    """
    When user mentions buying, selling or dividends of stocks/options, call this tool to record the transaction.

    :param ticker: Stock name or code (e.g., "心动公司", "02400", "美团", "长安B")
    :param action: Must be "BUY", "SELL" or "DIVIDEND"
    :param price: Transaction unit price
    :param quantity: Transaction quantity (number of shares)
    :param cash_impact: Absolute cash amount impacting checking account in base currency (usually CNY)
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

    try:
        cash_impact = float(cash_impact)
    except (TypeError, ValueError):
        return f"Error: cash_impact must be a number, got {cash_impact}"

    if cash_impact <= 0:
        return f"Error: cash_impact must be a positive number, got {cash_impact}"

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
    notion = None

    try:
        from app.services.notion_service import NotionService

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

    changes: dict[str, Any] | None = None

    try:
        root = _project_root()
        profile_path = Path(os.getenv("PROFILE_YAML_PATH") or (root / "config" / "profile.yaml"))

        if profile_path.exists():
            try:
                from ruamel.yaml import YAML

                ryaml = YAML()
                ryaml.preserve_quotes = True
                ryaml.indent(mapping=2, sequence=4, offset=2)
                with open(profile_path, "r", encoding="utf-8") as f:
                    data = ryaml.load(f)

                if isinstance(data, dict):
                    changes = _update_balance_sheet(
                        data=data,
                        ticker=ticker,
                        action=action,
                        quantity=quantity,
                        cash_impact=cash_impact,
                    )

                    if changes and not changes.get("errors"):
                        with open(profile_path, "w", encoding="utf-8") as f:
                            ryaml.dump(data, f)

                        changelog_reason = f"Telegram 自动捕获交易: {action} {int(quantity)} 股"

                        if changes.get("stock_changed"):
                            _write_changelog(
                                str(changes.get("stock_yaml_path") or ""),
                                changes.get("old_stock"),
                                changes.get("new_stock"),
                                changelog_reason,
                            )
                        if changes.get("cash_changed"):
                            _write_changelog(
                                str(changes.get("cash_yaml_path") or ""),
                                changes.get("old_cash"),
                                changes.get("new_cash"),
                                changelog_reason,
                            )
                    elif changes and changes.get("errors"):
                        yaml_update_note = f"(注：本地 Profile 更新失败: {'; '.join(changes.get('errors') or [])})"
            except Exception as e:
                yaml_update_note = f"(注：本地 Profile 更新失败，请检查 YAML 格式: {str(e)})"
    except Exception as e:
        yaml_update_note = f"(注：本地 Profile 更新失败，请检查 YAML 格式: {str(e)})"

    trade_snapshot_note = ""
    try:
        if notion and page_id:
            notion.append_trade_snapshot_log_to_page(
                page_id=page_id,
                ticker=ticker,
                action=action,
                price=price,
                quantity=quantity,
                cash_impact=cash_impact,
                currency=currency,
                total_amount=total_amount,
                notes=notes_str,
                changes=changes,
                captured_at=captured_at,
            )
    except Exception as e:
        trade_snapshot_note = f"(注：交易快照模板写入失败: {str(e)})"

    suffix = url or page_id
    base_msg = f"交易已记录：[{action}] {ticker} {int(quantity)}股 @ {price} {currency} (总额: {total_amount} {currency})，时间：{captured_at[:10]}"
    if suffix:
        base_msg += f"，Notion：{suffix}"
    if yaml_update_note:
        base_msg += f" {yaml_update_note}"
    if trade_snapshot_note:
        base_msg += f" {trade_snapshot_note}"

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
                "cash_impact": {
                    "type": "number",
                    "description": "The actual absolute amount of cash (in base currency, usually CNY) deducted from or added to the checking account, including all fees and FX conversions. The LLM must calculate or extract this from the user's prompt."
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
            "required": ["ticker", "action", "price", "quantity", "cash_impact"]
        }
    }
}
