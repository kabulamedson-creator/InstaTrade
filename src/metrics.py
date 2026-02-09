from prometheus_client import Counter, Histogram, Gauge, start_http_server
import time

# Define Prometheus metrics
TRANSACTION_COUNTER = Counter('transactions_total', 'Total number of transactions processed')
SETTLEMENT_SPEED_TIMER = Histogram('settlement_speed_seconds', 'Time taken for settlement in seconds')
ACTIVE_SETTLEMENTS_GAUGE = Gauge('active_settlements', 'Current number of active settlements')
REQUEST_LATENCY_HISTOGRAM = Histogram('request_latency_seconds', 'Request latency in seconds')

def process_transaction(transaction_data):
    """Simulate transaction processing."""
    TRANSACTION_COUNTER.inc()  # Increment the transaction counter
    start_time = time.time()
    
    # Simulate processing settlement
    simulate_settlement(transaction_data)
    
    # timers settlement speed
    elapsed_time = time.time() - start_time
    SETTLEMENT_SPEED_TIMER.observe(elapsed_time)  # Observe the time taken for settlement

def simulate_settlement(transaction_data):
    """Simulate settlement process with random active settlements."""
    # Update the active settlements gauge
    active_settlements = len(transaction_data)  # Example: number of settlements being processed
    ACTIVE_SETTLEMENTS_GAUGE.set(active_settlements)

    # Simulate a delay for settlement processing
    time.sleep(0.1)  # Simulate processing delay

# Dummy function to simulate requests
def handle_request(request_data):
    start_time = time.time()
    process_transaction(request_data)
    latency = time.time() - start_time
    REQUEST_LATENCY_HISTOGRAM.observe(latency)  # Record request latency

if __name__ == "__main__":
    # Start Prometheus metrics server
    start_http_server(8000)
    
    # Example loop to simulate incoming requests
    while True:
        request_data = [1, 2, 3]  # Example transaction data
        handle_request(request_data)