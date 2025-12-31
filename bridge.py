"""
MT5 Simulated DOM Bridge
=========================
WebSocket server that creates a simulated Depth of Market visualization
using real Bid/Ask prices from MetaTrader 5.

The DOM levels are generated around the current price, creating a realistic
looking orderbook visualization.

Usage:
    python bridge.py

Requirements:
    pip install MetaTrader5 websockets
"""

import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Dict, List, Set, Optional
import MetaTrader5 as mt5
import websockets
from websockets.server import WebSocketServerProtocol

# Import database module
try:
    from db import db, init_database
    DB_ENABLED = True
except ImportError:
    DB_ENABLED = False
    print("⚠️  Database module not found. Running without persistence.")

# ============================================================================
# CONFIGURATION
# ============================================================================

WEBSOCKET_HOST = "localhost"
WEBSOCKET_PORT = 8776
UPDATE_INTERVAL = 0.3  # seconds between updates (300ms for smooth animation)
BROKER_SUFFIX = "r"    # Broker-specific suffix to remove from display names

# DOM Configuration
DOM_LEVELS = 15  # Number of price levels above and below current price
VOLUME_MIN = 0.1
VOLUME_MAX = 5.0
ORDER_BLOCK_CHANCE = 0.05 # Chance to spawn an order block
ORDER_BLOCK_MULTIPLIER = 8.0 # Volume multiplier for order blocks

# Symbol Filter
SYMBOL_FILTER = [
    "XAUUSD",   # Gold
    "XAGUSD",   # Silver
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",
    "BTCUSD",  # Bitcoin
    "ETHUSD",  # Ethereum
    "SOLUSD",  # Solana
    "XRPUSD",  # Ripple
]

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============================================================================
# MT5 SYMBOL MANAGEMENT
# ============================================================================

class SymbolManager:
    """Manages MT5 symbols and their display names."""
    
    def __init__(self, suffix: str = BROKER_SUFFIX):
        self.suffix = suffix
        self.symbols: Dict[str, str] = {}
        self.mt5_to_display: Dict[str, str] = {}
        self.symbol_info: Dict[str, Dict] = {}  # Store symbol info
    
    def generate_display_name(self, mt5_symbol: str) -> str:
        if mt5_symbol.endswith(self.suffix):
            return mt5_symbol[:-len(self.suffix)]
        return mt5_symbol
    
    def fetch_visible_symbols(self) -> List[str]:
        # Important: Try to select symbols in filter if not visible
        if SYMBOL_FILTER:
            for s in SYMBOL_FILTER:
                # Try simple name and with suffix
                potential_names = [s, s + self.suffix]
                for name in potential_names:
                    # Force selection and subscription
                    if mt5.symbol_select(name, True):
                        logger.info(f"  Selected: {name}")
                        # Also try to subscribe to book to force data streaming
                        mt5.market_book_add(name)
                    else:
                        logger.debug(f"  Could not select: {name}")

        symbols = mt5.symbols_get(visible=True)
        
        if symbols is None:
            logger.error("Failed to get symbols from MT5")
            return []
        
        self.symbols.clear()
        self.mt5_to_display.clear()
        self.symbol_info.clear()
        
        for symbol in symbols:
            mt5_name = symbol.name
            display_name = self.generate_display_name(mt5_name)
            
            if SYMBOL_FILTER:
                if display_name not in SYMBOL_FILTER:
                    continue
            
            self.symbols[display_name] = mt5_name
            self.mt5_to_display[mt5_name] = display_name
            
            # Store symbol info for price calculations
            self.symbol_info[display_name] = {
                'digits': symbol.digits,
                'point': symbol.point,
                'tick_size': symbol.trade_tick_size if symbol.trade_tick_size > 0 else symbol.point
            }
        
        if SYMBOL_FILTER:
            logger.info(f"Filtered to {len(self.symbols)} symbols")
        else:
            logger.info(f"Found {len(self.symbols)} symbols")
        
        for display, mt5_name in self.symbols.items():
            logger.info(f"  -> {display}")
        
        # Sort by filter order
        if SYMBOL_FILTER:
            ordered = []
            for s in SYMBOL_FILTER:
                if s in self.symbols:
                    ordered.append(s)
            return ordered
            
        return list(self.symbols.keys())
    
    def get_mt5_symbol(self, display_name: str) -> Optional[str]:
        return self.symbols.get(display_name)
    
    def get_symbol_info(self, display_name: str) -> Dict:
        return self.symbol_info.get(display_name, {'digits': 4, 'point': 0.0001, 'tick_size': 0.0001})
    
    def get_all_mt5_symbols(self) -> List[str]:
        return list(self.symbols.values())
    
    def get_all_display_symbols(self) -> List[str]:
        if SYMBOL_FILTER:
            return [s for s in SYMBOL_FILTER if s in self.symbols]
        return list(self.symbols.keys())


