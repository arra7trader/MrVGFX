"""
Extended test script for MT5 market depth with multiple retries
"""
import MetaTrader5 as mt5
import time

print("=" * 60)
print("MT5 MARKET DEPTH EXTENDED TEST")
print("=" * 60)

print("\nInitializing MT5...")
if not mt5.initialize():
    print(f"Failed: {mt5.last_error()}")
    exit()

info = mt5.terminal_info()
account = mt5.account_info()
print(f"Terminal: {info.name}")
print(f"Account: {account.login}")
print(f"Account Type: {account.server}")
print(f"Trade Mode: {account.trade_mode}")  # 0=demo, 1=contest, 2=real

# Test multiple symbols
symbols = ["XAUUSD", "EURUSD", "GBPUSD"]

for symbol in symbols:
    print(f"\n{'='*60}")
    print(f"Testing: {symbol}")
    print("="*60)
    
    # Check symbol info
    sym_info = mt5.symbol_info(symbol)
    if sym_info is None:
        print(f"Symbol {symbol} not found!")
        continue
    
    print(f"Symbol visible: {sym_info.visible}")
    print(f"Symbol spread: {sym_info.spread}")
    print(f"Book depth: {sym_info.book_depth if hasattr(sym_info, 'book_depth') else 'N/A'}")
    
    # Make sure symbol is in market watch
    if not sym_info.visible:
        mt5.symbol_select(symbol, True)
        print("Added to market watch")
        time.sleep(0.5)
    
    # Subscribe
    print(f"\nSubscribing...")
    result = mt5.market_book_add(symbol)
    print(f"Subscribe result: {result}")
    
    if not result:
        error = mt5.last_error()
        print(f"Error code: {error}")
        continue
    
    # Try multiple times with delay
    print("\nPolling for depth data...")
    for i in range(5):
        time.sleep(1)
        book = mt5.market_book_get(symbol)
        
        if book is None:
            print(f"  Attempt {i+1}: None (error: {mt5.last_error()})")
        elif len(book) == 0:
            print(f"  Attempt {i+1}: Empty list")
        else:
            print(f"  Attempt {i+1}: SUCCESS! Got {len(book)} entries")
            for entry in book[:3]:
                book_type = "BID" if entry.type == 2 else "ASK"
                print(f"    {book_type}: {entry.price} x {entry.volume}")
            break
    
    # Release
    mt5.market_book_release(symbol)

# Also test copy_ticks as alternative
print(f"\n{'='*60}")
print("ALTERNATIVE: Testing copy_ticks_from for real-time prices")
print("="*60)

from datetime import datetime
ticks = mt5.copy_ticks_from("XAUUSD", datetime.now(), 10, mt5.COPY_TICKS_ALL)
if ticks is not None and len(ticks) > 0:
    print(f"Got {len(ticks)} recent ticks")
    print(f"Latest: Bid={ticks[-1]['bid']}, Ask={ticks[-1]['ask']}, Time={ticks[-1]['time']}")
else:
    print("No tick data")

mt5.shutdown()
print("\nDone!")
