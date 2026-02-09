class PricingService:
    def __init__(self, market_conditions):
        self.market_conditions = market_conditions

    def calculate_pricing(self, base_price, demand_factor):
        # Validate against market conditions
        if not self.validate_market_conditions():
            raise ValueError("Market conditions not suitable for pricing")

        # Calculate exact pricing
        price = base_price * demand_factor
        return price

    def validate_market_conditions(self):
        # Simplistic check against market conditions
        return self.market_conditions.get("is_stable", False)

# Example usage:
# market_conditions = {"is_stable": True}
# service = PricingService(market_conditions)
# price = service.calculate_pricing(100, 1.2)
# print(price)  # Output should be the calculated price