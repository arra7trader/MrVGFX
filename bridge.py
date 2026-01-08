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
ORDER_BLOCK_MAX_COUNT = 5  # Max number of order blocks per symbol

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
        self.last_price: Dict[str, float] = {}   # Track last mid price for direction
        self.order_blocks: Dict[str, List] = {}  # Track simulated order blocks
        self.order_blocks: Dict[str, Set[float]] = {} # Track persistent Order Block levels
        # Stable Support & Resistance (only update when 20%+ stronger)
        self.stable_support: Dict[str, Dict] = {}  # {symbol: {'price': x, 'volume': y}}
        self.stable_resistance: Dict[str, Dict] = {}  # {symbol: {'price': x, 'volume': y}}

    def _calculate_signal(self, buy_pressure, sell_pressure, direction, confidence,
                          total_bid_vol, total_ask_vol, strongest_level):
        """Calculate trading signal based on STRONGEST LEVEL (most pending orders)."""
        
        imbalance = buy_pressure - sell_pressure
        strongest_side = strongest_level[2]  # 'BID' or 'ASK'
        strongest_volume = strongest_level[1]
        
        # 1. Signal Type based on STRONGEST LEVEL (where most pending orders are)
        # BID = buyers waiting = support = BUY signal
        # ASK = sellers waiting = resistance = SELL signal
        if strongest_side == 'BID' and strongest_volume > 3:
            signal_type = "BUY"
        elif strongest_side == 'ASK' and strongest_volume > 3:
            signal_type = "SELL"
        else:
            signal_type = "WAIT"
        
        # 2. Signal Strength based on volume concentration
        strength = min(100, strongest_volume * 10 + abs(imbalance))
        
        # 3. Trend Direction
        if imbalance > 20:
            trend = "STRONG_UP"
            trend_arrow = "↑↑"
        elif imbalance > 5:
            trend = "UP"
            trend_arrow = "↑"
        elif imbalance < -20:
            trend = "STRONG_DOWN"
            trend_arrow = "↓↓"
        elif imbalance < -5:
            trend = "DOWN"
            trend_arrow = "↓"
        else:
            trend = "SIDEWAYS"
            trend_arrow = "→"
        
        # 4. Volume Confirmation
        volume_ratio = total_bid_vol / total_ask_vol if total_ask_vol > 0 else 1
        if signal_type == "BUY":
            volume_confirms = volume_ratio > 1.1  # Bid volume > Ask volume for BUY
        elif signal_type == "SELL":
            volume_confirms = volume_ratio < 0.9  # Ask volume > Bid volume for SELL
        else:
            volume_confirms = False
        
        # 5. Checklist Conditions
        checklist = {
            'volume_dominant': {
                'label': 'Volume Dominant',
                'passed': abs(imbalance) > 10,
                'value': f"{'Bid' if imbalance > 0 else 'Ask'} +{abs(imbalance):.1f}%"
            },
            'trend_aligned': {
                'label': 'Trend Aligned',
                'passed': (signal_type == "BUY" and trend in ["UP", "STRONG_UP"]) or 
                          (signal_type == "SELL" and trend in ["DOWN", "STRONG_DOWN"]) or
                          signal_type == "WAIT",
                'value': trend
            },
            'confidence_high': {
                'label': 'Confidence High',
                'passed': confidence >= 60,
                'value': f"{confidence:.0f}%"
            },
            'volume_confirms': {
                'label': 'Volume Confirms',
                'passed': volume_confirms or signal_type == "WAIT",
                'value': f"Ratio {volume_ratio:.2f}"
            },
            'strong_level': {
                'label': 'Strong Level',
                'passed': strongest_level[1] > 5,  # Volume > 5 lots
                'value': f"{strongest_level[1]:.1f} lots @ {strongest_level[2]}"
            }
        }
        
        # Count passed conditions
        passed_count = sum(1 for c in checklist.values() if c['passed'])
        total_conditions = len(checklist)
        
        return {
            'type': signal_type,
            'strength': round(strength, 1),
            'trend': trend,
            'trend_arrow': trend_arrow,
            'volume_confirms': volume_confirms,
            'checklist': checklist,
            'passed_count': passed_count,
            'total_conditions': total_conditions,
            'ready_to_trade': passed_count >= 4 and signal_type != "WAIT"
        }

    def _calculate_entry_zones(self, bid, ask, support_price, resistance_price, 
                                support_vol, resistance_vol, point_value, digits):
        """Calculate entry zones with Stop Loss and Take Profit levels."""
        
        spread = ask - bid
        mid_price = (ask + bid) / 2
        
        # Determine pip multiplier based on digits
        if digits == 5 or digits == 3:  # Forex 5 digits or JPY pairs
            pip_value = point_value * 10
        else:
            pip_value = point_value
        
        # ============================================================
        # BUY ZONE - Entry above support, SL below support
        # ============================================================
        # Entry zone: just above support level
        buy_entry_low = support_price + (spread * 1)
        buy_entry_high = support_price + (spread * 3)
        
        # Stop Loss: below support with buffer
        buy_sl = support_price - (spread * 5)
        buy_sl_pips = round((buy_entry_low - buy_sl) / pip_value, 1)
        
        # Take Profit targets based on Risk/Reward
        risk_distance = buy_entry_low - buy_sl
        buy_tp1 = round(buy_entry_low + risk_distance, digits)  # 1:1 RR
        buy_tp2 = round(buy_entry_low + (risk_distance * 2), digits)  # 1:2 RR
        buy_tp3 = round(buy_entry_low + (risk_distance * 3), digits)  # 1:3 RR
        
        # Distance to SL in price terms
        buy_sl_distance = round(buy_entry_low - buy_sl, digits)
        
        # Buyer strength based on support volume
        buy_strength = min(100, int(support_vol * 12))
        
        # ============================================================
        # SELL ZONE - Entry below resistance, SL above resistance  
        # ============================================================
        # Entry zone: just below resistance level
        sell_entry_high = resistance_price - (spread * 1)
        sell_entry_low = resistance_price - (spread * 3)
        
        # Stop Loss: above resistance with buffer
        sell_sl = resistance_price + (spread * 5)
        sell_sl_pips = round((sell_sl - sell_entry_high) / pip_value, 1)
        
        # Take Profit targets based on Risk/Reward
        risk_distance_sell = sell_sl - sell_entry_high
        sell_tp1 = round(sell_entry_high - risk_distance_sell, digits)  # 1:1 RR
        sell_tp2 = round(sell_entry_high - (risk_distance_sell * 2), digits)  # 1:2 RR
        sell_tp3 = round(sell_entry_high - (risk_distance_sell * 3), digits)  # 1:3 RR
        
        # Distance to SL in price terms
        sell_sl_distance = round(sell_sl - sell_entry_high, digits)
        
        # Seller strength based on resistance volume
        sell_strength = min(100, int(resistance_vol * 12))
        
        return {
            'buy_zone': {
                'entry_low': round(buy_entry_low, digits),
                'entry_high': round(buy_entry_high, digits),
                'stop_loss': round(buy_sl, digits),
                'sl_pips': buy_sl_pips,
                'sl_distance': buy_sl_distance,
                'tp1': buy_tp1,
                'tp2': buy_tp2,
                'tp3': buy_tp3,
                'strength': buy_strength,
                'support_price': round(support_price, digits),
                'recommended': buy_strength > sell_strength
            },
            'sell_zone': {
                'entry_low': round(sell_entry_low, digits),
                'entry_high': round(sell_entry_high, digits),
                'stop_loss': round(sell_sl, digits),
                'sl_pips': sell_sl_pips,
                'sl_distance': sell_sl_distance,
                'tp1': sell_tp1,
                'tp2': sell_tp2,
                'tp3': sell_tp3,
                'strength': sell_strength,
                'resistance_price': round(resistance_price, digits),
                'recommended': sell_strength > buy_strength
            }
        }

    def _classify_orders(self, bids, asks, max_volume):
        """Classify orders into Large/Medium/Small for bubble visualization."""
        
        def classify_size(volume, max_vol):
            if max_vol == 0:
                return 'SMALL', 10
            ratio = volume / max_vol
            if ratio > 0.6:
                return 'LARGE', min(60, max(35, ratio * 60))
            elif ratio > 0.3:
                return 'MEDIUM', min(35, max(20, ratio * 50))
            else:
                return 'SMALL', min(20, max(8, ratio * 40))
        
        bid_bubbles = []
        for i, b in enumerate(bids):
            size_class, radius = classify_size(b['volume'], max_volume)
            bid_bubbles.append({
                'price': b['price'],
                'volume': b['volume'],
                'size': size_class,
                'radius': round(radius, 1),
                'level': i,
                'side': 'BID'
            })
        
        ask_bubbles = []
        for i, a in enumerate(asks):
            size_class, radius = classify_size(a['volume'], max_volume)
            ask_bubbles.append({
                'price': a['price'],
                'volume': a['volume'],
                'size': size_class,
                'radius': round(radius, 1),
                'level': i,
                'side': 'ASK'
            })
        
        # Find notable orders (LARGE orders that stand out)
        large_bids = [b for b in bid_bubbles if b['size'] == 'LARGE']
        large_asks = [a for a in ask_bubbles if a['size'] == 'LARGE']
        
        return {
            'bids': bid_bubbles,
            'asks': ask_bubbles,
            'large_bid_count': len(large_bids),
            'large_ask_count': len(large_asks),
            'whale_alert': len(large_bids) > 2 or len(large_asks) > 2
        }

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
        
    def get_dom_data(self, mt5_symbol: str) -> Dict:
        tick = mt5.symbol_info_tick(mt5_symbol)
        if not tick:
            # logger.warning(f"get_dom_data: Tick is None for {mt5_symbol}")
            return None
        
        info = mt5.symbol_info(mt5_symbol)
        if not info:
            logger.warning(f"get_dom_data: SymbolInfo is None for {mt5_symbol}")
            return None
            
        display_name = self.symbol_manager.mt5_to_display.get(mt5_symbol, mt5_symbol)
        digits = info.digits
        point = info.point
        
        # ====================================================================
        # ATTEMPT 1: REAL MARKET DEPTH (Level 2)
        # ====================================================================
        real_book = mt5.market_book_get(mt5_symbol)
        
        asks = []
        bids = []
        is_real_data = False
        
        if real_book and len(real_book) > 0:
            is_real_data = True
            # Process Real Data
            for item in real_book:
                entry = {
                    'price': item.price,
                    'volume': float(item.volume),
                    'total': round(item.price * item.volume, 2)
                }
                if item.type == mt5.BOOK_TYPE_SELL:
                    asks.append(entry)
                elif item.type == mt5.BOOK_TYPE_BUY:
                    bids.append(entry)
            
            # Sort and Slice
            asks.sort(key=lambda x: x['price'])
            bids.sort(key=lambda x: x['price'], reverse=True)
            asks = asks[:DOM_LEVELS]
            bids = bids[:DOM_LEVELS]
            
        else:
            # ================================================================
            # ATTEMPT 2: REACTIVE EMULATION (Smart Simulation)
            # ================================================================
            # Calculate pressure from Price Action
            mid_price = (tick.bid + tick.ask) / 2
            spread = tick.ask - tick.bid
            
            last_mid = self.last_price.get(mt5_symbol, mid_price)
            price_change = mid_price - last_mid
            self.last_price[mt5_symbol] = mid_price
            
            # Momentum Factor (-1.0 to 1.0)
            momentum = 0
            if price_change > 0: momentum = 0.3  # Buying pressure
            elif price_change < 0: momentum = -0.3 # Selling pressure
            
            momentum += random.uniform(-0.1, 0.1) # Random sway
            bid_strength = 1.0 + momentum
            ask_strength = 1.0 - momentum
            
            # Init persistent storage
            if display_name not in self.volume_cache: self.volume_cache[display_name] = {}
            if display_name not in self.order_blocks: self.order_blocks[display_name] = set()
            cache = self.volume_cache[display_name]
            blocks = self.order_blocks[display_name]
            
            # Timing check
            current_time = tick.time_msc
            last_time = self.last_tick_time.get(mt5_symbol, 0)
            should_update_volume = (current_time != last_time)
            self.last_tick_time[mt5_symbol] = current_time

            # Level step determination - WIDE range as requested
            # Use 0.6% of mid_price per level = ~12% total range (20 levels each side)
            # Example: XAUUSD at 4300 = 25.8 per level = ~516 range each side (3800-4800)
            if 'JPY' in display_name: 
                # JPY pairs: e.g., USDJPY at 150 = 0.9 per level = ~18 range each side
                level_step = max(0.1, round(mid_price * 0.006, 2))
            elif 'XAU' in display_name: 
                # XAUUSD: e.g., at 4300 = 25.8 per level = ~516 range each side
                level_step = max(5.0, round(mid_price * 0.006, 1))
            elif 'XAG' in display_name: 
                # XAGUSD: e.g., at 30 = 0.18 per level
                level_step = max(0.05, round(mid_price * 0.006, 3))
            elif 'BTC' in display_name: 
                # BTC: e.g., at 95000 = 570 per level = ~11,400 range each side
                level_step = max(100.0, round(mid_price * 0.006, 0))
            elif 'ETH' in display_name: 
                # ETH: e.g., at 3500 = 21 per level
                level_step = max(5.0, round(mid_price * 0.006, 1))
            elif 'SOL' in display_name:
                # SOL: e.g., at 200 = 1.2 per level
                level_step = max(0.2, round(mid_price * 0.006, 2))
            elif 'XRP' in display_name:
                # XRP: e.g., at 2.5 = 0.015 per level
                level_step = max(0.003, round(mid_price * 0.006, 4))
            else: 
                # All Forex pairs: e.g., EURUSD at 1.10 = 0.0066 per level = ~132 pips each side
                level_step = max(point * 10, round(mid_price * 0.006, 5))
            
            # Manage Order Blocks
            if should_update_volume:
                if random.random() < 0.05:
                     if len(blocks) < ORDER_BLOCK_MAX_COUNT and random.random() < ORDER_BLOCK_CHANCE:
                        price_level = round(mid_price + ((1 if random.random()>0.5 else -1) * level_step * random.randint(5,10)), digits)
                        blocks.add(price_level)
                     if blocks and random.random() < ORDER_BLOCK_CHANCE:
                        blocks.remove(random.choice(list(blocks)))

            # Generate Asks (Sellers) - Smaller volumes, more scattered, occasional spike
            ask_seed = int(tick.time_msc % 1000)  # Different seed
            for i in range(DOM_LEVELS):
                price = round(tick.ask + (i * level_step), digits)
                if price not in cache:
                    # Asks: Generally smaller volumes, exponential decay
                    base_range = random.uniform(VOLUME_MIN * 0.5, VOLUME_MAX * 0.6)
                    decay = (1 - (i/DOM_LEVELS)**2) * 0.6
                    variance = random.uniform(0.3, 1.4)
                    base_vol = base_range * decay * ask_strength * variance
                    
                    # 15% chance of spike (sudden resistance)
                    if random.random() < 0.15:
                        base_vol *= random.uniform(2.5, 4.0)
                    # 10% chance of gap (very thin)
                    elif random.random() < 0.10:
                        base_vol *= 0.15
                    
                    if price in blocks: 
                        base_vol *= ORDER_BLOCK_MULTIPLIER
                    
                    cache[price] = round(max(0.05, base_vol), 2)
                elif should_update_volume:
                    cache[price] = round(cache[price] * random.uniform(0.8, 1.2), 2)
                asks.append({'price': price, 'volume': cache[price], 'total': round(cache[price]*price, 2)})
            
            # Generate Bids (Buyers) - Larger volumes, more clustered, support walls
            bid_seed = int((tick.time_msc + 500) % 1000)  # Different seed offset
            cluster_start = random.randint(3, 10)  # Random cluster position
            for i in range(DOM_LEVELS):
                price = round(tick.bid - (i * level_step), digits)
                if price not in cache:
                    # Bids: Generally larger volumes, linear decay
                    base_range = random.uniform(VOLUME_MIN * 0.8, VOLUME_MAX * 1.3)
                    decay = (1 - (i/DOM_LEVELS)*0.3) * 0.85
                    
                    # Cluster pattern: several consecutive levels with similar high volume
                    if cluster_start <= i <= cluster_start + 3:
                        variance = random.uniform(1.5, 2.2)
                    else:
                        variance = random.uniform(0.5, 1.3)
                    
                    base_vol = base_range * decay * bid_strength * variance
                    
                    # 12% chance of wall (big support)
                    if random.random() < 0.12:
                        base_vol *= random.uniform(2.0, 3.0)
                    
                    if price in blocks: 
                        base_vol *= ORDER_BLOCK_MULTIPLIER
                    
                    cache[price] = round(max(0.1, base_vol), 2)
                elif should_update_volume:
                    cache[price] = round(cache[price] * random.uniform(0.9, 1.1), 2)
                bids.append({'price': price, 'volume': cache[price], 'total': round(cache[price]*price, 2)})
        # Calculate max volume for scaling
        all_volumes = [a['volume'] for a in asks] + [b['volume'] for b in bids]
        max_volume = max(all_volumes) if all_volumes else 1
        
        # ========================================================================
        # ORDER FLOW ANALYSIS
        # ========================================================================
        
        # Calculate total volumes
        total_bid_volume = sum(b['volume'] for b in bids)
        total_ask_volume = sum(a['volume'] for a in asks)
        total_volume = total_bid_volume + total_ask_volume
        
        # Order Imbalance (Buy vs Sell pressure)
        buy_pressure = round((total_bid_volume / total_volume) * 100, 1) if total_volume > 0 else 50
        sell_pressure = round((total_ask_volume / total_volume) * 100, 1) if total_volume > 0 else 50
        
        # Price Direction Prediction
        if is_real_data:
            direction = "REAL DATA"
            confidence = 100
        else:
            imbalance = buy_pressure - sell_pressure
            if imbalance > 10:
                direction = "BULLISH"
                confidence = min(95, 50 + imbalance)
            elif imbalance < -10:
                direction = "BEARISH"
                confidence = min(95, 50 + abs(imbalance))
            else:
                direction = "NEUTRAL"
                confidence = 50 - abs(imbalance)
        
        # Find Strongest Levels (for Support & Resistance display)
        # Strongest BID = SUPPORT level (where buyers are waiting)
        # Strongest ASK = RESISTANCE level (where sellers are waiting)
        current_bid = max(bids, key=lambda x: x['volume']) if bids else {'price': 0, 'volume': 0}
        current_ask = max(asks, key=lambda x: x['volume']) if asks else {'price': 0, 'volume': 0}
        
        # STICKY LOGIC: Only update if new level has 20%+ more volume
        # This keeps levels stable for placing pending orders
        if display_name not in self.stable_support or current_bid['volume'] > self.stable_support[display_name]['volume'] * 1.2:
            self.stable_support[display_name] = current_bid
        if display_name not in self.stable_resistance or current_ask['volume'] > self.stable_resistance[display_name]['volume'] * 1.2:
            self.stable_resistance[display_name] = current_ask
        
        strongest_bid = self.stable_support[display_name]
        strongest_ask = self.stable_resistance[display_name]
        
        # Overall strongest (for signal calculation)
        all_levels = [(b['price'], b['volume'], 'BID') for b in bids] + [(a['price'], a['volume'], 'ASK') for a in asks]
        strongest_level = max(all_levels, key=lambda x: x[1]) if all_levels else (0, 0, 'NONE')
        
        # Clean old cache entries (Only if we used cache)
        if not is_real_data and display_name in self.volume_cache:
            cache = self.volume_cache[display_name]
            current_prices = set([a['price'] for a in asks] + [b['price'] for b in bids])
            old_prices = set(cache.keys()) - current_prices
            for old_price in list(old_prices)[:10]:
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
            'timestamp': datetime.now().isoformat(),
            'is_real_data': is_real_data,
            # Order Flow Analysis
            'analysis': {
                'buy_pressure': buy_pressure,
                'sell_pressure': sell_pressure,
                'direction': direction,
                'confidence': round(confidence, 1),
                'strongest_price': strongest_level[0],
                'strongest_volume': round(strongest_level[1], 2),
                'strongest_side': strongest_level[2],
                'total_bid_volume': round(total_bid_volume, 2),
                'total_ask_volume': round(total_ask_volume, 2),
                # Fixed Support & Resistance levels
                'support_price': round(strongest_bid['price'], digits),
                'support_volume': round(strongest_bid['volume'], 2),
                'resistance_price': round(strongest_ask['price'], digits),
                'resistance_volume': round(strongest_ask['volume'], 2)
            },
            # Signal Panel Data
            'signal': self._calculate_signal(
                buy_pressure, sell_pressure, direction, confidence,
                total_bid_volume, total_ask_volume, strongest_level
            ),
            # Entry Zones Data (NEW)
            'entry_zones': self._calculate_entry_zones(
                tick.bid, tick.ask,
                strongest_bid['price'], strongest_ask['price'],
                strongest_bid['volume'], strongest_ask['volume'],
                point, digits
            ),
            # Bubble Visualization Data (NEW)
            'bubbles': self._classify_orders(bids, asks, max_volume)
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
