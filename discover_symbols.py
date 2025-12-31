
import MetaTrader5 as mt5
import time

def discover_symbols():
    if not mt5.initialize():
        print(f"Initialize failed: {mt5.last_error()}")
        return

    print(f"Connected to: {mt5.terminal_info().name}")
    print("Searching for Crypto symbols...")

    # Search pattern 1: Standard names
    patterns = ["*BTC*", "*ETH*", "*BNB*", "*XRP*", "*SOL*"]
    
    found_count = 0
    for pattern in patterns:
        symbols = mt5.symbols_get(group=pattern)
        if symbols:
            print(f"\nFound match for '{pattern}':")
            for s in symbols:
                print(f"  - {s.name} (Path: {s.path})")
                found_count += 1
        else:
            print(f"No match for '{pattern}'")

    if found_count == 0:
        print("\nChecking all symbols manually for 'USD'...")
        all_symbols = mt5.symbols_get()
        if all_symbols:
            for s in all_symbols:
                if "BTC" in s.name or "ETH" in s.name:
                    print(f"  - {s.name}")

    mt5.shutdown()

if __name__ == "__main__":
    discover_symbols()
