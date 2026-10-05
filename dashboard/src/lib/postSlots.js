// Posting-slot math shared by the schedule screen. Everything is in the
// user's LOCAL time: Upload-Post receives "YYYY-MM-DDTHH:MM:00" plus an IANA
// timezone, and the Publish Plan stores the same local date/time strings.

// Default times per cadence, spread over the day's usual engagement peaks.
// They are only starting points — the schedule screen lets each be edited.
export const CADENCE_TIMES = {
    1: ['18:00'],
    2: ['12:00', '19:00'],
    3: ['08:00', '12:00', '20:00'],
};

// The daily posting slots offered as one-click chips. Clips take them in the
// order they were clicked: 1st selected → 8h, 2nd → 12h, 3rd → 20h, then the
// next day again.
export const SLOT_OPTIONS = [
    { value: '08:00', label: '8h' },
    { value: '12:00', label: '12h' },
    { value: '20:00', label: '20h' },
];

// Too-close slots are skipped: Upload-Post needs a little lead time and a
// post "scheduled" two minutes from now reads as a mistake to the user.
export const MIN_LEAD_MS = 15 * 60 * 1000;

const pad = (n) => String(n).padStart(2, '0');

export function localDateStr(d) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function userTimezone() {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
        return 'UTC';
    }
}

/**
 * Status of each posting time on the day `offsetDays` from today, for one
 * account: 'free', 'taken' (that account already posts then) or 'passed'.
 */
export function slotStatusOn({ offsetDays = 0, times, occupied = new Set(), now = new Date() }) {
    const day = new Date(now);
    day.setHours(0, 0, 0, 0);
    day.setDate(day.getDate() + offsetDays);
    const out = {};
    for (const t of times) {
        const [h, m] = t.split(':').map(Number);
        const dt = new Date(day);
        dt.setHours(h, m, 0, 0);
        out[t] = occupied.has(`${localDateStr(dt)}T${t}`) ? 'taken'
            : dt.getTime() - now.getTime() < MIN_LEAD_MS ? 'passed' : 'free';
    }
    return out;
}

/**
 * The next `count` free slots. `postFirstNow`: the 1st clip goes out right
 * away (the explicit "now" choice) and the others take the next free slots
 * from today on. A time that has already passed is simply skipped.
 */
export function buildSlots({ count, times, startOffsetDays = 0, occupied = new Set(), now = new Date(), postFirstNow = false }) {
    if (postFirstNow && count > 0) {
        const hhmm = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
        return [{ date: localDateStr(now), time: hhmm, dt: new Date(now), now: true },
            ...buildSlots({ count: count - 1, times, startOffsetDays: 0, occupied, now })];
    }
    return buildFutureSlots({ count, times, startOffsetDays, occupied, now });
}

/**
 *  - times: 'HH:MM' strings for each posting slot of a day
 *  - startOffsetDays: 0 = today, 1 = tomorrow, …
 *  - occupied: Set of 'YYYY-MM-DDTHH:MM' already taken on this account, so a
 *    new batch continues after what's already scheduled instead of doubling up.
 */
function buildFutureSlots({ count, times, startOffsetDays = 0, occupied = new Set(), now = new Date() }) {
    const sortedTimes = [...new Set(times.filter(Boolean))].sort();
    const slots = [];
    if (!sortedTimes.length || count <= 0) return slots;

    const day = new Date(now);
    day.setHours(0, 0, 0, 0);
    day.setDate(day.getDate() + startOffsetDays);

    // Hard cap so an absurd input can never spin forever.
    for (let guard = 0; slots.length < count && guard < 400; guard++) {
        for (const t of sortedTimes) {
            const [h, m] = t.split(':').map(Number);
            const dt = new Date(day);
            dt.setHours(h, m, 0, 0);
            const key = `${localDateStr(dt)}T${t}`;
            // Taken on this account, or already passed: skip. Posting right
            // away is the explicit "now" choice (postFirstNow), never implied.
            if (occupied.has(key) || dt.getTime() - now.getTime() < MIN_LEAD_MS) continue;
            slots.push({ date: localDateStr(dt), time: t, dt });
            if (slots.length === count) break;
        }
        day.setDate(day.getDate() + 1);
    }
    return slots;
}

// What Upload-Post gets: no scheduled_date at all = publish immediately.
export function scheduledDateFor(slot) {
    return slot && !slot.now ? `${slot.date}T${slot.time}:00` : null;
}

export function slotLabel(slot) {
    if (slot.now) return 'now';
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const d = new Date(slot.dt);
    d.setHours(0, 0, 0, 0);
    const diff = Math.round((d - today) / 86400000);
    const day = diff === 0 ? 'today' : diff === 1 ? 'tomorrow'
        : slot.dt.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
    return `${day} · ${slot.time}`;
}