# ============================================================================
# SIMULATED DOM GENERATOR
# ============================================================================

class SimulatedDOMGenerator:
    """Generates simulated DOM data based on real Bid/Ask prices."""
    
    def __init__(self, symbol_manager: SymbolManager):
        self.symbol_manager = symbol_manager
        self.volume_cache: Dict[str, Dict[float, float]] = {}  # Persistent volumes
        self.last_tick_time: Dict[str, int] = {} # Track last tick time to pause simulation
        self.order_blocks: Dict[str, Set[float]] = {} # Track persistent Order Block levels

    def get_dom_data(self, mt5_symbol: str) -> Optional[Dict]:
        """Generate simulated DOM data for a symbol."""
        tick = mt5.symbol_info_tick(mt5_symbol)
        
        # If tick, bid, or ask is missing/zero, return None
        if tick is None:
            if random.random() < 0.01:
                logger.warning(f"Tick is None for {mt5_symbol}")
            return None
        
        if tick.bid == 0 or tick.ask == 0:
            if random.random() < 0.01:
                logger.warning(f"Zero price for {mt5_symbol}: Bid={tick.bid}, Ask={tick.ask}")
            return None
        
        display_name = self.symbol_manager.mt5_to_display.get(mt5_symbol)
        if not display_name:
            return None
        
        info = self.symbol_manager.get_symbol_info(display_name)
        digits = info['digits']
        point = info['point']
        tick_size = info['tick_size']
        
        mid_price = (tick.bid + tick.ask) / 2

        # Check for market activity
        last_time = self.last_tick_time.get(mt5_symbol, 0)
        current_time = tick.time_msc
        should_update_volume = (current_time != last_time)
        
        # Always update last time
        self.last_tick_time[mt5_symbol] = current_time

        if display_name in ['XAUUSD', 'XAGUSD']:
            level_step = 0.50
        elif 'JPY' in display_name:
            level_step = 0.01
        
        # Dynamic step for Crypto and others based on price
        else:
            if mid_price > 1000:
                level_step = 1.0
            elif mid_price > 100:
                level_step = 0.1
            elif mid_price > 10:
                level_step = 0.01
            elif mid_price > 1:
                level_step = 0.001
            else:
                level_step = 0.0001
        
        mid_price = (tick.bid + tick.ask) / 2
        spread = tick.ask - tick.bid
        
        # Generate price levels
        asks = []  # Sell orders (above mid price)
        bids = []  # Buy orders (below mid price)
        
        # Initialize persistent storage
        if display_name not in self.volume_cache:
            self.volume_cache[display_name] = {}
        if display_name not in self.order_blocks:
            self.order_blocks[display_name] = set()
        
        cache = self.volume_cache[display_name]
        blocks = self.order_blocks[display_name]
        
        # Manage Order Blocks (Spawn/Despawn)
        if should_update_volume:
            # Chance to add a new block
            if random.random() < ORDER_BLOCK_CHANCE:
                # Pick a random level offset within visible range
                offset = random.randint(3, DOM_LEVELS - 3) 
                is_ask = random.random() > 0.5
                block_price = round(tick.ask + (offset * level_step), digits) if is_ask else round(tick.bid - (offset * level_step), digits)
                blocks.add(block_price)
                
            # Chance to remove a block
            if blocks and random.random() < ORDER_BLOCK_CHANCE:
                to_remove = random.choice(list(blocks))
                blocks.remove(to_remove)
                if to_remove in cache:
                    del cache[to_remove] # Force reset next loop

        # Generate ASK levels (sell orders - above current price)
        for i in range(DOM_LEVELS):
            price = round(tick.ask + (i * level_step), digits)
            
            # Get cached volume or generate new
            if price not in cache:
                # Initial volume
                base_volume = random.uniform(VOLUME_MIN, VOLUME_MAX) * (1 - (i / DOM_LEVELS) * 0.5)
                if price in blocks:
                    base_volume *= ORDER_BLOCK_MULTIPLIER
                cache[price] = round(base_volume, 2)
            
            # Only flicker/update if marked active
            if should_update_volume:
                # Add small random variation
                new_vol = cache[price] * random.uniform(0.9, 1.1)
                
                # Check block status alignment
                if price in blocks and new_vol < (VOLUME_MAX * 2):
                     # Was normal, now block -> Boost
                     new_vol = random.uniform(VOLUME_MIN, VOLUME_MAX) * ORDER_BLOCK_MULTIPLIER
                
                cache[price] = round(new_vol, 2)
            
            asks.append({
                'price': price,
                'volume': cache[price],
                'total': round(cache[price] * price, 2)
            })
        
        # Generate BID levels (buy orders - below current price)
        for i in range(DOM_LEVELS):
            price = round(tick.bid - (i * level_step), digits)
            
            if price not in cache:
                base_volume = random.uniform(VOLUME_MIN, VOLUME_MAX) * (1 - (i / DOM_LEVELS) * 0.5)
                if price in blocks:
                    base_volume *= ORDER_BLOCK_MULTIPLIER
                cache[price] = round(base_volume, 2)
            
            if should_update_volume:
                new_vol = cache[price] * random.uniform(0.9, 1.1)
                
                if price in blocks and new_vol < (VOLUME_MAX * 2):
                     new_vol = random.uniform(VOLUME_MIN, VOLUME_MAX) * ORDER_BLOCK_MULTIPLIER
                     
                cache[price] = round(new_vol, 2)
            
            bids.append({
                'price': price,
                'volume': cache[price],
                'total': round(cache[price] * price, 2)
            })
        
        # Calculate max volume for scaling
        all_volumes = [a['volume'] for a in asks] + [b['volume'] for b in bids]
        max_volume = max(all_volumes) if all_volumes else 1
        
        # Clean old cache entries
        current_prices = set([a['price'] for a in asks] + [b['price'] for b in bids])
        old_prices = set(cache.keys()) - current_prices
        for old_price in list(old_prices)[:10]:  # Clean up to 10 old entries
            del cache[old_price]
        
        return {
            'type': 'DOM_DATA',
            'symbol': display_name,
            'bid': round(tick.bid, digits),
            'ask': round(tick.ask, digits),
            'spread': round(spread / point),
            'spread_pips': round(spread / point / 10, 1) if digits == 5 or digits == 3 else round(spread / point, 1),
            'mid_price': round(mid_price, digits),
            'asks': asks,
            'bids': bids,
            'max_volume': round(max_volume, 2),
            'digits': digits,
            'timestamp': datetime.now().isoformat()
        }


