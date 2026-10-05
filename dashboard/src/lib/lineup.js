// The Line-up's pure helpers (5-oct-2026): ranking, labels and slot maths, kept out of the components so
// they read as plain rules. Data shape: GET /api/lineup (contract C2 of output/_lineup/BRIEF.md).
import { buildSlots, localDateStr, MIN_LEAD_MS } from './postSlots';

// The one number that separates the shorts that take off (output/_stepup/donnees/rapport.md, 4-oct-2026):
// "Stayed to watch" ≥ 63 % → 5 shorts out of 8 got a second wave; below → 1 out of 15.
export const STAYED_LINE = 63;
// The spectator's progress is read this often while it watches.
export const JURY_POLL_MS = 2000;
// The app speaks English: its dates too ("Wed 7 Oct"), whatever the browser's language.
export const DATE_LOCALE = 'en-GB';
// The default platforms of a new schedule, as in ScheduleComposer.
export const DEFAULT_PLATFORMS = ['tiktok', 'instagram', 'youtube'];

export const clipKey = (c) => `${c.job_id}:${c.clip_index}`;

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

// The spectator's score (contract C1 `score`), null when the clip was never tested or the test is stale.
export const spectatorScore = (c) => num(c?.jury?.score);

// The real "Stayed to watch" of a published clip, null when YouTube Studio's number isn't in yet.
export const realStayed = (c) => (c?.status === 'published' ? num(c?.stats?.stayed) : null);

// The ranking: the spectator's score first; on a tie, its head-to-head score, then the AI's score.
// Clips not tested yet come last, in the AI's order.
export function compareBySpectator(a, b) {
  const sa = spectatorScore(a);
  const sb = spectatorScore(b);
  if (sa === null && sb !== null) return 1;
  if (sb === null && sa !== null) return -1;
  if (sa !== sb) return sb - sa;
  const ra = num(a?.jury?.rank_check?.rank_score) ?? -1;
  const rb = num(b?.jury?.rank_check?.rank_score) ?? -1;
  if (ra !== rb) return rb - ra;
  return (num(b.ai_score) ?? -1) - (num(a.ai_score) ?? -1);
}

// The AI's own selection score (predicted_score), the ranking while the spectator is off (5-oct-2026).
export const aiScore = (c) => num(c?.ai_score);

export function compareByAi(a, b) {
  const sa = aiScore(a);
  const sb = aiScore(b);
  if (sa === null && sb !== null) return 1;
  if (sb === null && sa !== null) return -1;
  return (sb ?? 0) - (sa ?? 0);
}

// Published clips rank on what really happened: "Stayed to watch", then the spectator, then the AI.
export function compareByStayed(a, b) {
  const sa = realStayed(a);
  const sb = realStayed(b);
  if (sa === null && sb !== null) return 1;
  if (sb === null && sa !== null) return -1;
  return ((sb ?? 0) - (sa ?? 0)) || compareBySpectator(a, b);
}

// Where a clip's headline number comes from, said honestly (5-oct-2026). The engine sends
// `rank_score_source` ("jury" | "ai" | "stayed") on each clip; without it, the same rule here: the real
// "Stayed to watch" once published and measured, else the spectator's score (when on and tested), else the
// AI's pick score.
export const SCORE_SOURCES = {
  stayed: 'Stayed to watch',
  jury: 'Spectator score',
  ai: 'AI pick score',
};

export function scoreSource(c, spectatorOn) {
  const sent = c?.rank_score_source;
  if (sent === 'stayed' && realStayed(c) !== null) return 'stayed';
  if (sent === 'jury' && spectatorOn && spectatorScore(c) !== null) return 'jury';
  if (sent === 'ai') return 'ai';
  if (realStayed(c) !== null) return 'stayed';
  if (spectatorOn && spectatorScore(c) !== null) return 'jury';
  return 'ai';
}

export const scoreValue = (c, source) => (source === 'stayed' ? realStayed(c) : source === 'jury' ? spectatorScore(c) : aiScore(c));

export const SORTS = [
  { value: 'best', label: 'Best first' },
  { value: 'newest', label: 'Newest' },
];

