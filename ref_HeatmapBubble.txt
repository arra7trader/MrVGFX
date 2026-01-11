'use client';

import { useRef, useEffect, useState } from 'react';
import { OrderBook, DOM_SYMBOLS, DOMSymbolId } from '@/types/dom';
import { MLPrediction, getPredictionColor } from '@/types/ml-prediction';

export interface HeatmapDataPoint {
    timestamp: number;
    orderBook: OrderBook;
}

interface HeatmapBubbleProps {
    currentOrderBook: OrderBook | null;
    history: HeatmapDataPoint[];
    height?: number;
    mlPrediction?: MLPrediction | null;
    timeframe?: 1 | 5 | 15 | 30; // Minutes to display
}

// Wall persistence tracking
interface TrackedWall {
    price: number;
    volume: number;
    type: 'ASK' | 'BID';
    firstSeen: number;
    lastSeen: number;
    sizeClass: 'MEGA' | 'LARGE' | 'MEDIUM' | 'SMALL';
}

// Classify order size
function classifyOrderSize(volume: number, avgVol: number): 'MEGA' | 'LARGE' | 'MEDIUM' | 'SMALL' {
    if (volume > avgVol * 10) return 'MEGA';
    if (volume > avgVol * 5) return 'LARGE';
    if (volume > avgVol * 2) return 'MEDIUM';
    return 'SMALL';
}

// Get size icon
function getSizeIcon(sizeClass: 'MEGA' | 'LARGE' | 'MEDIUM' | 'SMALL'): string {
    switch (sizeClass) {
        case 'MEGA': return '🐋';
        case 'LARGE': return '🦈';
        case 'MEDIUM': return '📦';
        case 'SMALL': return '';
    }
}

