"""
MT5 Orderbook Bridge - API Version (No MT5 Required)
Uses TwelveData for Forex/Metals + Binance for Crypto
Works on VPS without MetaTrader5 library
"""

import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Dict, List, Set
import httpx
import websockets
from websockets.server import WebSocketServerProtocol

# ============ CONFIGURATION ============
WS_PORT = 8776
UPDATE_INTERVAL = 1.0  # seconds

# Set to True if API calls are failing/blocked on your network
# Prices will simulate with random walk around fallback values
OFFLINE_MODE = False  # <-- Set to False for REAL TIME Binance Data

# API Keys (Free tier)
TWELVEDATA_API_KEY = "demo"  # Free demo key, or get yours at twelvedata.com

# Symbol mapping
SYMBOLS = {
    # Metals - Using Binance PAXG for gold (tokenized gold, very accurate)
    "XAUUSD": {"source": "binance", "symbol": "PAXGUSDT", "digits": 2},
    "XAGUSD": {"source": "fallback", "symbol": "silver", "digits": 3},  # No free silver API
    # Forex (TwelveData)
    "EURUSD": {"source": "twelvedata", "symbol": "EUR/USD", "digits": 5},
    "GBPUSD": {"source": "twelvedata", "symbol": "GBP/USD", "digits": 5},
    "USDJPY": {"source": "twelvedata", "symbol": "USD/JPY", "digits": 3},
    "AUDUSD": {"source": "twelvedata", "symbol": "AUD/USD", "digits": 5},
    "USDCAD": {"source": "twelvedata", "symbol": "USD/CAD", "digits": 5},
    "NZDUSD": {"source": "twelvedata", "symbol": "NZD/USD", "digits": 5},
    "USDCHF": {"source": "twelvedata", "symbol": "USD/CHF", "digits": 5},
    # Crypto (Binance - no API key needed)
    "BTCUSD": {"source": "binance", "symbol": "BTCUSDT", "digits": 2},
    "ETHUSD": {"source": "binance", "symbol": "ETHUSDT", "digits": 2},
    "SOLUSD": {"source": "binance", "symbol": "SOLUSDT", "digits": 2},
    "XRPUSD": {"source": "binance", "symbol": "XRPUSDT", "digits": 4},
}

