import os
from typing import Literal

from app.services.notion_service import NotionService


PortfolioAction = Literal["BUY", "SELL", "DIVIDEND"]
PortfolioCurrency = Literal["HKD", "CNY", "USD"]


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

    try:
        notion = NotionService()
        result = notion.append_portfolio_ledger(
            ticker=ticker,
            action=action,
            price=price,
            quantity=quantity,
            currency=currency,
            total_amount=total_amount,
            notes=notes_str,
        )
        page_id = result.get("page_id") or ""
        url = result.get("url") or ""
        captured_at = result.get("captured_at") or ""

        suffix = url or page_id
        if suffix:
            return f"交易已记录：[{action}] {ticker} {int(quantity)}股 @ {price} {currency} (总额: {total_amount} {currency})，时间：{captured_at[:10]}，Notion：{suffix}"
        return f"交易已记录：[{action}] {ticker} {int(quantity)}股 @ {price} {currency} (总额: {total_amount} {currency})，时间：{captured_at[:10]}"
    except ValueError as e:
        if "NOTION_PORTFOLIO_LEDGER_DB_ID" in str(e):
            return f"Error: Portfolio Ledger database not configured. Please set NOTION_PORTFOLIO_LEDGER_DB_ID environment variable."
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error recording transaction: {str(e)}"


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
