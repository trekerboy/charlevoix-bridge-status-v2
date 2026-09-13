export default async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });
  try {
    const origin = process.env.STATS_ORIGIN || 'http://127.0.0.1:8090';
    const baseUrl = origin.endsWith('/') ? origin : `${origin}/`;
    const response = await fetch(new URL('live.jpg', baseUrl), {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) {
      return res.status(response.status).json({ error: 'Live frame unavailable' });
    }
    const contentType = response.headers.get('content-type') || 'image/jpeg';
    const arrayBuffer = await response.arrayBuffer();
    res.setHeader('Content-Type', contentType);
    res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0');
    return res.status(200).send(Buffer.from(arrayBuffer));
  } catch {
    res.setHeader('Cache-Control', 'no-store');
    return res.status(503).json({ error: 'Live camera stream temporarily unavailable' });
  }
}