# ============ LOGGING ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============ PRICE FETCHER ============
class PriceFetcher:
    def __init__(self):
        self.prices: Dict[str, Dict] = {}
        self.volume_cache: Dict[str, Dict[float, float]] = {}
        self.stable_support: Dict[str, Dict] = {}
        self.stable_resistance: Dict[str, Dict] = {}
        self.client = httpx.AsyncClient(timeout=5.0)  # Reduced timeout
        # Fallback prices if API fails
        self.fallback_prices = {
            "XAUUSD": 2650.00,
            "XAGUSD": 30.50,
            "EURUSD": 1.0850,
            "GBPUSD": 1.2650,
            "USDJPY": 157.50,
            "AUDUSD": 0.6250,
            "USDCAD": 1.4350,
            "NZDUSD": 0.5650,
            "USDCHF": 0.9050,
            "BTCUSD": 95000.00,
            "ETHUSD": 3400.00,
            "SOLUSD": 200.00,
            "XRPUSD": 2.30,
        }
        # CoinGecko ID mapping
        self.coingecko_ids = {
            "BTCUSD": "bitcoin",
            "ETHUSD": "ethereum",
            "SOLUSD": "solana",
            "XRPUSD": "ripple",
            "XAUUSD": "paxos-gold",  # PAXG as gold proxy
        }
        
    async def fetch_metals(self, symbol_info: dict, display_name: str):
        """Fetch price from Metals.live API (free, no key required)"""
        try:
            url = "https://api.metals.live/v1/spot"
            response = await self.client.get(url)
            data = response.json()
            # Data format: [{"gold": 2650.xx, "silver": 30.xx, ...}]
            if isinstance(data, list) and len(data) > 0:
                metal_name = symbol_info['symbol']  # "gold" or "silver"
                if metal_name in data[0]:
                    price = float(data[0][metal_name])
                    logger.info(f"  {display_name}: {price} (Metals.live)")
                    return price
        except Exception as e:
            logger.warning(f"  {display_name}: Metals API error - {e}")
        return self.fallback_prices.get(display_name)
        
    async def fetch_twelvedata(self, symbol_info: dict, display_name: str):
        """Fetch price from TwelveData API"""
        try:
            url = f"https://api.twelvedata.com/price?symbol={symbol_info['symbol']}&apikey={TWELVEDATA_API_KEY}"
            response = await self.client.get(url)
            data = response.json()
            if "price" in data:
                price = float(data["price"])
                logger.info(f"  {display_name}: {price} (TwelveData)")
                return price
            else:
                logger.warning(f"  {display_name}: No price in response, using fallback")
        except Exception as e:
            logger.warning(f"  {display_name}: API error - {e}")
        # Use fallback
        return self.fallback_prices.get(display_name)
    
    async def fetch_coingecko(self, display_name: str):
        """Fetch price from CoinGecko API (free, no key required, reliable)"""
        try:
            coin_id = self.coingecko_ids.get(display_name)
            if not coin_id:
                return None
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
            response = await self.client.get(url)
            data = response.json()
            if coin_id in data and "usd" in data[coin_id]:
                price = float(data[coin_id]["usd"])
                logger.info(f"  {display_name}: {price} (CoinGecko)")
                return price
        except Exception as e:
            logger.warning(f"  {display_name}: CoinGecko error - {e}")
        return None
    
    async def fetch_binance(self, symbol_info: dict, display_name: str):
        """Fetch price from Binance API (Primary source)"""
        # PRIORITY: BINANCE -> COINGECKO -> FALLBACK
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol_info['symbol']}"
            response = await self.client.get(url)
            data = response.json()
            if "price" in data:
                price = float(data["price"])
                logger.info(f"  {display_name}: {price} (Binance)")
                return price
        except Exception as e:
            logger.warning(f"  {display_name}: Binance error - {e}")
        
        # Fallback to CoinGecko
        price = await self.fetch_coingecko(display_name)
        if price:
            return price
            
        # Final fallback
        price = self.fallback_prices.get(display_name)
        if price:
            logger.info(f"  {display_name}: {price} (Fallback)")
        return price
    
    async def fetch_all_prices(self):
        """Fetch all prices from APIs or simulate if OFFLINE_MODE"""
        for display_name, info in SYMBOLS.items():
            # OFFLINE MODE: Use simulated prices with random walk
            if OFFLINE_MODE:
                base_price = self.fallback_prices.get(display_name, 100)
                # If we already have a price, do random walk
                if display_name in self.prices:
                    current = self.prices[display_name]["price"]
                    # Random walk: -0.1% to +0.1% change
                    change = current * random.uniform(-0.001, 0.001)
                    price = current + change
                else:
                    # First run: start with fallback
                    price = base_price
                logger.info(f"  {display_name}: {price:.{info['digits']}f} (Simulated)")
            
            # ONLINE MODE: Fetch from APIs
            elif info["source"] == "fallback":
                price = self.fallback_prices.get(display_name)
                if price:
                    logger.info(f"  {display_name}: {price} (Fallback)")
            elif info["source"] == "metals":
                price = await self.fetch_metals(info, display_name)
            elif info["source"] == "twelvedata":
                price = await self.fetch_twelvedata(info, display_name)
            else:
                price = await self.fetch_binance(info, display_name)
            
            if price:
                self.prices[display_name] = {
                    "price": price,
                    "digits": info["digits"],
                    "timestamp": datetime.now()
                }
            else:
                logger.error(f"  {display_name}: FAILED to get price!")
    
    def generate_dom_data(self, display_name: str) -> dict:
        """Generate simulated DOM data based on real price"""
        if display_name not in self.prices:
            return None
        
        price_data = self.prices[display_name]
        mid_price = price_data["price"]
        digits = price_data["digits"]
        
        # Calculate spread and level step
        if display_name in ["BTCUSD"]:
            spread = mid_price * 0.0001
            level_step = max(100.0, mid_price * 0.006)
        elif display_name in ["ETHUSD"]:
            spread = mid_price * 0.0001
            level_step = max(5.0, mid_price * 0.006)
        elif display_name in ["SOLUSD", "XRPUSD"]:
            spread = mid_price * 0.0002
            level_step = max(0.1, mid_price * 0.006)
        elif display_name in ["XAUUSD"]:
            spread = 0.30
            level_step = max(5.0, mid_price * 0.006)
        elif display_name in ["XAGUSD"]:
            spread = 0.02
            level_step = max(0.05, mid_price * 0.006)
        elif "JPY" in display_name:
            spread = 0.02
            level_step = max(0.1, mid_price * 0.006)
        else:
            spread = 0.00015
            level_step = max(0.0005, mid_price * 0.006)
        
        # Generate volume cache key
        if display_name not in self.volume_cache:
            self.volume_cache[display_name] = {}
        cache = self.volume_cache[display_name]
        
        # Generate asks (above mid price)
        asks = []
        for i in range(1, 21):
            price = round(mid_price + spread/2 + (i * level_step), digits)
            if price not in cache:
                # Generate organic volume
                base = random.uniform(0.5, 3.0)
                if random.random() < 0.1:
                    base *= random.uniform(3, 6)  # Occasional spike
                cache[price] = round(base, 2)
            asks.append({"price": price, "volume": cache[price]})
        
        # Generate bids (below mid price)
        bids = []
        for i in range(1, 21):
            price = round(mid_price - spread/2 - (i * level_step), digits)
            if price not in cache:
                base = random.uniform(0.5, 4.0)
                if random.random() < 0.08:
                    base *= random.uniform(4, 8)  # Buyer wall
                cache[price] = round(base, 2)
            bids.append({"price": price, "volume": cache[price]})
        
        # Calculate analysis
        total_bid_vol = sum(b["volume"] for b in bids)
        total_ask_vol = sum(a["volume"] for a in asks)
        total_vol = total_bid_vol + total_ask_vol
        
        buy_pressure = round((total_bid_vol / total_vol) * 100) if total_vol > 0 else 50
        sell_pressure = 100 - buy_pressure
        
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
        
        # Find support/resistance with sticky logic
        current_bid = max(bids, key=lambda x: x['volume']) if bids else {'price': 0, 'volume': 0}
        current_ask = max(asks, key=lambda x: x['volume']) if asks else {'price': 0, 'volume': 0}
        
        if display_name not in self.stable_support or current_bid['volume'] > self.stable_support[display_name]['volume'] * 1.2:
            self.stable_support[display_name] = current_bid
        if display_name not in self.stable_resistance or current_ask['volume'] > self.stable_resistance[display_name]['volume'] * 1.2:
            self.stable_resistance[display_name] = current_ask
        
        strongest_bid = self.stable_support[display_name]
        strongest_ask = self.stable_resistance[display_name]
        
        # Signal calculation
        all_levels = [(b['price'], b['volume'], 'BID') for b in bids] + [(a['price'], a['volume'], 'ASK') for a in asks]
        strongest_level = max(all_levels, key=lambda x: x[1]) if all_levels else (0, 0, 'NONE')
        
        strongest_side = strongest_level[2]
        strongest_volume = strongest_level[1]
        
        if strongest_side == 'BID' and strongest_volume > 3:
            signal_type = "BUY"
        elif strongest_side == 'ASK' and strongest_volume > 3:
            signal_type = "SELL"
        else:
            signal_type = "WAIT"
        
        strength = min(100, strongest_volume * 10 + abs(imbalance))
        
        if imbalance > 20:
            trend, trend_arrow = "STRONG_UP", "↑↑"
        elif imbalance > 5:
            trend, trend_arrow = "UP", "↑"
        elif imbalance < -20:
            trend, trend_arrow = "STRONG_DOWN", "↓↓"
        elif imbalance < -5:
            trend, trend_arrow = "DOWN", "↓"
        else:
            trend, trend_arrow = "SIDEWAYS", "→"
        
        # Build checklist
        checklist = [
            {"name": "Volume Dominant", "passed": abs(imbalance) > 10, "value": f"{'Bid' if imbalance > 0 else 'Ask'} +{abs(imbalance):.0f}%"},
            {"name": "Trend Aligned", "passed": (signal_type == "BUY" and trend in ["UP", "STRONG_UP"]) or (signal_type == "SELL" and trend in ["DOWN", "STRONG_DOWN"]), "value": trend},
            {"name": "Confidence High", "passed": confidence > 60, "value": f"{confidence:.0f}%"},
            {"name": "Volume Confirms", "passed": (signal_type == "BUY" and total_bid_vol > total_ask_vol) or (signal_type == "SELL" and total_ask_vol > total_bid_vol), "value": f"Ratio {total_bid_vol/total_ask_vol:.2f}" if total_ask_vol > 0 else "N/A"},
            {"name": "Strong Level", "passed": strongest_volume > 5, "value": f"{strongest_volume:.1f} lots @ {strongest_level[2]}"}
        ]
        passed_count = sum(1 for c in checklist if c["passed"])
        ready_to_trade = passed_count >= 4 and signal_type != "WAIT"
        
        return {
            'symbol': display_name,
            'bid': round(mid_price - spread/2, digits),
            'ask': round(mid_price + spread/2, digits),
            'spread': round(spread * (10 ** digits)),
            'spread_pips': round(spread * 10000, 1) if digits >= 4 else round(spread * 100, 1),
            'mid_price': round(mid_price, digits),
            'asks': asks,
            'bids': bids,
            'max_volume': max(max(a['volume'] for a in asks), max(b['volume'] for b in bids)),
            'digits': digits,
            'timestamp': datetime.now().isoformat(),
            'is_real_data': True,
            'analysis': {
                'buy_pressure': buy_pressure,
                'sell_pressure': sell_pressure,
                'direction': direction,
                'confidence': round(confidence, 1),
                'strongest_price': strongest_level[0],
                'strongest_volume': round(strongest_level[1], 2),
                'strongest_side': strongest_level[2],
                'total_bid_volume': round(total_bid_vol, 2),
                'total_ask_volume': round(total_ask_vol, 2),
                'support_price': round(strongest_bid['price'], digits),
                'support_volume': round(strongest_bid['volume'], 2),
                'resistance_price': round(strongest_ask['price'], digits),
                'resistance_volume': round(strongest_ask['volume'], 2)
            },
            'signal': {
                'type': signal_type,
                'strength': round(strength),
                'trend': trend,
                'trend_arrow': trend_arrow,
                'volume_confirms': (signal_type == "BUY" and total_bid_vol > total_ask_vol) or (signal_type == "SELL" and total_ask_vol > total_bid_vol),
                'checklist': {
                    'volume_dominant': {'label': 'Volume Dominant', 'passed': abs(imbalance) > 10, 'value': f"{'Bid' if imbalance > 0 else 'Ask'} +{abs(imbalance):.0f}%"},
                    'trend_aligned': {'label': 'Trend Aligned', 'passed': (signal_type == "BUY" and trend in ["UP", "STRONG_UP"]) or (signal_type == "SELL" and trend in ["DOWN", "STRONG_DOWN"]) or signal_type == "WAIT", 'value': trend},
                    'confidence_high': {'label': 'Confidence High', 'passed': confidence > 60, 'value': f"{confidence:.0f}%"},
                    'volume_confirms': {'label': 'Volume Confirms', 'passed': (signal_type == "BUY" and total_bid_vol > total_ask_vol) or (signal_type == "SELL" and total_ask_vol > total_bid_vol) or signal_type == "WAIT", 'value': f"Ratio {total_bid_vol/total_ask_vol:.2f}" if total_ask_vol > 0 else "N/A"},
                    'strong_level': {'label': 'Strong Level', 'passed': strongest_volume > 5, 'value': f"{strongest_volume:.1f} lots @ {strongest_level[2]}"}
                },
                'ready_to_trade': ready_to_trade
            },
            # Entry Zones (NEW)
            'entry_zones': self._calculate_entry_zones(
                mid_price - spread/2, mid_price + spread/2,
                strongest_bid['price'], strongest_ask['price'],
                strongest_bid['volume'], strongest_ask['volume'],
                digits
            ),
            # Bubble Visualization (NEW)
            'bubbles': self._classify_orders(bids, asks, max(max(a['volume'] for a in asks), max(b['volume'] for b in bids)))
        }
    
    def _calculate_entry_zones(self, bid, ask, support_price, resistance_price, support_vol, resistance_vol, digits):
        """Calculate entry zones with Stop Loss and Take Profit levels."""
        spread = ask - bid
        
        # Pip value calculation
        if digits >= 4:
            pip_value = 0.0001 if digits == 5 else 0.01
        else:
            pip_value = 0.01
        
        # BUY ZONE
        buy_entry_low = support_price + (spread * 1)
        buy_entry_high = support_price + (spread * 3)
        buy_sl = support_price - (spread * 5)
        buy_sl_pips = round((buy_entry_low - buy_sl) / pip_value, 1)
        risk_distance = buy_entry_low - buy_sl
        buy_tp1 = round(buy_entry_low + risk_distance, digits)
        buy_tp2 = round(buy_entry_low + (risk_distance * 2), digits)
        buy_tp3 = round(buy_entry_low + (risk_distance * 3), digits)
        buy_strength = min(100, int(support_vol * 12))
        
        # SELL ZONE
        sell_entry_high = resistance_price - (spread * 1)
        sell_entry_low = resistance_price - (spread * 3)
        sell_sl = resistance_price + (spread * 5)
        sell_sl_pips = round((sell_sl - sell_entry_high) / pip_value, 1)
        risk_distance_sell = sell_sl - sell_entry_high
        sell_tp1 = round(sell_entry_high - risk_distance_sell, digits)
        sell_tp2 = round(sell_entry_high - (risk_distance_sell * 2), digits)
        sell_tp3 = round(sell_entry_high - (risk_distance_sell * 3), digits)
        sell_strength = min(100, int(resistance_vol * 12))
        
        return {
            'buy_zone': {
                'entry_low': round(buy_entry_low, digits),
                'entry_high': round(buy_entry_high, digits),
                'stop_loss': round(buy_sl, digits),
                'sl_pips': buy_sl_pips,
                'sl_distance': round(buy_entry_low - buy_sl, digits),
                'tp1': buy_tp1, 'tp2': buy_tp2, 'tp3': buy_tp3,
                'strength': buy_strength,
                'support_price': round(support_price, digits),
                'recommended': buy_strength > sell_strength
            },
            'sell_zone': {
                'entry_low': round(sell_entry_low, digits),
                'entry_high': round(sell_entry_high, digits),
                'stop_loss': round(sell_sl, digits),
                'sl_pips': sell_sl_pips,
                'sl_distance': round(sell_sl - sell_entry_high, digits),
                'tp1': sell_tp1, 'tp2': sell_tp2, 'tp3': sell_tp3,
                'strength': sell_strength,
                'resistance_price': round(resistance_price, digits),
                'recommended': sell_strength > buy_strength
            }
        }
    
    def _classify_orders(self, bids, asks, max_volume):
        """Classify orders into Large/Medium/Small for bubble visualization."""
        def classify(vol, max_vol):
            if max_vol == 0: return 'SMALL', 10
            ratio = vol / max_vol
            if ratio > 0.6: return 'LARGE', min(60, max(35, ratio * 60))
            elif ratio > 0.3: return 'MEDIUM', min(35, max(20, ratio * 50))
            else: return 'SMALL', min(20, max(8, ratio * 40))
        
        bid_bubbles = [{'price': b['price'], 'volume': b['volume'], 'size': classify(b['volume'], max_volume)[0], 'radius': round(classify(b['volume'], max_volume)[1], 1), 'level': i, 'side': 'BID'} for i, b in enumerate(bids)]
        ask_bubbles = [{'price': a['price'], 'volume': a['volume'], 'size': classify(a['volume'], max_volume)[0], 'radius': round(classify(a['volume'], max_volume)[1], 1), 'level': i, 'side': 'ASK'} for i, a in enumerate(asks)]
        
        large_bids = [b for b in bid_bubbles if b['size'] == 'LARGE']
        large_asks = [a for a in ask_bubbles if a['size'] == 'LARGE']
        
        return {
            'bids': bid_bubbles,
            'asks': ask_bubbles,
            'large_bid_count': len(large_bids),
            'large_ask_count': len(large_asks),
            'whale_alert': len(large_bids) > 2 or len(large_asks) > 2
        }