// "Best first" never mixes scales. Groups, in this order:
//  - tested: still to publish, ranked by the spectator (only when it is on);
//  - todo:   still to publish, by the AI's pick score (with the spectator on: the ones it hasn't watched);
//  - done:   published, by their real "Stayed to watch".
export function groupOf(c, spectatorOn) {
  if (c.status === 'published') return 'done';
  return spectatorOn && !isUntested(c) ? 'tested' : 'todo';
}

export const GROUP_ORDER = ['tested', 'todo', 'done'];

// `projectTime`: job_id → when the project was made (seconds), from /api/local-projects.
export function sortClips(clips, sort, projectTime = {}, spectatorOn = false) {
  const list = [...clips];
  if (sort === 'newest') {
    return list.sort((a, b) => ((projectTime[b.job_id] || 0) - (projectTime[a.job_id] || 0)) || (a.clip_index - b.clip_index));
  }
  const cmp = { tested: compareBySpectator, todo: compareByAi, done: compareByStayed };
  return GROUP_ORDER.flatMap((g) => list.filter((c) => groupOf(c, spectatorOn) === g).sort(cmp[g]));
}

// Rank = position within its group, counting only clips that HAVE the group's number.
export function ranksOf(clips, spectatorOn = false) {
  const out = {};
  const n = { tested: 0, todo: 0, done: 0 };
  for (const c of clips) {
    const g = groupOf(c, spectatorOn);
    const value = g === 'tested' ? spectatorScore(c) : g === 'done' ? realStayed(c) : aiScore(c);
    if (value === null) continue;
    n[g] += 1;
    out[clipKey(c)] = n[g];
  }
  return out;
}

// Where a clip stands, as the filter reads it: free, on Upload-Post for THIS week, queued after it, out.
export const STATES = [
  { value: 'all', label: 'All' },
  { value: 'available', label: 'Available' },
  { value: 'week', label: 'This week' },
  { value: 'later', label: 'Later' },
  { value: 'published', label: 'Published' },
];

export function stateOf(c, weekTo) {
  if (c.status === 'published') return 'published';
  if (c.status !== 'scheduled') return 'available';
  const first = (c.slots || []).map((s) => s.date).filter(Boolean).sort()[0];
  return first && weekTo && first > weekTo ? 'later' : 'week';
}

export const STATUS_LABEL = { available: 'Available', scheduled: 'Scheduled', published: 'Published' };

export const TITLE_FORMS = { question: 'Question', why: 'Why…', how: 'How…', statement: 'Statement' };
export const titleFormLabel = (f) => TITLE_FORMS[f] || (f ? String(f) : 'Unknown');

// "#2553 · Andrew Huberman" — the show is long and the same for most clips; it goes in the tooltip.
export function episodeShort(c) {
  return [c.episode, c.guest].filter(Boolean).join(' · ') || c.show || '';
}

export function episodeFull(c) {
  return [c.show, c.episode].filter(Boolean).join(' ') + (c.guest ? ` — ${c.guest}` : '');
}

