// Sunucu API sarmalayıcısı
export class ApiError extends Error {
  constructor(msg, status, data) { super(msg); this.status = status; this.data = data; }
}

let onNeedPin = null;
export function setPinHandler(fn) { onNeedPin = fn; }

export async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: {} };
  if (opts.body !== undefined) {
    if (opts.raw) { init.body = opts.body; }
    else { init.body = JSON.stringify(opts.body); init.headers['Content-Type'] = 'application/json'; }
  }
  let res;
  try {
    res = await fetch('/api' + path, init);
  } catch (e) {
    throw new ApiError('Sunucuya ulaşılamadı. Uygulama kapalı olabilir.', 0);
  }
  if (res.status === 401) {
    const d = await res.json().catch(() => ({}));
    if (d.need_pin && onNeedPin) onNeedPin();
    throw new ApiError(d.error || d.detail || 'Yetkisiz', 401, d);
  }
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError((data && (data.detail || data.error)) || ('HTTP ' + res.status), res.status, data);
  return data;
}

export const get = (p) => api(p);
export const post = (p, body = {}) => api(p, { method: 'POST', body });
export const put = (p, body = {}) => api(p, { method: 'PUT', body });
export const del = (p) => api(p, { method: 'DELETE' });