# ============================================================================
# WEBSOCKET SERVER
# ============================================================================

class DOMServer:
    """WebSocket server for broadcasting simulated DOM data."""
    
    def __init__(self):
        self.symbol_manager = SymbolManager()
        self.dom_generator = SimulatedDOMGenerator(self.symbol_manager)
        self.clients: Set[WebSocketServerProtocol] = set()
        self.running = False
    
    def initialize_mt5(self) -> bool:
        # Try to connect specifically to FBS terminal
        fbs_path = r"C:\Program Files\FBS MetaTrader 5\terminal64.exe"
        
        if not mt5.initialize(path=fbs_path):
            logger.info(f"Failed to initialize with FBS path, trying default...")
            if not mt5.initialize():
                logger.error(f"MT5 initialization failed: {mt5.last_error()}")
                return False
        
        terminal_info = mt5.terminal_info()
        if terminal_info:
            logger.info(f"Connected to MT5: {terminal_info.name}")
            logger.info(f"Account: {mt5.account_info().login}")
        
        return True
    
    def shutdown_mt5(self) -> None:
        mt5.shutdown()
        logger.info("MT5 connection closed")
    
    async def handle_client(self, websocket: WebSocketServerProtocol) -> None:
        client_id = id(websocket)
        self.clients.add(websocket)
        logger.info(f"Client connected: {client_id} | Total: {len(self.clients)}")
        
        try:
            # Send symbol list
            symbol_list = self.symbol_manager.get_all_display_symbols()
            await websocket.send(json.dumps({
                'type': 'SYMBOL_LIST',
                'data': symbol_list,
                'count': len(symbol_list)
            }))
            logger.info(f"Sent SYMBOL_LIST: {len(symbol_list)} symbols")
            
            # Keep connection alive
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.handle_client_message(websocket, data)
                except json.JSONDecodeError:
                    pass
        
        except websockets.ConnectionClosed:
            logger.info(f"Client disconnected: {client_id}")
        finally:
            self.clients.discard(websocket)
    
    async def handle_client_message(self, websocket: WebSocketServerProtocol, data: Dict) -> None:
        msg_type = data.get('type')
        
        if msg_type == 'GET_DOM':
            symbol = data.get('symbol')
            if symbol:
                mt5_symbol = self.symbol_manager.get_mt5_symbol(symbol)
                if mt5_symbol:
                    dom_data = self.dom_generator.get_dom_data(mt5_symbol)
                    if dom_data:
                        await websocket.send(json.dumps(dom_data))
        
        elif msg_type == 'PING':
            await websocket.send(json.dumps({'type': 'PONG'}))
    
    async def broadcast_loop(self) -> None:
        """Broadcast DOM data for all symbols."""
        while self.running:
            if self.clients:
                for mt5_symbol in self.symbol_manager.get_all_mt5_symbols():
                    try:
                        dom_data = self.dom_generator.get_dom_data(mt5_symbol)
                        
                        if dom_data:
                            # Print first few updates to console to prove data flow
                            # Log first 50 updates per symbol, then sample
                            should_log = random.random() < 0.05
                            if should_log:
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] {mt5_symbol} Bid: {dom_data['bid']} Ask: {dom_data['ask']}")
                                logger.info(f"Generated data for {mt5_symbol}: {dom_data['bid']}/{dom_data['ask']}")
                            
                            message = json.dumps(dom_data)
                            
                            disconnected = set()
                            for client in self.clients:
                                try:
                                    await client.send(message)
                                except websockets.ConnectionClosed:
                                    disconnected.add(client)
                            
                            self.clients -= disconnected
                        else:
                             # Log why it failed (already logged in get_dom_data, but let's be sure)
                             if random.random() < 0.1:
                                 logger.warning(f"No data generated for {mt5_symbol}")

                    except Exception as e:
                        logger.error(f"Error processing {mt5_symbol}: {e}", exc_info=True)
                        continue
            
            await asyncio.sleep(UPDATE_INTERVAL)
    
    async def run(self) -> None:
        if not self.initialize_mt5():
            return
        
        self.symbol_manager.fetch_visible_symbols()
        self.running = True
        
        # Initialize database
        if DB_ENABLED:
            logger.info("Initializing Turso database...")
            if init_database():
                logger.info("✅ Database connected and initialized")
            else:
                logger.warning("⚠️ Database initialization failed - running without persistence")
        
        broadcast_task = asyncio.create_task(self.broadcast_loop())
        
        # Start price snapshot task if DB is enabled
        snapshot_task = None
        if DB_ENABLED:
            snapshot_task = asyncio.create_task(self.price_snapshot_loop())
        
        logger.info(f"Starting WebSocket server on ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
        
        try:
            async with websockets.serve(
                self.handle_client,
                WEBSOCKET_HOST,
                WEBSOCKET_PORT,
                ping_interval=30,
                ping_timeout=10
            ):
                logger.info("Server running. Press Ctrl+C to stop.")
                await asyncio.Future()
        
        except asyncio.CancelledError:
            logger.info("Shutting down...")
        finally:
            self.running = False
            broadcast_task.cancel()
            if snapshot_task:
                snapshot_task.cancel()
            try:
                await broadcast_task
                if snapshot_task:
                    await snapshot_task
            except asyncio.CancelledError:
                pass
            self.shutdown_mt5()
    
    async def price_snapshot_loop(self) -> None:
        """Periodically save price snapshots to database."""
        from db import db, PRICE_SNAPSHOT_INTERVAL
        
        while self.running:
            for mt5_symbol in self.symbol_manager.get_all_mt5_symbols():
                try:
                    tick = mt5.symbol_info_tick(mt5_symbol)
                    if tick and tick.bid > 0 and tick.ask > 0:
                        display_name = self.symbol_manager.mt5_to_display.get(mt5_symbol)
                        if display_name:
                            db.save_price_snapshot(display_name, tick.bid, tick.ask)
                except Exception as e:
                    logger.debug(f"Snapshot error for {mt5_symbol}: {e}")
            
            await asyncio.sleep(PRICE_SNAPSHOT_INTERVAL)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("""
+==============================================================+
|         MT5 SIMULATED DOM - WebSocket Server                 |
+==============================================================+
|  Real Bid/Ask prices with simulated depth levels             |
|  Creates realistic orderbook visualization                   |
+==============================================================+
    """)
    
    server = DOMServer()
    
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
