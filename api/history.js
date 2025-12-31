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
        const { symbol, limit = 100 } = req.query;

        if (!symbol) {
            return res.status(400).json({
                success: false,
                error: 'Symbol parameter is required'
            });
        }

        const query = `
      SELECT bid, ask, mid_price, timestamp 
      FROM price_history 
      WHERE symbol = ? 
      ORDER BY timestamp DESC 
      LIMIT ?
    `;

        const result = await db.execute({
            sql: query,
            args: [symbol, parseInt(limit)]
        });

        const history = result.rows.map(row => ({
            bid: parseFloat(row.bid),
            ask: parseFloat(row.ask),
            mid_price: parseFloat(row.mid_price),
            timestamp: row.timestamp
        }));

        res.status(200).json({
            success: true,
            symbol: symbol,
            data: history,
            count: history.length
        });

    } catch (error) {
        console.error('Database error:', error);
        res.status(500).json({
            success: false,
            error: 'Failed to fetch history',
            message: error.message
        });
    }
}
