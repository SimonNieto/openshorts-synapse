// Niches the user has actually used (research/download/regenerate), most
// recent first, so switching between a few regular niches is a click instead
// of retyping. Recorded only at the point of use, not on every keystroke, so
// half-typed text never pollutes it. Shared by App.jsx (Settings, download
// all) and ResultCard.jsx (regenerate copy, per-clip download) so a niche
// picked in one place shows up in every other picker too.
export const NICHE_HISTORY_KEY = 'openshorts_niche_history';
const NICHE_HISTORY_MAX = 8;

export function loadNicheHistory() {
    try {
        const raw = JSON.parse(localStorage.getItem(NICHE_HISTORY_KEY) || '[]');
        return Array.isArray(raw) ? raw.filter((n) => typeof n === 'string' && n.trim()) : [];
    } catch {
        return [];
    }
}

// Which Upload-Post profile (= which set of TikTok/IG/YouTube accounts) each
// niche posts to — one account per niche — so confirming a known niche on a
// new project preselects the right account.
const NICHE_PROFILES_KEY = 'openshorts_niche_profiles';

export function profileForNiche(niche) {
    const k = (niche || '').trim().toLowerCase();
    if (!k) return null;
    try {
        return (JSON.parse(localStorage.getItem(NICHE_PROFILES_KEY) || '{}') || {})[k] || null;
    } catch {
        return null;
    }
}

export function rememberNicheProfile(niche, profile) {
    const k = (niche || '').trim().toLowerCase();
    if (!k || !profile) return;
    try {
        const map = JSON.parse(localStorage.getItem(NICHE_PROFILES_KEY) || '{}') || {};
        map[k] = profile;
        localStorage.setItem(NICHE_PROFILES_KEY, JSON.stringify(map));
    } catch { /* storage full/blocked */ }
}

export function pushNicheHistory(niche) {
    const trimmed = (niche || '').trim();
    if (!trimmed) return loadNicheHistory();
    const next = [trimmed, ...loadNicheHistory().filter((n) => n.toLowerCase() !== trimmed.toLowerCase())]
        .slice(0, NICHE_HISTORY_MAX);
    try { localStorage.setItem(NICHE_HISTORY_KEY, JSON.stringify(next)); } catch { /* storage full/blocked */ }
    return next;
}
