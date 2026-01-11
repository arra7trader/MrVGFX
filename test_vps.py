"""
MT5 Connection Test for VPS
Jalankan dengan: python test_vps.py
"""
import sys
print("="*50)
print("MT5 VPS DIAGNOSTIC TOOL")
print("="*50)
print()

# Step 1: Check Python version
print(f"[1] Python Version: {sys.version}")
print()

# Step 2: Check imports
print("[2] Testing imports...")
try:
    import MetaTrader5 as mt5
    print("    MetaTrader5: OK")
except ImportError as e:
    print(f"    MetaTrader5: FAILED - {e}")
    input("Press Enter to exit...")
    sys.exit(1)

try:
    import websockets
    print("    websockets: OK")
except ImportError as e:
    print(f"    websockets: FAILED - {e}")

try:
    import numpy
    print("    numpy: OK")
except ImportError as e:
    print(f"    numpy: FAILED - {e}")

print()

# Step 3: Initialize MT5
print("[3] Testing MT5 connection...")
print("    Attempting mt5.initialize()...")

result = mt5.initialize()
print(f"    Result: {result}")

if not result:
    error = mt5.last_error()
    print(f"    ERROR CODE: {error}")
    print()
    print("="*50)
    print("DIAGNOSIS:")
    print("="*50)
    if error[0] == -1:
        print("  MT5 Terminal tidak ditemukan atau tidak berjalan.")
        print()
        print("  SOLUSI:")
        print("  1. Buka MetaTrader 5 SEBELUM menjalankan script")
        print("  2. Login ke akun (Demo/Real)")
        print("  3. Tunggu sampai chart loaded")
        print("  4. Jalankan script ini lagi")
    elif error[0] == -10003:
        print("  IPC connection failed - Terminal belum siap.")
        print()
        print("  SOLUSI:")
        print("  1. Tutup semua MT5")
        print("  2. Buka MT5 dan login")
        print("  3. Tunggu 30 detik")
        print("  4. Jalankan script ini lagi")
    else:
        print(f"  Unknown error. Screenshot dan kirim ke developer.")
    print("="*50)
else:
    print("    MT5 Connected!")
    info = mt5.terminal_info()
    print(f"    Terminal: {info.name if info else 'Unknown'}")
    print(f"    Company: {info.company if info else 'Unknown'}")
    print(f"    Path: {info.path if info else 'Unknown'}")
    
    account = mt5.account_info()
    if account:
        print(f"    Account: {account.login}")
        print(f"    Server: {account.server}")
    
    symbols = mt5.symbols_get()
    print(f"    Symbols available: {len(symbols) if symbols else 0}")
    
    mt5.shutdown()
    print()
    print("="*50)
    print("SUCCESS! MT5 connection OK.")
    print("Anda bisa menjalankan START_VPS.bat sekarang.")
    print("="*50)

print()
input("Press Enter to exit...")
