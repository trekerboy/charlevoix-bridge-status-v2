export default async function handler(req, res) {
  if (req.method !== 'GET' && req.method !== 'HEAD') return res.status(405).json({ error: 'Method not allowed' });
  if (req.method === 'HEAD') {
    res.setHeader('Content-Type', 'application/json');
    return res.status(200).end();
  }
  try {
    const origin = process.env.STATS_ORIGIN || 'http://127.0.0.1:8090';
    const { date } = req.query;
    const target = date ? `/stats?date=${encodeURIComponent(date)}` : '/stats';
    const baseUrl = origin.endsWith('/') ? origin : `${origin}/`;
    const cleanTarget = target.startsWith('/') ? target.slice(1) : target;
    const response = await fetch(new URL(cleanTarget, baseUrl), {
      cache: 'no-store',
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error(`Backend error: ${response.status}`);
    const data = await response.json();
    if (data.is_historical) {
      res.setHeader('Cache-Control', 'public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800');
    } else {
      res.setHeader('Cache-Control', 'no-store, max-age=0');
    }
    return res.status(200).json(data);
  } catch (err) {
    res.setHeader('Cache-Control', 'no-store');
    return res.status(503).json({ error: 'Bridge telemetry temporarily unavailable' });
  }
}