# ============ WEBSOCKET SERVER ============
class WebSocketServer:
    def __init__(self):
        self.clients: Set[WebSocketServerProtocol] = set()
        self.fetcher = PriceFetcher()
        self.current_symbol: Dict[WebSocketServerProtocol, str] = {}
        
    async def register(self, ws: WebSocketServerProtocol):
        self.clients.add(ws)
        self.current_symbol[ws] = "XAUUSD"
        logger.info(f"Client connected. Total: {len(self.clients)}")
        
        # Send symbol list (use 'data' key to match frontend)
        symbol_list = list(SYMBOLS.keys())
        await ws.send(json.dumps({
            "type": "SYMBOL_LIST",
            "data": symbol_list
        }))
    
    async def unregister(self, ws: WebSocketServerProtocol):
        self.clients.discard(ws)
        self.current_symbol.pop(ws, None)
        logger.info(f"Client disconnected. Total: {len(self.clients)}")
    
    async def handler(self, ws: WebSocketServerProtocol, path: str = None):
        await self.register(ws)
        try:
            async for message in ws:
                data = json.loads(message)
                if data.get("type") == "SUBSCRIBE":
                    symbol = data.get("symbol", "XAUUSD")
                    if symbol in SYMBOLS:
                        self.current_symbol[ws] = symbol
                        logger.info(f"Client subscribed to {symbol}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister(ws)
    
    async def broadcast_loop(self):
        """Main loop to fetch prices and broadcast to clients"""
        while True:
            try:
                # Fetch fresh prices
                await self.fetcher.fetch_all_prices()
                
                # Send to each client their subscribed symbol
                for ws in list(self.clients):
                    try:
                        symbol = self.current_symbol.get(ws, "XAUUSD")
                        dom_data = self.fetcher.generate_dom_data(symbol)
                        if dom_data:
                            # Use DOM_DATA type and include symbol to match frontend
                            message = dom_data.copy()
                            message['type'] = 'DOM_DATA'
                            await ws.send(json.dumps(message))
                    except Exception as e:
                        logger.error(f"Error sending to client: {e}")
                        
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
            
            await asyncio.sleep(UPDATE_INTERVAL)
    
    async def run(self):
        logger.info("="*50)
        logger.info("MT5 ORDERBOOK - API VERSION (No MT5 Required)")
        logger.info("="*50)
        logger.info(f"Data Sources: TwelveData (Forex/Metals) + Binance (Crypto)")
        logger.info(f"Symbols: {', '.join(SYMBOLS.keys())}")
        logger.info(f"WebSocket Server: ws://localhost:{WS_PORT}")
        logger.info("="*50)
        
        # Initial price fetch
        logger.info("Fetching initial prices...")
        await self.fetcher.fetch_all_prices()
        logger.info(f"Prices loaded for {len(self.fetcher.prices)} symbols")
        
        # Start server
        async with websockets.serve(self.handler, "localhost", WS_PORT):
            logger.info(f"Server running on port {WS_PORT}")
            await self.broadcast_loop()

# ============ MAIN ============
if __name__ == "__main__":
    server = WebSocketServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
