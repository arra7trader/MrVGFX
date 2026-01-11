'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useSession } from 'next-auth/react';
import Link from 'next/link';
import { LockIcon, ChartIcon, SparklesIcon, ScaleIcon, SignalIcon, CircleStackIcon } from '@/components/PremiumIcons';
import { OrderBook, DOMPrediction, DOM_SYMBOLS, DOMSymbolId } from '@/types/dom';
import { analyzeOrderFlow, calculateOrderBookMetrics, createSmoothingState, SmoothingState } from '@/lib/dom-analysis';
import BookmapChart, { HeatmapDataPoint } from '@/components/dom/HeatmapBubble';
import TradeSetupPanel from '@/components/dom/TradeSetupPanel';
import { MLPrediction, fetchMLPrediction } from '@/types/ml-prediction';
import MLSettingsPanel, { PredictionSettings, DEFAULT_SETTINGS } from '@/components/dom/MLSettingsPanel';
import AccuracyTrackerPanel, { useAccuracyTracker } from '@/components/dom/AccuracyTracker';
import CVDIndicator from '@/components/dom/CVDIndicator';
import ImbalanceChart from '@/components/dom/ImbalanceChart';
import { useAlertSystem, AlertPanel, AlertToastContainer, AlertSettings, DEFAULT_ALERT_SETTINGS } from '@/components/dom/AlertSystem';

const ADMIN_EMAILS = ['apmexplore@gmail.com'];
const MAX_FLOW_HISTORY = 600; // Keep last 1 minute of data (100ms * 600)

