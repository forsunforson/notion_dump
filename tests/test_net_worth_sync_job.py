import unittest
from decimal import Decimal
 
from app.jobs.net_worth_sync_job import calculate_node_value, collect_market_inputs
 
 
class TestNetWorthSyncJob(unittest.TestCase):
    def test_parent_ignores_own_value_when_detail_present(self):
        node = {
            "name": "liquid assets",
            "value": "999",
            "detail": [
                {"name": "checking account", "value": 200000},
                {
                    "name": "stock holding",
                    "ticker": "2400.HK",
                    "currency": "HKD",
                    "stock_count": 10,
                },
            ],
        }
        live_prices = {"2400.HK": Decimal("20")}
        fx_rates = {"CNY": Decimal("1"), "HKD": Decimal("0.9")}
        v = calculate_node_value(node, live_prices=live_prices, fx_rates=fx_rates)
        self.assertEqual(v, Decimal("200180.0"))
 
    def test_stock_valuation_uses_price_count_fx(self):
        node = {
            "name": "some stock",
            "ticker": "3690.HK",
            "currency": "HKD",
            "stock_count": "9300",
        }
        live_prices = {"3690.HK": Decimal("100")}
        fx_rates = {"CNY": Decimal("1"), "HKD": Decimal("0.92")}
        v = calculate_node_value(node, live_prices=live_prices, fx_rates=fx_rates)
        self.assertEqual(v, Decimal("855600.0"))
 
    def test_option_valuation_uses_static_price_count_fx(self):
        node = {"name": "byte option", "price": 200, "currency": "USD", "option_count": 771}
        live_prices = {}
        fx_rates = {"CNY": Decimal("1"), "USD": Decimal("7.2")}
        v = calculate_node_value(node, live_prices=live_prices, fx_rates=fx_rates)
        self.assertEqual(v, Decimal("1110240.0"))
 
    def test_static_leaf_parses_string_value(self):
        node = {"name": "car", "value": "40000"}
        v = calculate_node_value(node, live_prices={}, fx_rates={"CNY": Decimal("1")})
        self.assertEqual(v, Decimal("40000"))
 
    def test_missing_market_price_returns_zero(self):
        node = {"name": "some stock", "ticker": "NOPE", "currency": "USD", "stock_count": 1}
        v = calculate_node_value(node, live_prices={}, fx_rates={"CNY": Decimal("1"), "USD": Decimal("7.2")})
        self.assertEqual(v, Decimal("0"))
 
    def test_collect_market_inputs_finds_tickers_and_currencies(self):
        asset_detail = [
            {"name": "checking", "value": 1},
            {
                "name": "equity",
                "detail": [
                    {"name": "stock", "detail": [{"name": "A", "ticker": "2400.HK", "currency": "HKD", "stock_count": 1}]},
                    {"name": "option", "detail": [{"name": "B", "price": 2, "currency": "USD", "option_count": 3}]},
                ],
            },
        ]
        tickers, currencies = collect_market_inputs(asset_detail)
        self.assertEqual(tickers, {"2400.HK"})
        self.assertEqual(currencies, {"HKD", "USD"})
 
 
if __name__ == "__main__":
    unittest.main()