// Turbo Colormap (Approximation)
function getHeatmapColor(intensity: number, alpha: number = 1): string {
    const t = Math.max(0, Math.min(1, intensity));
    let r = 0, g = 0, b = 0;

    if (t < 0.25) {
        const p = t / 0.25;
        r = 0;
        g = Math.floor(p * 255);
        b = Math.floor(150 + p * 105);
    } else if (t < 0.5) {
        const p = (t - 0.25) / 0.25;
        r = 0;
        g = 255;
        b = Math.floor(255 * (1 - p));
    } else if (t < 0.75) {
        const p = (t - 0.5) / 0.25;
        r = Math.floor(p * 255);
        g = 255;
        b = 0;
    } else {
        const p = (t - 0.75) / 0.25;
        r = 255;
        g = Math.floor(255 * (1 - p));
        b = 0;
        if (t > 0.95) { r = 255; g = 255; b = 255; }
    }

    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// Helper: Calculate statistics for auto-scaling
function getVolumeStats(history: HeatmapDataPoint[], currentBook: OrderBook | null) {
    let maxVol = 0;
    let totalVol = 0;
    let count = 0;

    const processLevels = (levels: any[]) => {
        levels.forEach(l => {
            maxVol = Math.max(maxVol, l.volume);
            totalVol += l.volume;
            count++;
        });
    };

    if (currentBook) {
        processLevels(currentBook.bids);
        processLevels(currentBook.asks);
    }

    const recent = history.slice(-100);
    recent.forEach(h => {
        processLevels(h.orderBook.bids);
        processLevels(h.orderBook.asks);
    });

    const avgVol = count > 0 ? totalVol / count : 1;
    const ceiling = Math.min(maxVol, avgVol * 8);

    return { max: Math.max(ceiling, 0.0001), avg: avgVol };
}

// Helper: Get Price Range
function getPriceRange(history: HeatmapDataPoint[], currentBook: OrderBook | null) {
    let minPrice = Infinity;
    let maxPrice = -Infinity;

    if (currentBook) {
        if (currentBook.bids.length > 0) minPrice = Math.min(minPrice, currentBook.bids[currentBook.bids.length - 1].price);
        if (currentBook.asks.length > 0) maxPrice = Math.max(maxPrice, currentBook.asks[currentBook.asks.length - 1].price);
    }

    const recent = history.slice(-150);
    recent.forEach(h => {
        const book = h.orderBook;
        if (book.bids.length > 0) {
            minPrice = Math.min(minPrice, book.bids[book.bids.length - 1].price);
        }
        if (book.asks.length > 0) {
            maxPrice = Math.max(maxPrice, book.asks[book.asks.length - 1].price);
        }
    });

    // Fallback
    if (minPrice === Infinity || maxPrice === -Infinity) {
        const mid = currentBook?.midPrice || 100;
        minPrice = mid * 0.98;
        maxPrice = mid * 1.02;
    }

    // Add padding
    const span = maxPrice - minPrice;
    return { min: minPrice - span * 0.05, max: maxPrice + span * 0.05 };
}

// Helper: Calculate Volume Profile (aggregate volume per price bucket)
function calculateVolumeProfile(history: HeatmapDataPoint[], currentBook: OrderBook | null, priceRange: { min: number; max: number }, numBuckets: number = 40) {
    const buckets: number[] = new Array(numBuckets).fill(0);
    const priceSpan = priceRange.max - priceRange.min;
    const bucketSize = priceSpan / numBuckets;

    const addToBucket = (price: number, volume: number) => {
        const bucketIndex = Math.floor((price - priceRange.min) / bucketSize);
        if (bucketIndex >= 0 && bucketIndex < numBuckets) {
            buckets[bucketIndex] += volume;
        }
    };

    // Current order book
    if (currentBook) {
        currentBook.bids.forEach(b => addToBucket(b.price, b.volume));
        currentBook.asks.forEach(a => addToBucket(a.price, a.volume));
    }

    // Historical data (last 50 points)
    const recent = history.slice(-50);
    recent.forEach(h => {
        h.orderBook.bids.forEach(b => addToBucket(b.price, b.volume * 0.5)); // Weight historical less
        h.orderBook.asks.forEach(a => addToBucket(a.price, a.volume * 0.5));
    });

    const maxBucket = Math.max(...buckets, 1);
    return { buckets, maxBucket, bucketSize };
}

export default function BookmapChart({ currentOrderBook, history, mlPrediction, timeframe = 5 }: HeatmapBubbleProps) {
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const containerRef = useRef<HTMLDivElement | null>(null);
    const [dimensions, setDimensions] = useState({ width: 1200, height: 500 });

    // Wall persistence tracking - stores walls with their first/last seen timestamps
    const wallHistoryRef = useRef<Map<string, TrackedWall>>(new Map());

    // Resize handler
    useEffect(() => {
        const updateSize = () => {
            if (containerRef.current) {
                const { width } = containerRef.current.getBoundingClientRect();
                setDimensions({ width, height: 500 });
            }
        };

        updateSize();
        window.addEventListener('resize', updateSize);
        return () => window.removeEventListener('resize', updateSize);
    }, []);

    // Main drawing effect
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas || !currentOrderBook) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const symbolConfig = DOM_SYMBOLS[currentOrderBook.symbol as DOMSymbolId];
        const priceDecimals = symbolConfig?.decimals || 2;
        const volDecimals = symbolConfig?.volumeDecimals ?? 2;
        const { width, height } = dimensions;

        // === LAYOUT ===
        const VOLUME_PROFILE_WIDTH = 100; // NEW: Volume profile bar on right
        const PRICE_AXIS_WIDTH = 80;
        const RIGHT_MARGIN = VOLUME_PROFILE_WIDTH + PRICE_AXIS_WIDTH;
        const BOTTOM_MARGIN = 28;
        const FUTURE_WIDTH = 320; // Widened future zone
        const CHART_WIDTH = width - RIGHT_MARGIN;
        const HISTORY_WIDTH = CHART_WIDTH - FUTURE_WIDTH;
        const CHART_HEIGHT = height - BOTTOM_MARGIN;

        // === STATS & SCALE ===
        // Filter history based on timeframe (1m, 5m, 15m, 30m)
        const timeframeMsMap = { 1: 60000, 5: 300000, 15: 900000, 30: 1800000 };
        const cutoffTime = Date.now() - (timeframeMsMap[timeframe] || 300000);
        const filteredHistory = history.filter(h => h.timestamp >= cutoffTime);

        const { max: maxVol, avg: avgVol } = getVolumeStats(filteredHistory, currentOrderBook);
        const priceRange = getPriceRange(filteredHistory, currentOrderBook);
        const priceSpan = priceRange.max - priceRange.min;
        const getY = (price: number) => CHART_HEIGHT - ((price - priceRange.min) / priceSpan) * CHART_HEIGHT;

        // === VOLUME PROFILE ===
        const volumeProfile = calculateVolumeProfile(filteredHistory, currentOrderBook, priceRange, 40);

        // === 1. BACKGROUND ===
        ctx.fillStyle = '#0a0f1a'; // Darker background
        ctx.fillRect(0, 0, width, height);

        // Grid lines (subtle)
        ctx.strokeStyle = '#1e293b';
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= 10; i++) {
            const y = (CHART_HEIGHT / 10) * i;
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(CHART_WIDTH, y);
            ctx.stroke();
        }

        // === 2. HEATMAP (History) ===
        const pointsToDraw = filteredHistory.slice(-Math.floor(HISTORY_WIDTH / 2));
        const pointWidth = Math.max(2, HISTORY_WIDTH / Math.max(pointsToDraw.length, 1));

        pointsToDraw.forEach((point, i) => {
            const x = i * pointWidth;

            // Asks (above mid)
            point.orderBook.asks.forEach(ask => {
                if (ask.volume < avgVol * 0.1) return;
                const y = getY(ask.price);
                const intensity = ask.volume / maxVol;
                ctx.fillStyle = getHeatmapColor(intensity);
                ctx.fillRect(x, y, Math.ceil(pointWidth), 3);
            });

            // Bids (below mid)
            point.orderBook.bids.forEach(bid => {
                if (bid.volume < avgVol * 0.1) return;
                const y = getY(bid.price);
                const intensity = bid.volume / maxVol;
                ctx.fillStyle = getHeatmapColor(intensity);
                ctx.fillRect(x, y, Math.ceil(pointWidth), 3);
            });
        });

        // === 3. PRICE LINE (Enhanced - Candlestick style) ===
        const historyEndX = pointsToDraw.length * pointWidth;
        const currentY = getY(currentOrderBook.midPrice);

        // Price path with glow
        ctx.shadowBlur = 8;
        ctx.shadowColor = '#3b82f6';
        ctx.beginPath();
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#ffffff';

        if (pointsToDraw.length > 0) {
            ctx.moveTo(0, getY(pointsToDraw[0].orderBook.midPrice));
            pointsToDraw.forEach((p, i) => {
                ctx.lineTo(i * pointWidth, getY(p.orderBook.midPrice));
            });
        }
        ctx.lineTo(historyEndX, currentY);
        ctx.stroke();
        ctx.shadowBlur = 0;

        // === 4. FUTURE ZONE ===
        const futureX = historyEndX;

        // Separator line
        ctx.beginPath();
        ctx.setLineDash([4, 6]);
        ctx.strokeStyle = '#475569';
        ctx.lineWidth = 2;
        ctx.moveTo(futureX, 0);
        ctx.lineTo(futureX, CHART_HEIGHT);
        ctx.stroke();
        ctx.setLineDash([]);

        // "FUTURE" label
        ctx.fillStyle = '#64748b';
        ctx.font = 'bold 10px Inter, sans-serif';
        ctx.fillText('▶ FUTURE ORDERS', futureX + 10, 16);

        // Current price extends into future
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([8, 4]);
        ctx.beginPath();
        ctx.moveTo(futureX, currentY);
        ctx.lineTo(CHART_WIDTH, currentY);
        ctx.stroke();
        ctx.setLineDash([]);

        // Draw depth bars in future zone
        const drawFutureBar = (price: number, volume: number, type: 'ASK' | 'BID') => {
            const y = getY(price);
            const intensity = volume / maxVol;
            const barWidth = Math.min(FUTURE_WIDTH * intensity * 2, FUTURE_WIDTH - 20);
            const color = type === 'ASK' ? 'rgba(239, 68, 68, 0.7)' : 'rgba(34, 197, 94, 0.7)';

            // Gradient effect
            const gradient = ctx.createLinearGradient(futureX, 0, futureX + barWidth, 0);
            gradient.addColorStop(0, color);
            gradient.addColorStop(1, 'transparent');

            ctx.fillStyle = gradient;
            ctx.fillRect(futureX + 5, y - 2, barWidth, 4);
        };

        currentOrderBook.asks.forEach(a => drawFutureBar(a.price, a.volume, 'ASK'));
        currentOrderBook.bids.forEach(b => drawFutureBar(b.price, b.volume, 'BID'));

        // === 5. WHALE WALLS with Persistence Tracking ===
        const whaleThreshold = Math.max(avgVol * 2, maxVol * 0.4);
        const now = Date.now();
        const wallHistory = wallHistoryRef.current;

        // Update wall history with current orders
        const updateWallHistory = (price: number, volume: number, type: 'ASK' | 'BID') => {
            if (volume < avgVol * 1.5) return; // Only track significant orders

            const key = `${type}-${price.toFixed(priceDecimals)}`;
            const existing = wallHistory.get(key);
            const sizeClass = classifyOrderSize(volume, avgVol);

            if (existing) {
                // Update existing wall
                existing.lastSeen = now;
                existing.volume = volume;
                existing.sizeClass = sizeClass;
            } else {
                // New wall
                wallHistory.set(key, {
                    price,
                    volume,
                    type,
                    firstSeen: now,
                    lastSeen: now,
                    sizeClass
                });
            }
        };

        // Track all current orders
        currentOrderBook.asks.forEach(a => updateWallHistory(a.price, a.volume, 'ASK'));
        currentOrderBook.bids.forEach(b => updateWallHistory(b.price, b.volume, 'BID'));

        // Clean up stale walls (not seen for 3 seconds)
        wallHistory.forEach((wall, key) => {
            if (now - wall.lastSeen > 3000) {
                wallHistory.delete(key);
            }
        });

        // Draw walls with persistence info
        const drawStickyWall = (price: number, volume: number, type: 'ASK' | 'BID') => {
            if (volume < whaleThreshold) return;

            const key = `${type}-${price.toFixed(priceDecimals)}`;
            const wallData = wallHistory.get(key);
            const ageMs = wallData ? now - wallData.firstSeen : 0;
            const ageSeconds = Math.floor(ageMs / 1000);
            const sizeClass = wallData?.sizeClass || classifyOrderSize(volume, avgVol);

            const y = getY(price);
            const baseColor = type === 'ASK' ? '#ef4444' : '#22c55e';

            // Opacity increases with age (more stable = more solid)
            const stabilityAlpha = Math.min(0.3 + (ageSeconds / 20) * 0.5, 0.8);
            const bgColor = type === 'ASK'
                ? `rgba(239, 68, 68, ${stabilityAlpha})`
                : `rgba(34, 197, 94, ${stabilityAlpha})`;

            // Horizontal zone highlight - thicker for older walls
            const zoneHeight = ageSeconds > 10 ? 20 : ageSeconds > 5 ? 16 : 12;
            ctx.fillStyle = bgColor;
            ctx.fillRect(futureX, y - zoneHeight / 2, FUTURE_WIDTH, zoneHeight);

            // Line - thicker for confirmed walls
            const lineWidth = ageSeconds > 15 ? 4 : ageSeconds > 5 ? 3 : 2;
            ctx.beginPath();
            ctx.strokeStyle = baseColor;
            ctx.lineWidth = lineWidth;
            ctx.setLineDash([]);
            ctx.moveTo(futureX, y);
            ctx.lineTo(CHART_WIDTH, y);
            ctx.stroke();

            // Build label with size icon and stability
            const sizeIcon = getSizeIcon(sizeClass);
            const dirIcon = type === 'ASK' ? '🔴' : '🟢';
            let labelText = `${dirIcon}${sizeIcon} ${volume.toFixed(volDecimals)}`;

            // Add stability badge
            if (ageSeconds >= 15) {
                labelText += ' ✅';
            } else if (ageSeconds >= 5) {
                labelText += ` (${ageSeconds}s)`;
            }

            ctx.font = 'bold 13px Inter, sans-serif';
            const textWidth = ctx.measureText(labelText).width;

            // Label background - gold border for confirmed
            ctx.fillStyle = '#0f172a';
            ctx.strokeStyle = ageSeconds >= 15 ? '#fbbf24' : baseColor;
            ctx.lineWidth = ageSeconds >= 15 ? 3 : 2;
            ctx.beginPath();
            ctx.roundRect(CHART_WIDTH - textWidth - 26, y - 14, textWidth + 22, 28, 6);
            ctx.fill();
            ctx.stroke();

            // Label text
            ctx.fillStyle = ageSeconds >= 15 ? '#fbbf24' : baseColor;
            ctx.fillText(labelText, CHART_WIDTH - textWidth - 16, y + 5);

            // Size class label above for MEGA/LARGE
            if (sizeClass === 'MEGA' || sizeClass === 'LARGE') {
                ctx.font = 'bold 9px Inter, sans-serif';
                ctx.fillStyle = '#94a3b8';
                const sizeLabel = sizeClass === 'MEGA' ? 'MEGA WALL' : 'LARGE WALL';
                ctx.fillText(sizeLabel, futureX + 10, y - zoneHeight / 2 - 4);
            }

            // Price tag
            ctx.font = 'bold 10px Inter, monospace';
            ctx.fillStyle = '#94a3b8';
            ctx.fillText(price.toFixed(priceDecimals), futureX + 10, y - 14);
        };

        currentOrderBook.asks.forEach(a => drawStickyWall(a.price, a.volume, 'ASK'));
        currentOrderBook.bids.forEach(b => drawStickyWall(b.price, b.volume, 'BID'));

        // === 6. ML PREDICTION OVERLAY ===
        if (mlPrediction && mlPrediction.confidence > 0.5) {
            const predColor = getPredictionColor(mlPrediction.direction);
            const isUp = mlPrediction.direction === 'UP';
            const isDown = mlPrediction.direction === 'DOWN';

            const priceChange = currentOrderBook.midPrice * 0.001 * (isUp ? 1 : isDown ? -1 : 0);
            const targetY = getY(currentOrderBook.midPrice + priceChange);

            ctx.shadowBlur = 15;
            ctx.shadowColor = predColor;

            ctx.beginPath();
            ctx.setLineDash([6, 4]);
            ctx.strokeStyle = predColor;
            ctx.lineWidth = 3;
            ctx.moveTo(futureX, currentY);
            ctx.bezierCurveTo(
                futureX + FUTURE_WIDTH * 0.4, currentY,
                futureX + FUTURE_WIDTH * 0.6, targetY,
                CHART_WIDTH - 20, targetY
            );
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.shadowBlur = 0;

            // Prediction badge
            const confPct = Math.round(mlPrediction.confidence * 100);
            ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';
            ctx.strokeStyle = predColor;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.roundRect(futureX + 10, 30, 120, 32, 8);
            ctx.fill();
            ctx.stroke();

            ctx.fillStyle = predColor;
            ctx.font = 'bold 14px Inter, sans-serif';
            ctx.fillText(`AI: ${confPct}% ${mlPrediction.direction}`, futureX + 20, 52);
        }

        // === 7. VOLUME PROFILE BAR (NEW - Right side histogram) ===
        const vpX = CHART_WIDTH;
        const vpWidth = VOLUME_PROFILE_WIDTH - 10;
        const bucketHeight = CHART_HEIGHT / volumeProfile.buckets.length;

        // Background
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(vpX, 0, VOLUME_PROFILE_WIDTH, CHART_HEIGHT);

        // Title
        ctx.fillStyle = '#64748b';
        ctx.font = 'bold 9px Inter, sans-serif';
        ctx.save();
        ctx.translate(vpX + 8, CHART_HEIGHT / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('VOLUME PROFILE', 0, 0);
        ctx.restore();

        // Draw histogram bars
        volumeProfile.buckets.forEach((vol, i) => {
            const barHeight = bucketHeight - 1;
            const barWidth = (vol / volumeProfile.maxBucket) * (vpWidth - 20);
            const y = CHART_HEIGHT - (i + 1) * bucketHeight;

            // Determine color based on position relative to current price
            const bucketMidPrice = priceRange.min + (i + 0.5) * volumeProfile.bucketSize;
            const isBid = bucketMidPrice < currentOrderBook.midPrice;

            const gradient = ctx.createLinearGradient(vpX + 15, 0, vpX + 15 + barWidth, 0);
            if (isBid) {
                gradient.addColorStop(0, 'rgba(34, 197, 94, 0.8)');
                gradient.addColorStop(1, 'rgba(34, 197, 94, 0.2)');
            } else {
                gradient.addColorStop(0, 'rgba(239, 68, 68, 0.8)');
                gradient.addColorStop(1, 'rgba(239, 68, 68, 0.2)');
            }

            ctx.fillStyle = gradient;
            ctx.fillRect(vpX + 15, y, barWidth, barHeight);

            // Highlight high volume areas
            if (vol > volumeProfile.maxBucket * 0.7) {
                ctx.fillStyle = '#ffffff';
                ctx.fillRect(vpX + 15 + barWidth - 3, y, 3, barHeight);
            }
        });

        // === 8. PRICE AXIS ===
        const priceAxisX = CHART_WIDTH + VOLUME_PROFILE_WIDTH;
        ctx.fillStyle = '#1e293b';
        ctx.fillRect(priceAxisX, 0, PRICE_AXIS_WIDTH, height);

        ctx.fillStyle = '#94a3b8';
        ctx.font = '10px Inter, monospace';
        const numTicks = 10;
        for (let i = 0; i <= numTicks; i++) {
            const price = priceRange.min + (priceSpan * i) / numTicks;
            const y = getY(price);

            if (Math.abs(y - currentY) > 20) {
                ctx.fillText(price.toFixed(priceDecimals), priceAxisX + 6, y + 3);
                ctx.fillStyle = '#334155';
                ctx.fillRect(priceAxisX, y, 4, 1);
                ctx.fillStyle = '#94a3b8';
            }
        }

        // Current price tag
        ctx.fillStyle = '#3b82f6';
        ctx.fillRect(priceAxisX, currentY - 12, PRICE_AXIS_WIDTH, 24);
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 12px Inter, monospace';
        ctx.fillText(currentOrderBook.midPrice.toFixed(priceDecimals), priceAxisX + 6, currentY + 4);

        // === 9. TIME AXIS ===
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(0, CHART_HEIGHT, width, BOTTOM_MARGIN);

        ctx.fillStyle = '#64748b';
        ctx.font = '10px Inter, sans-serif';

        // "NOW" marker
        ctx.fillStyle = '#3b82f6';
        ctx.font = 'bold 11px Inter, sans-serif';
        ctx.fillText('◆ NOW', historyEndX - 20, CHART_HEIGHT + 18);

        // Time ticks
        ctx.fillStyle = '#64748b';
        ctx.font = '9px Inter, sans-serif';
        if (pointsToDraw.length > 20) {
            const tickInterval = Math.floor(pointsToDraw.length / 5);
            pointsToDraw.forEach((p, i) => {
                if (i % tickInterval === 0) {
                    const x = i * pointWidth;
                    const timeStr = new Date(p.timestamp).toLocaleTimeString('en-US', {
                        hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'
                    });
                    ctx.fillText(timeStr, x, CHART_HEIGHT + 18);
                }
            });
        }

    }, [dimensions, currentOrderBook, history, mlPrediction, timeframe]);

    if (!currentOrderBook) {
        return (
            <div className="h-[500px] w-full flex items-center justify-center bg-slate-900 border border-slate-800 rounded-xl text-slate-400">
                <div className="flex flex-col items-center gap-2">
                    <div className="w-8 h-8 rounded-full border-2 border-slate-600 border-t-blue-500 animate-spin" />
                    <span className="text-sm font-medium">Initializing Bookmap...</span>
                </div>
            </div>
        );
    }

    return (
        <div ref={containerRef} className="relative rounded-xl overflow-hidden border border-slate-800 shadow-2xl bg-slate-900">
            {/* Legend Overlay */}
            <div className="absolute top-3 left-3 flex gap-2 z-10">
                <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/90 border border-slate-700 backdrop-blur text-[10px] text-slate-300">
                    <div className="w-2.5 h-2.5 rounded-sm bg-blue-600"></div>
                    <span>Low Vol</span>
                </div>
                <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/90 border border-slate-700 backdrop-blur text-[10px] text-slate-300">
                    <div className="w-2.5 h-2.5 rounded-sm bg-yellow-500"></div>
                    <span>High Vol</span>
                </div>
                <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/90 border border-slate-700 backdrop-blur text-[10px] text-white font-bold">
                    <div className="w-2.5 h-2.5 rounded-sm bg-white shadow-[0_0_6px_white]"></div>
                    <span>Whale Wall</span>
                </div>
            </div>

            {/* Symbol Badge */}
            <div className="absolute top-3 right-[200px] z-10">
                <div className="px-3 py-1.5 rounded-lg bg-blue-600/90 border border-blue-500 text-white text-sm font-bold">
                    {currentOrderBook.symbol}
                </div>
            </div>

            <canvas
                ref={canvasRef}
                width={dimensions.width}
                height={dimensions.height}
                className="block"
            />
        </div>
    );
}
