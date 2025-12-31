import { createClient } from '@libsql/client';

const db = createClient({
    url: process.env.TURSO_DATABASE_URL,
    authToken: process.env.TURSO_AUTH_TOKEN,
});

export default async function handler(req, res) {
    // Enable CORS
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    try {
        if (req.method === 'GET') {
            // Get all settings
            const result = await db.execute('SELECT key, value FROM user_settings');

            const settings = {};
            result.rows.forEach(row => {
                settings[row.key] = row.value;
            });

            return res.status(200).json({
                success: true,
                data: settings
            });
        }

        if (req.method === 'POST') {
            // Update setting
            const { key, value } = req.body;

            if (!key || value === undefined) {
                return res.status(400).json({
                    success: false,
                    error: 'Key and value are required'
                });
            }

            await db.execute({
                sql: `
          INSERT INTO user_settings (key, value, updated_at) 
          VALUES (?, ?, datetime('now'))
          ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
        `,
                args: [key, String(value)]
            });

            return res.status(200).json({
                success: true,
                message: 'Setting updated'
            });
        }

        res.status(405).json({ error: 'Method not allowed' });

    } catch (error) {
        console.error('Database error:', error);
        res.status(500).json({
            success: false,
            error: 'Failed to process settings',
            message: error.message
        });
    }
}
