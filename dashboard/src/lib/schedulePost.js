// What every "schedule on Upload-Post" screen shares (5-oct-2026: extracted from ScheduleComposer so the
// Line-up sends EXACTLY the same request): the remembered platforms/times, the project's niche + account,
// and the body of one POST /api/social/post. Behaviour unchanged for ScheduleComposer.
import { scheduledDateFor, userTimezone } from './postSlots';
import { profileForNiche } from './nicheHistory';

// Last-used platforms/slots, so a repeat session is: open, click, done.
export const SCHEDULE_PREFS_KEY = 'openshorts_schedule_prefs_v1';

export function loadSchedulePrefs() {
    try { return JSON.parse(localStorage.getItem(SCHEDULE_PREFS_KEY) || '{}') || {}; } catch { return {}; }
}

export function saveSchedulePrefs(p) {
    try { localStorage.setItem(SCHEDULE_PREFS_KEY, JSON.stringify(p)); } catch { /* ignore */ }
}

// The niche + account confirmed for a project (saved on it), else null: nothing is guessed.
export const savedNicheChoice = (project, fallbackProfile) => (project?.niche
    ? { niche: project.niche, profile: project.upload_profile || profileForNiche(project.niche) || fallbackProfile }
    : null);

// One clip → Upload-Post. No title/description: the server builds one caption per platform
// (niche-generator hashtags only). A slot with `now` (or no slot) → published right away.
export function socialPostBody({ jobId, clipIndex, uploadPostKey, profile, platforms, slot, niche, timezone = userTimezone() }) {
    return {
        job_id: jobId,
        clip_index: clipIndex,
        api_key: uploadPostKey,
        user_id: profile, // this niche's own accounts
        platforms,
        scheduled_date: scheduledDateFor(slot),
        timezone,
        niche: niche || null,
    };
}
