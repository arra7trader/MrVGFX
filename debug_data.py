import MetaTrader5 as mt5
import time

TARGET_SYMBOLS = ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "XAUUSD", "EURUSD"]

def main():
    print("Initializing MT5...")
    if not mt5.initialize(path=r"C:\Program Files\FBS MetaTrader 5\terminal64.exe"):
        print(f"Failed to initialize MT5, error code: {mt5.last_error()}")
        return

    print("MT5 Initialized.")
    print(f"Terminal Info: {mt5.terminal_info()}")
    print(f"Version: {mt5.version()}")

    for symbol in TARGET_SYMBOLS:
        print(f"\n--- Checking {symbol} ---")
        
        # 1. Check if symbol exists
        info = mt5.symbol_info(symbol)
        if info is None:
            print(f" [X] Symbol {symbol} not found in MT5")
            # Try to find similar
            all_symbols = mt5.symbols_get()
            similar = [s.name for s in all_symbols if symbol in s.name]
            if similar:
                print(f"   Did you mean: {similar}?")
            continue
        else:
            print(f" [OK] Symbol found. Visible: {info.visible}, Select: {info.select}")

        # 2. Select and Subscribe
        if not info.visible:
            print(f"   Symbol not visible, attempting to select...")
            if not mt5.symbol_select(symbol, True):
                print(f"   [X] Failed to select {symbol}")
            else:
                print(f"   [OK] Selected {symbol}")
        
        # 3. Market Book Add (Aggressive)
        print("   Subscribing to Market Book...")
        mt5.market_book_add(symbol)
        
        # 4. Fetch Tick
        print("   Fetching tick data...")
        for _ in range(5):
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                print("   [!] Tick is None")
            else:
                print(f"   tick.bid: {tick.bid}, tick.ask: {tick.ask}, time: {tick.time}")
                if tick.bid != 0 and tick.ask != 0:
                    print("   [OK] Valid Data Received!")
                    break
            time.sleep(0.5)

    mt5.shutdown()

if __name__ == "__main__":
    main()
