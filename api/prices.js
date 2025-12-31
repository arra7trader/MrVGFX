import { createClient } from '@libsql/client';

const db = createClient({
    url: process.env.TURSO_DATABASE_URL,
    authToken: process.env.TURSO_AUTH_TOKEN,
});

export default async function handler(req, res) {
    // Enable CORS
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    try {
        const { symbol } = req.query;

        let query;
        let args = [];

        if (symbol) {
            // Get latest price for specific symbol
            query = `
        SELECT symbol, bid, ask, mid_price, timestamp 
        FROM price_history 
        WHERE symbol = ? 
        ORDER BY timestamp DESC 
        LIMIT 1
      `;
            args = [symbol];
        } else {
            // Get latest price for all symbols
            query = `
        SELECT DISTINCT symbol, bid, ask, mid_price, timestamp 
        FROM price_history 
        WHERE timestamp = (
          SELECT MAX(timestamp) FROM price_history AS p2 
          WHERE p2.symbol = price_history.symbol
        )
        ORDER BY symbol
      `;
        }

        const result = await db.execute({ sql: query, args });

        const prices = result.rows.map(row => ({
            symbol: row.symbol,
            bid: parseFloat(row.bid),
            ask: parseFloat(row.ask),
            mid_price: parseFloat(row.mid_price),
            timestamp: row.timestamp
        }));

        res.status(200).json({
            success: true,
            data: prices,
            count: prices.length
        });

    } catch (error) {
        console.error('Database error:', error);
        res.status(500).json({
            success: false,
            error: 'Failed to fetch prices',
            message: error.message
        });
    }
}
