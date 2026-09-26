// Remembered between sessions: tick it once and every new video goes out.
export const AUTO_PUBLISH_KEY = 'os_auto_publish';

export function loadAutoPublish() {
    try {
        const saved = JSON.parse(localStorage.getItem(AUTO_PUBLISH_KEY) || '{}') || {};
        return {
            enabled: !!saved.enabled,
            profile: saved.profile || '',
            niche: saved.niche || '',
            platforms: Array.isArray(saved.platforms) && saved.platforms.length ? saved.platforms : ['tiktok', 'instagram', 'youtube'],
        };
    } catch {
        return { enabled: false, profile: '', niche: '', platforms: ['tiktok', 'instagram', 'youtube'] };
    }
}

export function saveAutoPublish(value) {
    try { localStorage.setItem(AUTO_PUBLISH_KEY, JSON.stringify(value)); } catch { /* ignore */ }
}
