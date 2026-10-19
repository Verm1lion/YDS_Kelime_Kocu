// Rota jetonu: yavaş gelen bir yanıt, kullanıcı başka ekrana geçtiyse ekrana yazılmaz.
let seq = 0;
let activeStudy = null;

export function nextRoute() {
  // yeni ekrana geçerken açık çalışma oturumunu (zamanlayıcı, klavye dinleyicileri) kapat
  if (activeStudy) {
    try { activeStudy.cleanup(); } catch (e) { /* yok */ }
    activeStudy = null;
  }
  return ++seq;
}

export function currentRoute() { return seq; }
export function isCurrent(token) { return token === seq; }

export function setActiveStudy(s) { activeStudy = s; }
export function clearActiveStudy(s) { if (activeStudy === s) activeStudy = null; }
