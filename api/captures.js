export default async function handler(req, res) {
  if (req.method !== 'GET' && req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  try {
    const origin = process.env.STATS_ORIGIN || 'http://127.0.0.1:8090';
    const { id, frame, embed, action } = req.query;

    let targetPath = '/captures';
    if (action === 'recognize') {
      targetPath = '/recognize';
    } else if (id && action === 'audit') {
      targetPath = `/captures/${encodeURIComponent(id)}/audit`;
    } else if (id && frame) {
      targetPath = `/captures?id=${encodeURIComponent(id)}&frame=${encodeURIComponent(frame)}`;
    } else if (id) {
      targetPath = `/captures?id=${encodeURIComponent(id)}`;
    }

    const fetchOptions = {
      method: req.method,
      signal: AbortSignal.timeout(10000),
    };
    if (req.method === 'POST') {
      fetchOptions.headers = { 'Content-Type': 'application/json' };
      fetchOptions.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
    } else {
      fetchOptions.cache = 'no-store';
    }

    const baseUrl = origin.endsWith('/') ? origin : `${origin}/`;
    const cleanTarget = targetPath.startsWith('/') ? targetPath.slice(1) : targetPath;
    const response = await fetch(new URL(cleanTarget, baseUrl), fetchOptions);
    if (!response.ok) {
      return res.status(response.status).json({ error: 'Capture resource unavailable' });
    }

    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('image/')) {
      const arrayBuffer = await response.arrayBuffer();
      res.setHeader('Content-Type', contentType);
      res.setHeader('Cache-Control', 'public, max-age=86400, immutable');
      return res.status(200).send(Buffer.from(arrayBuffer));
    }

    const data = await response.json();
    res.setHeader('Cache-Control', 'no-store, max-age=0');
    return res.status(200).json(data);
  } catch {
    res.setHeader('Cache-Control', 'no-store');
    return res.status(503).json({ error: 'Captures service temporarily unavailable' });
  }
}