// The episodes present, for the filter: [{ key, label, count }], most clips first.
export function episodesOf(clips) {
  const by = new Map();
  for (const c of clips) {
    const key = c.episode_key || '';
    if (!key) continue;
    if (!by.has(key)) by.set(key, { key, label: episodeFull(c), short: episodeShort(c), count: 0 });
    by.get(key).count += 1;
  }
  return [...by.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

export function fmtDuration(sec) {
  const s = num(sec);
  if (s === null) return '';
  const r = Math.round(s);
  return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, '0')}`;
}

export function fmtPct(v) {
  const n = num(v);
  if (n === null) return '';
  return `${Number.isInteger(n) ? n : n.toFixed(1)}%`;
}

// "Tue 6 Oct" from "2026-10-06" (a local calendar day, no timezone shift).
export function fmtDay(date, opts = { weekday: 'short', day: 'numeric', month: 'short' }) {
  if (!date) return '';
  return new Date(`${date}T00:00:00`).toLocaleDateString(DATE_LOCALE, opts);
}

export function dayLabel(date, today) {
  if (date === today) return 'Today';
  const t = new Date(`${today}T00:00:00`);
  t.setDate(t.getDate() + 1);
  if (date === localDateStr(t)) return 'Tomorrow';
  return fmtDay(date, { weekday: 'short' });
}

// The 7 days of the week strip, from → to inclusive.
export function daysBetween(from, to) {
  const out = [];
  if (!from) return out;
  const d = new Date(`${from}T00:00:00`);
  const end = to ? new Date(`${to}T00:00:00`) : null;
  for (let i = 0; i < 14; i++) {
    out.push(localDateStr(d));
    if (!end || d >= end) break;
    d.setDate(d.getDate() + 1);
  }
  return out;
}

// Nothing is deleted on its own any more (5-oct-2026, the user's call): a clip shows how old its project is,
// and the Projects panel deletes a project by hand.
export function ageLabel(days) {
  const d = num(days);
  if (d === null) return '';
  if (d < 1) return 'made today';
  const n = Math.floor(d);
  return n === 1 ? '1 day old' : `${n} days old`;
}

export function fmtBytes(bytes) {
  const b = num(bytes);
  if (b === null) return '';
  if (b >= 1e9) return `${(b / 1e9).toFixed(b >= 1e10 ? 0 : 1)} GB`;
  if (b >= 1e6) return `${Math.round(b / 1e6)} MB`;
  return `${Math.max(1, Math.round(b / 1e3))} kB`;
}

const firstNum = (...vals) => { for (const v of vals) { const n = num(v); if (n !== null) return n; } return null; };

const gb = (v) => (num(v) !== null ? v * 1e9 : null);

// The disk line (C2 `disk` = { output_gb, uploads_gb, free_gb, measured_at }, read defensively): what the
// projects take, what the downloaded sources take, what is left free.
export function diskOf(disk) {
  if (!disk || typeof disk !== 'object') return null;
  const used = firstNum(gb(disk.output_gb), disk.output_bytes, disk.used_bytes, gb(disk.used_gb));
  const sources = firstNum(gb(disk.uploads_gb), disk.uploads_bytes);
  const free = firstNum(gb(disk.free_gb), disk.free_bytes);
  return used === null && free === null ? null : { used, sources, free };
}

// "<job uuid>_Joe Rogan Experience #2553 - Andrew Huberman-004" → "Joe Rogan Experience #2553 - Andrew Huberman · part 4"
// (a long source is cut in ~36-min chunks: the part tells two projects of one episode apart).
export function projectTitle(raw) {
  const t = String(raw || '').replace(/^[0-9a-z]{8}-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{12}_/i, '');
  const m = /^(.*)-0*(\d{1,3})$/.exec(t);
  return m ? `${m[1]} · part ${Number(m[2])}` : t;
}

// The projects of the Projects panel: the engine's `projects` when it sends them, else the projects
// read from /api/local-projects. Counts come from the clips themselves when the engine doesn't give
// them, so a project's line always matches the board.
export function projectsOf(serverProjects, localProjects, clips) {
  const byJob = new Map();
  for (const c of clips) {
    if (!byJob.has(c.job_id)) byJob.set(c.job_id, []);
    byJob.get(c.job_id).push(c);
  }
  const src = Array.isArray(serverProjects) && serverProjects.length ? serverProjects : (localProjects || []);
  return src.map((p) => {
    const mine = byJob.get(p.job_id) || [];
    const count = (st) => mine.filter((c) => c.status === st).length;
    const first = mine[0];
    const counts = p.counts || {};
    const published = firstNum(p.published, counts.published) ?? count('published');
    const scheduled = firstNum(p.scheduled, counts.scheduled) ?? count('scheduled');
    const available = firstNum(p.available, counts.available) ?? count('available');
    const clipsN = firstNum(typeof p.clips === 'number' ? p.clips : null, p.clip_count, p.n_clips)
      ?? (mine.length || (Array.isArray(p.clips) ? p.clips.length : 0));
    return {
      job_id: p.job_id,
      title: p.label || (p.title ? projectTitle(p.title) : '') || (first ? episodeFull(first) : '') || p.job_id,
      age: firstNum(p.age_days, p.project_age_days, first?.project_age_days),
      size: firstNum(gb(p.size_gb), p.size_bytes, p.bytes),
      clips: clipsN,
      published,
      scheduled,
      available,
      notPublished: Math.max(0, clipsN - published),
    };
  }).sort((a, b) => (b.age ?? -1) - (a.age ?? -1));
}

// The spectator hasn't watched this clip (C2 `untested` on the clip, or no up-to-date result).
export const isUntested = (c) => c?.untested === true || spectatorScore(c) === null;

// The spectator's calibration (C1 calibration.json) in one honest sentence.
export function calibrationSentence(cal) {
  if (!cal || !num(cal.n)) return { text: 'Not calibrated yet — treat scores as indicative.', weak: true };
  const n = cal.n;
  const reading = cal.reading;
  if (reading === 'too_few') {
    return { text: `Checked against only ${n} published shorts — too few to trust yet; treat scores as indicative.`, weak: true };
  }
  const word = reading === 'strong' || reading === 'moderate' || reading === 'weak' ? reading : null;
  if (!word) return { text: `Checked against ${n} published shorts — treat scores as indicative.`, weak: true };
  return {
    text: `Checked against ${n} published shorts: agreement ${word}.`,
    weak: word === 'weak',
  };
}

// Which free posting slots a new plan may use: the same daily times as ScheduleComposer (its saved
// preferences), from today on (a slot less than 15 min away is skipped), skipping every slot already
// taken on the accounts concerned (the calendar) and every YouTube post the server already knows.
// `until` ("YYYY-MM-DD"): only the slots up to that day — "Mix my week" fills the week's free slots.
export function freeSlotsFor({ count, times, entries = [], timeline = [], platforms, profiles, fallbackProfile, now = new Date(), startOffsetDays = 0, until = '' }) {
  const occupied = new Set(entries
    .filter((e) => platforms.includes(e.platform) && e.time && profiles.has(e.profile || fallbackProfile))
    .map((e) => `${e.date}T${e.time}`));
  for (const t of timeline) {
    if (t.status !== 'published' && t.date && t.time) occupied.add(`${t.date}T${t.time}`);
  }
  return buildSlots({ count, times, startOffsetDays, occupied, now })
    .filter((s) => !until || s.date <= until)
    .map((s) => ({ date: s.date, time: s.time }));
}

// A slot that has passed (or is too close to send) while the plan sat on screen.
export function slotPassed(slot, now = new Date()) {
  if (!slot?.date || !slot?.time) return true;
  const dt = new Date(`${slot.date}T${slot.time}:00`);
  return dt.getTime() - now.getTime() < MIN_LEAD_MS;
}

// The plan in time order; swapping two rows exchanges their CLIPS, the times stay where they were.
// The suggestion's notes that the week doesn't already show (the engine repeats the week's own alerts).
export function newAlerts(planAlerts, weekAlerts) {
  const seen = new Set((weekAlerts || []).map((a) => `${a.kind}|${a.message}`));
  return (planAlerts || []).filter((a) => !seen.has(`${a.kind}|${a.message}`));
}

export const sortPlan = (plan) => [...plan].sort((a, b) => `${a.date}T${a.time}`.localeCompare(`${b.date}T${b.time}`));

export function swapPlanClips(plan, i, j) {
  if (i < 0 || j < 0 || i >= plan.length || j >= plan.length) return plan;
  const next = plan.map((p) => ({ ...p }));
  const pick = (p) => ({ job_id: p.job_id, clip_index: p.clip_index, ref: p.ref, why: p.why });
  const a = pick(next[i]);
  const b = pick(next[j]);
  next[i] = { ...next[i], ...b };
  next[j] = { ...next[j], ...a };
  return next;
}

// Criteria of the spectator (C1), in plain words.
export const CRITERIA = [
  ['stands_alone', 'The first sentence stands on its own'],
  ['topic_named', 'You know the topic within 5 s'],
  ['tension', 'A question or a stake within 5 s'],
  ['hook_matches_voice', 'The hook text says what the voice says'],
  ['first_frame_clear', 'The first image reads on a phone'],
  ['no_spoiler', "The hook doesn't give the ending away"],
];

export const STOP_LABEL = { yes: 'Yes', maybe: 'Maybe', no: 'No' };