// Order Book Component
function OrderBookVisualization({ orderBook, maxLevels = 15, statusMessage }: { orderBook: OrderBook | null; maxLevels?: number; statusMessage?: string }) {
    if (!orderBook) {
        return (
            <div className="h-full flex items-center justify-center text-[var(--text-muted)]">
                <div className="text-center">
                    <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                    <p className="text-sm font-mono text-blue-400">{statusMessage || 'Menghubungkan ke market...'}</p>
                </div>
            </div>
        );
    }

    const bids = orderBook.bids.slice(0, maxLevels);
    const asks = orderBook.asks.slice(0, maxLevels).reverse(); // Reverse for display

    return (
        <div className="grid grid-cols-2 gap-4 h-full">
            {/* Asks (Sell Orders) - Top */}
            <div className="col-span-2">
                <div className="text-xs text-[var(--text-muted)] mb-2 flex justify-between">
                    <span>SELL ORDERS (Asks)</span>
                    <span>Total: {orderBook.totalAskVolume.toFixed(4)}</span>
                </div>
                <div className="space-y-1">
                    {asks.map((level, i) => (
                        <div key={`ask-${i}`} className="flex items-center gap-2 text-sm">
                            <div className="w-24 text-right font-mono text-red-600">
                                {level.price.toFixed(2)}
                            </div>
                            <div className="flex-1 h-6 bg-[var(--bg-secondary)] rounded overflow-hidden relative">
                                <motion.div
                                    initial={{ width: 0 }}
                                    animate={{ width: `${level.percentage}%` }}
                                    className="absolute left-0 top-0 h-full bg-gradient-to-r from-red-500/30 to-red-500/60"
                                />
                                <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-[var(--text-secondary)] font-mono">
                                    {level.volume.toFixed(4)}
                                </span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Spread Indicator */}
            <div className="col-span-2 py-3 px-4 bg-[var(--bg-secondary)] rounded-xl flex items-center justify-between">
                <div className="text-center">
                    <span className="text-xs text-[var(--text-muted)]">Best Bid</span>
                    <p className="text-lg font-bold text-green-600">{orderBook.bids[0]?.price.toFixed(2) || '-'}</p>
                </div>
                <div className="text-center px-4">
                    <span className="text-xs text-[var(--text-muted)]">Spread</span>
                    <p className="text-lg font-bold text-[var(--text-primary)]">{orderBook.spread.toFixed(2)}</p>
                    <span className="text-xs text-[var(--text-muted)]">({orderBook.spreadPercent.toFixed(3)}%)</span>
                </div>
                <div className="text-center">
                    <span className="text-xs text-[var(--text-muted)]">Best Ask</span>
                    <p className="text-lg font-bold text-red-600">{orderBook.asks[0]?.price.toFixed(2) || '-'}</p>
                </div>
            </div>

            {/* Bids (Buy Orders) - Bottom */}
            <div className="col-span-2">
                <div className="text-xs text-[var(--text-muted)] mb-2 flex justify-between">
                    <span>BUY ORDERS (Bids)</span>
                    <span>Total: {orderBook.totalBidVolume.toFixed(4)}</span>
                </div>
                <div className="space-y-1">
                    {bids.map((level, i) => (
                        <div key={`bid-${i}`} className="flex items-center gap-2 text-sm">
                            <div className="w-24 text-right font-mono text-green-600">
                                {level.price.toFixed(2)}
                            </div>
                            <div className="flex-1 h-6 bg-[var(--bg-secondary)] rounded overflow-hidden relative">
                                <motion.div
                                    initial={{ width: 0 }}
                                    animate={{ width: `${level.percentage}%` }}
                                    className="absolute left-0 top-0 h-full bg-gradient-to-r from-green-500/30 to-green-500/60"
                                />
                                <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-[var(--text-secondary)] font-mono">
                                    {level.volume.toFixed(4)}
                                </span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

// Imbalance Meter Component
function ImbalanceMeter({ imbalance }: { imbalance: number }) {
    // Clamp to -100 to +100
    const value = Math.max(-100, Math.min(100, imbalance));
    const percentage = (value + 100) / 2; // Convert to 0-100 scale

    const getColor = () => {
        if (value > 30) return 'text-green-600';
        if (value < -30) return 'text-red-600';
        return 'text-amber-600';
    };

    const getLabel = () => {
        if (value > 50) return 'Strong Buyers';
        if (value > 20) return 'Buyers Active';
        if (value < -50) return 'Strong Sellers';
        if (value < -20) return 'Sellers Active';
        return 'Balanced';
    };

    return (
        <div className="bg-white rounded-2xl p-6 border border-[var(--border-light)]">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4 flex items-center gap-2">
                <span>⚖️</span> Order Imbalance
            </h3>

            {/* Gauge */}
            <div className="relative h-4 bg-[var(--bg-secondary)] rounded-full overflow-hidden mb-4">
                <div className="absolute inset-0 flex">
                    <div className="w-1/2 bg-gradient-to-r from-red-500 to-red-300 opacity-30" />
                    <div className="w-1/2 bg-gradient-to-r from-green-300 to-green-500 opacity-30" />
                </div>
                <motion.div
                    className="absolute top-0 w-3 h-full bg-[var(--text-primary)] rounded-full shadow-lg"
                    initial={{ left: '50%' }}
                    animate={{ left: `calc(${percentage}% - 6px)` }}
                    transition={{ type: 'spring', stiffness: 100 }}
                />
            </div>

            <div className="flex justify-between text-xs text-[var(--text-muted)] mb-4">
                <span>Sellers</span>
                <span>Neutral</span>
                <span>Buyers</span>
            </div>

            <div className="text-center">
                <p className={`text-2xl font-bold ${getColor()}`}>
                    {value > 0 ? '+' : ''}{value.toFixed(1)}%
                </p>
                <p className="text-sm text-[var(--text-secondary)]">{getLabel()}</p>
            </div>
        </div>
    );
}

// Prediction Panel Component
function PredictionPanel({ prediction }: { prediction: DOMPrediction | null }) {
    if (!prediction) {
        return (
            <div className="bg-white rounded-2xl p-6 border border-[var(--border-light)] h-full flex items-center justify-center">
                <p className="text-[var(--text-muted)]">Analyzing...</p>
            </div>
        );
    }

    const directionColors = {
        BULLISH: 'from-green-500 to-emerald-500',
        BEARISH: 'from-red-500 to-rose-500',
        NEUTRAL: 'from-amber-500 to-orange-500',
    };

    const directionIcons = {
        BULLISH: '📈',
        BEARISH: '📉',
        NEUTRAL: '➡️',
    };

    return (
        <div className="bg-white rounded-2xl p-6 border border-[var(--border-light)]">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4 flex items-center gap-2">
                <SparklesIcon size="sm" className="text-purple-500" />
                AI Prediction
            </h3>

            {/* Direction Badge */}
            <div className={`bg-gradient-to-r ${directionColors[prediction.direction]} rounded-xl p-4 text-white mb-4`}>
                <div className="flex items-center gap-3">
                    <span className="text-3xl">{directionIcons[prediction.direction]}</span>
                    <div>
                        <p className="text-lg font-bold">{prediction.direction}</p>
                        <p className="text-sm opacity-90">Strength: {prediction.strength.toFixed(0)}%</p>
                    </div>
                </div>
            </div>

            {/* Confidence & Whale Activity */}
            <div className="grid grid-cols-2 gap-3 mb-4">
                <div className="bg-[var(--bg-secondary)] rounded-xl p-3 text-center">
                    <p className="text-xs text-[var(--text-muted)]">Confidence</p>
                    <p className="text-lg font-bold text-[var(--text-primary)]">{prediction.confidence}%</p>
                </div>
                <div className="bg-[var(--bg-secondary)] rounded-xl p-3 text-center">
                    <p className="text-xs text-[var(--text-muted)]">Whale Activity</p>
                    <p className={`text-lg font-bold ${prediction.whaleActivity === 'HIGH' ? 'text-purple-600' :
                        prediction.whaleActivity === 'MEDIUM' ? 'text-blue-600' : 'text-gray-500'
                        }`}>
                        {prediction.whaleActivity === 'HIGH' ? '🐋 High' :
                            prediction.whaleActivity === 'MEDIUM' ? '🐬 Medium' : '🐟 Low'}
                    </p>
                </div>
            </div>

            {/* Recommendation */}
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-4">
                <p className="text-sm text-blue-800">{prediction.recommendation}</p>
            </div>

            {/* Signals */}
            {prediction.signals.length > 0 && (
                <div>
                    <p className="text-xs text-[var(--text-muted)] mb-2">Detected Signals</p>
                    <div className="space-y-2 max-h-32 overflow-y-auto">
                        {prediction.signals.slice(0, 5).map((signal, i) => (
                            <div key={i} className="text-xs p-2 bg-[var(--bg-secondary)] rounded-lg flex items-start gap-2">
                                <span className={`px-1.5 py-0.5 rounded text-white text-[10px] ${signal.level === 'HIGH' ? 'bg-red-500' :
                                    signal.level === 'MEDIUM' ? 'bg-amber-500' : 'bg-gray-400'
                                    }`}>
                                    {signal.level}
                                </span>
                                <span className="text-[var(--text-secondary)]">{signal.description}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

// Coming Soon Component (for non-admin users)
function ComingSoonView() {
    return (
        <div className="min-h-screen bg-[var(--bg-primary)] pt-20">
            <div className="container-apple section-padding">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="text-center mb-12"
                >
                    <span className="badge-apple mb-6 inline-flex">
                        🔮 Advanced Trading Tool
                    </span>
                    <h1 className="headline-lg mb-4">
                        DOM <span className="gradient-text">ARRA</span>
                    </h1>
                    <p className="body-lg max-w-2xl mx-auto">
                        Depth of Market visualization dengan AI-powered order flow analysis
                    </p>
                </motion.div>

                <motion.div
                    initial={{ opacity: 0, y: 30 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.1 }}
                    className="max-w-2xl mx-auto"
                >
                    <div className="relative bg-white rounded-3xl border border-[var(--border-light)] overflow-hidden">
                        <div className="absolute inset-0 bg-white/90 backdrop-blur-sm z-10 flex flex-col items-center justify-center">
                            <motion.div
                                initial={{ scale: 0 }}
                                animate={{ scale: 1 }}
                                transition={{ delay: 0.3, type: 'spring' }}
                                className="w-20 h-20 rounded-full bg-gradient-to-br from-blue-100 to-cyan-100 flex items-center justify-center mb-6"
                            >
                                <LockIcon className="text-[var(--accent-blue)]" size="xl" />
                            </motion.div>
                            <h2 className="text-2xl font-bold text-[var(--text-primary)] mb-2">Coming Soon</h2>
                            <p className="text-[var(--text-secondary)] mb-6 text-center px-8">
                                Fitur Bookmap ARRA7 sedang dalam pengembangan dan akan segera hadir
                            </p>
                            <div className="flex flex-wrap gap-3 justify-center">
                                <span className="px-4 py-2 rounded-full bg-[var(--bg-secondary)] text-sm text-[var(--text-secondary)]">
                                    📊 Order Flow Analysis
                                </span>
                                <span className="px-4 py-2 rounded-full bg-[var(--bg-secondary)] text-sm text-[var(--text-secondary)]">
                                    🔥 Liquidity Heatmap
                                </span>
                                <span className="px-4 py-2 rounded-full bg-[var(--bg-secondary)] text-sm text-[var(--text-secondary)]">
                                    🐋 Whale Detection
                                </span>
                            </div>
                        </div>

                        <div className="p-8 opacity-30 blur-sm">
                            <div className="h-64 bg-gradient-to-br from-gray-100 to-gray-200 rounded-2xl mb-4"></div>
                            <div className="grid grid-cols-3 gap-4">
                                <div className="h-20 bg-gray-100 rounded-xl"></div>
                                <div className="h-20 bg-gray-100 rounded-xl"></div>
                                <div className="h-20 bg-gray-100 rounded-xl"></div>
                            </div>
                        </div>
                    </div>
                </motion.div>

                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.3 }}
                    className="text-center mt-12"
                >
                    <p className="text-[var(--text-muted)] mb-4">Ingin notifikasi saat Bookmap ARRA7 tersedia?</p>
                    <Link href="https://t.me/arra7trader" target="_blank" rel="noopener noreferrer">
                        <button className="btn-primary">
                            Join Telegram untuk Update
                        </button>
                    </Link>
                </motion.div>

                <div className="text-center mt-8">
                    <Link href="/" className="text-[var(--accent-blue)] hover:underline">
                        ← Kembali ke Beranda
                    </Link>
                </div>
            </div>
        </div>
    );
}

import { AccessResult } from '@/lib/turso';

// Access Control Banner Component
function TrialBanner({ daysLeft }: { daysLeft: number }) {
    return (
        <div className="fixed bottom-6 right-6 z-50 animate-bounce-slow">
            <div className="bg-gradient-to-r from-amber-500 to-orange-600 text-white px-6 py-4 rounded-xl shadow-lg shadow-amber-500/20 flex items-center gap-4">
                <div className="p-2 bg-white/20 rounded-lg backdrop-blur-sm">
                    <SparklesIcon className="text-white" size="md" />
                </div>
                <div>
                    <h4 className="font-bold text-sm">Free Trial Active</h4>
                    <p className="text-xs opacity-90">Sisa waktu: {daysLeft} hari lagi</p>
                </div>
                <Link href="/pricing">
                    <button className="bg-white text-orange-600 px-4 py-2 rounded-lg text-xs font-bold hover:bg-orange-50 transition-colors">
                        Upgrade
                    </button>
                </Link>
            </div>
        </div>
    );
}

// Blocked View Component
function BlockedView({ reason }: { reason: string }) {
    const isExpired = reason === 'TRIAL_EXPIRED';

    return (
        <div className="min-h-screen bg-[var(--bg-primary)] pt-20 flex items-center justify-center">
            <div className="container-apple section-padding">
                <div className="max-w-2xl mx-auto text-center">
                    <motion.div
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        className="bg-white p-8 rounded-3xl border border-[var(--border-light)] shadow-xl"
                    >
                        <div className={`w-20 h-20 mx-auto rounded-full flex items-center justify-center mb-6 ${isExpired ? 'bg-red-100' : 'bg-gray-100'}`}>
                            <LockIcon className={isExpired ? 'text-red-500' : 'text-gray-500'} size="xl" />
                        </div>

                        <h1 className="headline-md mb-4">
                            {isExpired ? 'Masa Trial Berakhir' : 'Akses Terbatas'}
                        </h1>

                        <p className="body-lg text-[var(--text-secondary)] mb-8">
                            {isExpired
                                ? 'Masa trial 3 hari Anda telah habis. Upgrade ke akun PRO untuk melanjutkan akses ke Bookmap ARRA7 dan fitur premium lainnya.'
                                : 'Fitur Bookmap ARRA7 hanya tersedia untuk pengguna PRO dan VVIP.'}
                        </p>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
                            <div className="p-4 bg-[var(--bg-secondary)] rounded-xl text-left">
                                <h4 className="font-semibold mb-2 flex items-center gap-2">Basic</h4>
                                <ul className="text-sm space-y-2 text-[var(--text-muted)]">
                                    <li className="flex items-center gap-2">✅ Analisa Market Basic</li>
                                    <li className="flex items-center gap-2">❌ Bookmap ARRA7</li>
                                    <li className="flex items-center gap-2">❌ Whale Alerts</li>
                                </ul>
                            </div>
                            <div className="p-4 bg-blue-50 border border-blue-200 rounded-xl text-left">
                                <h4 className="font-semibold text-blue-900 mb-2 flex items-center gap-2">PRO <span className="text-xs bg-blue-200 text-blue-800 px-2 py-0.5 rounded-full">Recommended</span></h4>
                                <ul className="text-sm space-y-2 text-blue-800">
                                    <li className="flex items-center gap-2">✅ Analisa Market Premium</li>
                                    <li className="flex items-center gap-2">✅ Bookmap ARRA7 Unlimited</li>
                                    <li className="flex items-center gap-2">✅ Whale Alerts Real-time</li>
                                </ul>
                            </div>
                        </div>

                        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                            <Link href="/pricing">
                                <button className="btn-primary w-full sm:w-auto">
                                    Upgrade Sekarang
                                </button>
                            </Link>
                            <Link href="/">
                                <button className="btn-secondary w-full sm:w-auto">
                                    Kembali ke Beranda
                                </button>
                            </Link>
                        </div>
                    </motion.div>
                </div>
            </div>
        </div>
    );
}

// Client Component Props
interface DomArraClientProps {
    accessResult: AccessResult;
}

// Main DOM ARRA Client Component
export default function DomArraClient({ accessResult }: DomArraClientProps) {
    const { data: session, status } = useSession();
    const [selectedSymbol, setSelectedSymbol] = useState<DOMSymbolId>('BTCUSD');
    const [orderBook, setOrderBook] = useState<OrderBook | null>(null);
    const [statusMessage, setStatusMessage] = useState('Initializing...');

    // Check access immediately
    if (!accessResult.allowed) {
        return <BlockedView reason={accessResult.reason} />;
    }

    // ... rest of the component state

    const [prediction, setPrediction] = useState<DOMPrediction | null>(null);
    const [mlPrediction, setMLPrediction] = useState<MLPrediction | null>(null);
    const [mlLoading, setMLLoading] = useState(false);
    const [mlSettings, setMLSettings] = useState<PredictionSettings>(DEFAULT_SETTINGS);
    const [isConnected, setIsConnected] = useState(false);
    const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
    const [flowHistory, setFlowHistory] = useState<HeatmapDataPoint[]>([]);
    const [activeTab, setActiveTab] = useState<'orderbook' | 'heatmap'>('orderbook');
    const [heatmapTimeframe, setHeatmapTimeframe] = useState<1 | 5 | 15 | 30>(5); // Minutes
    const { stats: accuracyStats, pendingCount, trackPrediction, setGetCurrentPrice } = useAccuracyTracker(selectedSymbol);
    const [usePolling, setUsePolling] = useState(false); // Fallback mode for ISP blocks
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
    const currentSymbolRef = useRef<DOMSymbolId>(selectedSymbol);
    const wsFailCountRef = useRef(0); // Track consecutive failures
    const smoothingStateRef = useRef<SmoothingState>(createSmoothingState()); // Instance-based smoothing state

    const isAdmin = session?.user?.email && ADMIN_EMAILS.includes(session.user.email);
    const symbolConfig = DOM_SYMBOLS[selectedSymbol];

    // Alert system
    const [alertSettings, setAlertSettings] = useState<AlertSettings>(DEFAULT_ALERT_SETTINGS);
    const { alerts, activeAlerts, dismissAlert, clearAlerts } = useAlertSystem(
        orderBook,
        prediction,
        mlPrediction,
        alertSettings
    );

    // Set up price getter for accuracy verification
    useEffect(() => {
        // Pass a function that returns current price (not the price itself)
        setGetCurrentPrice(() => orderBookRef.current?.midPrice || 0);
    }, [setGetCurrentPrice]);

    // Update ref when symbol changes
    useEffect(() => {
        currentSymbolRef.current = selectedSymbol;
    }, [selectedSymbol]);

    // Unified Binance WebSocket connection for both symbols
    const connectBinanceStream = useCallback((symbol: DOMSymbolId) => {
        // Clear any pending reconnect
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = null;
        }

        // Close existing connection
        if (wsRef.current) {
            wsRef.current.close();
            wsRef.current = null;
        }

        // Get the binance symbol from config
        const binanceSymbol = DOM_SYMBOLS[symbol].binanceSymbol;
        if (!binanceSymbol) {
            console.error('No Binance symbol configured for', symbol);
            return;
        }

        console.log(`Connecting to Binance for ${symbol} (${binanceSymbol})...`);
        setStatusMessage('Connecting WS...');
        const wsUrl = `wss://stream.binance.com/ws/${binanceSymbol}@depth20@100ms`;
        const ws = new WebSocket(wsUrl);

        // Connection timeout - if no connection in 2 seconds, switch to polling
        // (Reduced from 5s to help users in blocked regions switch to proxy faster)
        const connectionTimeout = setTimeout(() => {
            if (!ws || ws.readyState !== WebSocket.OPEN) {
                console.log(`WebSocket connection timeout for ${symbol}, switching to polling...`);
                setStatusMessage('WS Timeout. Switching to Proxy...');
                ws.close();
                setUsePolling(true);
            }
        }, 2000);

        ws.onopen = () => {
            setStatusMessage('Connected (WS)');
            clearTimeout(connectionTimeout);
            console.log(`Binance WebSocket connected for ${symbol} (${binanceSymbol})`);
            setIsConnected(true);
            wsFailCountRef.current = 0; // Reset failure count on success
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                // Parse Binance depth data
                const bids = data.bids.map(([price, volume]: [string, string]) => ({
                    price: parseFloat(price),
                    volume: parseFloat(volume),
                }));

                const asks = data.asks.map(([price, volume]: [string, string]) => ({
                    price: parseFloat(price),
                    volume: parseFloat(volume),
                }));

                // Calculate order book metrics - use the symbol this connection was created for
                const newOrderBook = calculateOrderBookMetrics(bids, asks, symbol, 'REAL');
                setOrderBook(newOrderBook);
                setLastUpdate(new Date());

                // Analyze order flow with instance-based smoothing state
                const { prediction: newPrediction, updatedState } = analyzeOrderFlow(newOrderBook, smoothingStateRef.current);
                smoothingStateRef.current = updatedState;
                setPrediction(newPrediction);

                // Add to flow history
                setFlowHistory(prev => {
                    const newPoint: HeatmapDataPoint = {
                        timestamp: Date.now(),
                        orderBook: newOrderBook
                    };
                    const updated = [...prev, newPoint];
                    return updated.slice(-MAX_FLOW_HISTORY);
                });
            } catch (error) {
                console.error('Error parsing Binance data:', error);
            }
        };

        ws.onclose = () => {
            console.log('Binance WebSocket disconnected');
            setIsConnected(false);

            // Only reconnect if this is still the current symbol
            if (currentSymbolRef.current === symbol) {
                reconnectTimeoutRef.current = setTimeout(() => {
                    // Double-check the symbol hasn't changed
                    if (currentSymbolRef.current === symbol) {
                        connectBinanceStream(symbol);
                    }
                }, 5000);
            }
        };

        ws.onerror = (error) => {
            console.error('Binance WebSocket error:', error);
            setIsConnected(false);
            wsFailCountRef.current++;

            // For non-BTC symbols, switch to polling faster (1 failure instead of 2)
            const failThreshold = symbol === 'BTCUSD' ? 2 : 1;
            if (wsFailCountRef.current >= failThreshold) {
                console.log(`WebSocket blocked for ${symbol}, switching to proxy polling...`);
                setStatusMessage('WS Blocked. Switching to Proxy...');
                setUsePolling(true);
            }
        };

        wsRef.current = ws;
    }, []);

    // Proxy Polling Fallback (for ISP-blocked connections)
    const fetchViaProxy = useCallback(async (symbol: DOMSymbolId) => {
        try {
            if (orderBook === null) setStatusMessage('Connecting via Proxy...');
            const binanceSymbol = DOM_SYMBOLS[symbol].binanceSymbol;
            const response = await fetch(`/api/binance/depth?symbol=${binanceSymbol}&limit=20`);

            if (!response.ok) throw new Error('Proxy fetch failed');

            const data = await response.json();

            // Parse data (same format as WebSocket)
            const bids = data.bids.map(([price, volume]: [string, string]) => ({
                price: parseFloat(price),
                volume: parseFloat(volume),
            }));
            const asks = data.asks.map(([price, volume]: [string, string]) => ({
                price: parseFloat(price),
                volume: parseFloat(volume),
            }));

            const newOrderBook = calculateOrderBookMetrics(bids, asks, symbol, 'REAL');
            setOrderBook(newOrderBook);
            setLastUpdate(new Date());
            setIsConnected(true);
            setStatusMessage('Connected (Proxy)');

            const { prediction: newPrediction, updatedState } = analyzeOrderFlow(newOrderBook, smoothingStateRef.current);
            smoothingStateRef.current = updatedState;
            setPrediction(newPrediction);

            setFlowHistory(prev => {
                const newPoint: HeatmapDataPoint = {
                    timestamp: Date.now(),
                    orderBook: newOrderBook
                };
                const updated = [...prev, newPoint];
                return updated.slice(-MAX_FLOW_HISTORY);
            });
        } catch (error) {
            console.error('Proxy fetch error:', error);
            setStatusMessage('Proxy Error: ' + (error instanceof Error ? error.message : 'Unknown'));
            setIsConnected(false);
        }
    }, []);

    // Effect: Start polling when in fallback mode
    useEffect(() => {
        if (!usePolling) return;

        // Close WebSocket if still open
        if (wsRef.current) {
            wsRef.current.close();
            wsRef.current = null;
        }

        // Start polling every 500ms
        console.log('Starting proxy polling for', selectedSymbol);
        fetchViaProxy(selectedSymbol); // Initial fetch
        pollingIntervalRef.current = setInterval(() => {
            fetchViaProxy(selectedSymbol);
        }, 500);

        return () => {
            if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current);
                pollingIntervalRef.current = null;
            }
        };
    }, [usePolling, selectedSymbol, fetchViaProxy]);

    // Effect: Connect on symbol change
    useEffect(() => {
        if (usePolling) return;

        // Reset failure count on symbol change
        wsFailCountRef.current = 0;

        // Clear data when switching symbols
        setOrderBook(null);
        setPrediction(null);
        setFlowHistory([]);
        smoothingStateRef.current = createSmoothingState(); // Reset smoothing state

        // Connect to Binance for the selected symbol
        connectBinanceStream(selectedSymbol);

        return () => {
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
                reconnectTimeoutRef.current = null;
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, [selectedSymbol, usePolling, connectBinanceStream]);

    // Keep track of latest order book for interval-based prediction
    const orderBookRef = useRef<OrderBook | null>(null);
    useEffect(() => {
        orderBookRef.current = orderBook;
    }, [orderBook]);

    // Effect: Fetch ML predictions based on settings (Interval based)
    useEffect(() => {
        // ML predictions now available for ALL users (not just admin)
        const fetchPrediction = async () => {
            if (!orderBookRef.current) return;

            try {
                setMLLoading(true);
                const pred = await fetchMLPrediction(selectedSymbol, mlSettings.horizon, orderBookRef.current);
                setMLPrediction(pred);

                // Track for accuracy (all users contribute to learning)
                if (orderBookRef.current.midPrice) {
                    trackPrediction(pred, orderBookRef.current.midPrice);
                }
            } catch (error) {
                console.error('ML prediction error:', error);
            } finally {
                setMLLoading(false);
            }
        };

        // Initial fetch
        fetchPrediction();

        // Fetch based on settings interval
        const interval = setInterval(fetchPrediction, mlSettings.refreshInterval * 1000);

        return () => clearInterval(interval);
    }, [selectedSymbol, mlSettings.horizon, mlSettings.refreshInterval, trackPrediction]);

    // Loading state
    if (status === 'loading') {
        return (
            <div className="min-h-screen flex items-center justify-center bg-[var(--bg-primary)]">
                <div className="w-10 h-10 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    // Admin check removed, relying on accessResult
    // if (!isAdmin) { return <ComingSoonView />; }

    // Admin View - Full DOM
    return (
        <div className="min-h-screen bg-[var(--bg-primary)] pt-20 pb-12">
            {/* Floating Alert Toasts - Disabled by user request */}
            {/* <AlertToastContainer alerts={alerts} onDismiss={dismissAlert} /> */}

            {/* Trial Banner for BASIC users */}
            {accessResult.reason === 'TRIAL_ACTIVE' && accessResult.daysLeft !== undefined && (
                <TrialBanner daysLeft={accessResult.daysLeft} />
            )}

            <div className="max-w-7xl mx-auto px-4">
                {/* Header */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex items-center justify-between mb-6"
                >
                    <div>
                        <h1 className="text-2xl font-bold text-[var(--text-primary)] flex items-center gap-3">
                            <ChartIcon size="lg" className="text-blue-600" />
                            Bookmap ARRA7
                            <span className="text-xs px-2 py-1 bg-amber-100 text-amber-700 rounded-full">BETA</span>
                        </h1>
                        <p className="text-[var(--text-secondary)]">Real-time Depth of Market Analysis</p>
                    </div>
                    <div className="flex items-center gap-3">
                        {/* Connection Status */}
                        <div className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm ${isConnected ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                            }`}>
                            <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'} animate-pulse`} />
                            {isConnected ? 'Connected' : 'Disconnected'}
                        </div>
                        <Link href="/admin">
                            <button className="px-4 py-2 bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary)] border border-[var(--border-light)] rounded-lg text-sm text-[var(--text-primary)]">
                                ← Admin
                            </button>
                        </Link>
                    </div>
                </motion.div>

                {/* Symbol Selector */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.1 }}
                    className="flex gap-3 mb-6"
                >
                    {Object.entries(DOM_SYMBOLS).map(([key, config]) => (
                        <button
                            key={key}
                            onClick={() => setSelectedSymbol(key as DOMSymbolId)}
                            className={`flex items-center gap-2 px-4 py-3 rounded-xl font-medium transition-all ${selectedSymbol === key
                                ? 'bg-blue-600 text-white'
                                : 'bg-white border border-[var(--border-light)] text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]'
                                }`}
                        >
                            <span className="text-xl">{config.icon}</span>
                            <span>{config.id}</span>
                            <span className={`text-xs px-1.5 py-0.5 rounded ${config.dataSource === 'REAL'
                                ? 'bg-green-500/20 text-green-500'
                                : 'bg-amber-500/20 text-amber-500'
                                }`}>
                                {config.dataSource}
                            </span>
                        </button>
                    ))}
                </motion.div>

                {/* Tab Selector */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.15 }}
                    className="flex gap-2 mb-6"
                >
                    <button
                        onClick={() => setActiveTab('orderbook')}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'orderbook'
                            ? 'bg-blue-100 text-blue-700 border border-blue-300'
                            : 'bg-white border border-[var(--border-light)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
                            }`}
                    >
                        <CircleStackIcon size="sm" />
                        Order Book
                    </button>
                    <button
                        onClick={() => setActiveTab('heatmap')}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'heatmap'
                            ? 'bg-purple-100 text-purple-700 border border-purple-300'
                            : 'bg-white border border-[var(--border-light)] text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'
                            }`}
                    >
                        <ChartIcon size="sm" />
                        Heatmap & Flow
                    </button>
                </motion.div>

                {/* Main Grid - Conditional layout based on active tab */}
                {activeTab === 'heatmap' ? (
                    /* Full Width Heatmap Layout */
                    <div className="space-y-4">
                        {/* Timeframe Selector */}
                        <motion.div
                            initial={{ opacity: 0, y: -10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="flex items-center justify-between"
                        >
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-[var(--text-secondary)]">Timeframe:</span>
                                {([1, 5, 15, 30] as const).map((tf) => (
                                    <button
                                        key={tf}
                                        onClick={() => setHeatmapTimeframe(tf)}
                                        className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-all ${heatmapTimeframe === tf
                                            ? 'bg-blue-600 text-white shadow-md'
                                            : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
                                            }`}
                                    >
                                        {tf}m
                                    </button>
                                ))}
                            </div>
                            <div className="text-xs text-gray-400">
                                Showing last {heatmapTimeframe}m • {flowHistory.length} data points
                                {flowHistory.length > 0 && (
                                    <span className="ml-1">
                                        ({Math.round((Date.now() - flowHistory[0].timestamp) / 60000)}m collected)
                                    </span>
                                )}
                            </div>
                        </motion.div>

                        <motion.div
                            initial={{ opacity: 0, y: -10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: 0.1 }}
                        >
                            <BookmapChart
                                currentOrderBook={orderBook}
                                history={flowHistory}
                                mlPrediction={mlPrediction}
                                timeframe={heatmapTimeframe}
                            />
                        </motion.div>

                        {/* CVD and Imbalance Charts */}
                        <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: 0.2 }}
                            className="grid grid-cols-1 lg:grid-cols-2 gap-4"
                        >
                            <CVDIndicator
                                history={flowHistory}
                                currentOrderBook={orderBook}
                                height={180}
                            />
                            <ImbalanceChart
                                history={flowHistory}
                                height={180}
                            />
                        </motion.div>

                        {/* Sidebar panels in horizontal row below chart */}
                        <motion.div
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: 0.3 }}
                            className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4"
                        >
                            <ImbalanceMeter imbalance={orderBook?.imbalance || 0} />
                            <TradeSetupPanel prediction={mlPrediction} isLoading={mlLoading} />
                            <MLSettingsPanel settings={mlSettings} onSettingsChange={setMLSettings} />
                            <AccuracyTrackerPanel stats={accuracyStats} pendingCount={pendingCount} />
                            <AlertPanel alerts={alerts} onDismiss={dismissAlert} onClear={clearAlerts} />
                        </motion.div>
                    </div>
                ) : (
                    /* Original 3-column layout for Order Book */
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                        {/* Left Content - 2 columns */}
                        <motion.div
                            initial={{ opacity: 0, x: -20 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ delay: 0.2 }}
                            className="lg:col-span-2"
                        >
                            <div className="bg-white rounded-2xl p-6 border border-[var(--border-light)]">
                                <div className="flex items-center justify-between mb-4">
                                    <h2 className="text-lg font-semibold text-[var(--text-primary)] flex items-center gap-2">
                                        <CircleStackIcon size="md" className="text-blue-600" />
                                        Order Book - {symbolConfig.name}
                                    </h2>
                                    {lastUpdate && (
                                        <span className="text-xs text-[var(--text-muted)]">
                                            Last update: {lastUpdate.toLocaleTimeString()}
                                        </span>
                                    )}
                                </div>
                                <OrderBookVisualization orderBook={orderBook} statusMessage={statusMessage} />
                            </div>
                        </motion.div>

                        {/* Right Sidebar - Imbalance & Prediction */}
                        <motion.div
                            initial={{ opacity: 0, x: 20 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ delay: 0.3 }}
                            className="space-y-4"
                        >
                            <ImbalanceMeter imbalance={orderBook?.imbalance || 0} />
                            <TradeSetupPanel prediction={mlPrediction} isLoading={mlLoading} />
                            <MLSettingsPanel settings={mlSettings} onSettingsChange={setMLSettings} />
                            <AccuracyTrackerPanel stats={accuracyStats} pendingCount={pendingCount} />
                            <PredictionPanel prediction={prediction} />
                        </motion.div>
                    </div>
                )}

                {/* Stats Footer */}
                {orderBook && (
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.4 }}
                        className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-4"
                    >
                        <div className="bg-white rounded-xl p-4 border border-[var(--border-light)]">
                            <p className="text-xs text-[var(--text-muted)]">Mid Price</p>
                            <p className="text-xl font-bold text-[var(--text-primary)]">${orderBook.midPrice.toFixed(2)}</p>
                        </div>
                        <div className="bg-white rounded-xl p-4 border border-[var(--border-light)]">
                            <p className="text-xs text-[var(--text-muted)]">Total Bid Volume</p>
                            <p className="text-xl font-bold text-green-600">{orderBook.totalBidVolume.toFixed(4)}</p>
                        </div>
                        <div className="bg-white rounded-xl p-4 border border-[var(--border-light)]">
                            <p className="text-xs text-[var(--text-muted)]">Total Ask Volume</p>
                            <p className="text-xl font-bold text-red-600">{orderBook.totalAskVolume.toFixed(4)}</p>
                        </div>
                        <div className="bg-white rounded-xl p-4 border border-[var(--border-light)]">
                            <p className="text-xs text-[var(--text-muted)]">Data Source</p>
                            <p className={`text-xl font-bold ${orderBook.dataSource === 'REAL' ? 'text-green-600' : 'text-amber-600'}`}>
                                {orderBook.dataSource === 'REAL' ? '🔴 Live' : '🟡 Simulated'}
                            </p>
                        </div>
                    </motion.div>
                )}
            </div>
        </div>
    );
}
