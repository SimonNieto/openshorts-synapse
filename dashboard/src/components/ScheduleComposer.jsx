import { useEffect, useMemo, useState } from 'react';
import { Loader2, Plus, Calendar, CheckCircle, AlertCircle, Check, Video, Instagram, Youtube } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';
import SegmentedControl from './ui/SegmentedControl';
import ProjectNicheBar from './ProjectNicheBar';
import TikTokDraftNotice from './TikTokDraftNotice';
import { SLOT_OPTIONS, buildSlots, slotStatusOn, userTimezone, slotLabel } from '../lib/postSlots';
import { loadSchedulePrefs as loadPrefs, saveSchedulePrefs as savePrefs, savedNicheChoice as savedChoice, socialPostBody } from '../lib/schedulePost';

const PLATFORM_OPTIONS = [
    { value: 'tiktok', label: 'TikTok', icon: <Video size={14} /> },
    { value: 'instagram', label: 'Instagram', icon: <Instagram size={14} /> },
    { value: 'youtube', label: 'YouTube', icon: <Youtube size={14} /> },
];

// 'now' = the 1st clip goes out right away, the others take the next free
// slots from today on. The days are greyed when the account has no free slot.
const DAY_OPTIONS = [
    { value: 'now', label: 'Now' },
    { value: '0', label: 'Today' },
    { value: '1', label: 'Tomorrow' },
    { value: '2', label: 'In 2 days' },
];
const ALL_TIMES = SLOT_OPTIONS.map((s) => s.value);

// Last-used platforms/slots (loadPrefs/savePrefs) and the project's saved niche + account (savedChoice)
// live in lib/schedulePost.js, shared with the Line-up so both send the same request (5-oct-2026).

/**
 * THE scheduling form — used by the Clip Generator's "schedule clips" window
 * and by Publish Plan, so the two can never drift apart again (they did:
 * one had real dates + text preview, the other didn't).
 *
 *  1. the project's niche + account (confirmed once, saved on the project)
 *  2. clips clicked in posting order (1st → first free slot)
 *  3. platforms · start day · 8h/12h/20h slots
 *  4. the real dates ("goes out"), an exact preview of every text
 *  5. schedule on Upload-Post (or note it in the checklist to post by hand)
 *
 * project: { job_id, clips: [{ index, title, video_url, predicted_score, published }],
 *            niche, niche_guess, upload_profile }
 * entries: the calendar (a slot is taken only by a post on the same account)
 */
export default function ScheduleComposer({
    project, entries = [], uploadPostKey, uploadUserId, profiles = [], isManaged, lastNiche = '',
    onNicheChosen, onScheduled, allowChecklist = false, onEntriesAdded,
}) {
    const prefs = useMemo(loadPrefs, []);
    const [nicheChoice, setNicheChoice] = useState(() => savedChoice(project, uploadUserId));
    // Clip indices in the order they were CLICKED (a Set keeps insertion order).
    const [selected, setSelected] = useState(new Set());
    const [platforms, setPlatforms] = useState(prefs.platforms || ['tiktok', 'instagram', 'youtube']);
    // Tomorrow by default: a full day of free slots, so 1st → 8h holds exactly.
    const [dayOffset, setDayOffset] = useState('1');
    const [slots, setSlots] = useState(prefs.slots || SLOT_OPTIONS.map((s) => s.value));
    const [scheduling, setScheduling] = useState(false);
    const [adding, setAdding] = useState(false);
    const [results, setResults] = useState({}); // clip index -> { ok, error }
    const [previews, setPreviews] = useState(null);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [error, setError] = useState('');
    // Re-evaluated every minute so a slot turns "passed" while the form is open.
    const [now, setNow] = useState(() => new Date());
    useEffect(() => {
        const t = setInterval(() => setNow(new Date()), 60000);
        return () => clearInterval(t);
    }, []);

    // A different project, or its saved niche/account changing, resets.
    useEffect(() => {
        setNicheChoice(savedChoice(project, uploadUserId));
        setSelected(new Set());
        setResults({});
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [project?.job_id, project?.niche, project?.upload_profile]);

    useEffect(() => { setPreviews(null); }, [selected, nicheChoice, platforms]);

    const ranked = useMemo(() => (project?.clips || [])
        .filter((c) => !c.published)
        .sort((a, b) => (b.predicted_score ?? -1) - (a.predicted_score ?? -1)), [project]);

    const activeProfile = nicheChoice?.profile || project?.upload_profile || uploadUserId;
    const canPost = !!(isManaged || (uploadPostKey && activeProfile));

    const orderedSelection = [...selected].map((i) => ranked.find((c) => c.index === i)).filter(Boolean);
    // Only posts on the SAME account take a slot: every niche account posts on
    // the same hours. Old entries without an account count as the Settings one.
    const occupied = useMemo(() => new Set(entries
        .filter((e) => platforms.includes(e.platform) && e.time && (e.profile || uploadUserId) === activeProfile)
        .map((e) => `${e.date}T${e.time}`)), [entries, platforms, activeProfile, uploadUserId]);
    const postNow = dayOffset === 'now';
    const startDay = postNow ? 0 : Number(dayOffset);
    const plan = useMemo(() => {
        const got = buildSlots({ count: orderedSelection.length, times: slots, startOffsetDays: startDay, occupied, now, postFirstNow: postNow });
        return orderedSelection.map((c, k) => ({ clip: c, index: c.index, slot: got[k] }));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selected, slots, dayOffset, occupied, ranked, now]);

    // Free slots per day on THIS account → greyed day / time chips.
    const dayStatus = useMemo(() => [0, 1, 2].map((d) => slotStatusOn({ offsetDays: d, times: ALL_TIMES, occupied, now })),
        [occupied, now]);
    const freeOn = (d) => Object.values(dayStatus[d]).filter((v) => v === 'free').length;
    const dayOptions = DAY_OPTIONS.map((o) => {
        if (o.value === 'now') return { ...o, hint: 'First clip' };
        const free = freeOn(Number(o.value));
        return { ...o, disabled: free === 0, hint: free === 0 ? 'Full' : `${free} free` };
    });
    // Greyed (with the reason) when not free on the start day, but still
    // clickable: the times are the DAILY pattern, and the clips that don't fit
    // on the start day roll over to the next days on those same times.
    const timeOptions = SLOT_OPTIONS.map((o) => {
        const st = dayStatus[startDay][o.value];
        return st === 'free' ? o : { ...o, muted: true, hint: st };
    });
    // The chosen day just filled up (or its last slot passed): next open day.
    useEffect(() => {
        if (postNow || freeOn(startDay) > 0) return;
        const next = [0, 1, 2].find((d) => freeOn(d) > 0);
        setDayOffset(next === undefined ? 'now' : String(next));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [dayStatus, dayOffset]);

    const tileTag = (order) => {
        const slot = plan[order]?.slot;
        if (!slot) return '';
        if (slot.now) return 'now';
        const hour = `${parseInt(slot.time, 10)}h`;
        const first = plan[0]?.slot;
        const days = first ? Math.round((new Date(`${slot.date}T00:00:00`) - new Date(`${first.date}T00:00:00`)) / 86400000) : 0;
        return days > 0 ? `${hour} · +${days}d` : hour;
    };

    const toggleClip = (index) => {
        if (scheduling) return;
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(index)) next.delete(index); else next.add(index);
            return next;
        });
    };

    const chooseNiche = (choice) => {
        setNicheChoice(choice);
        if (choice) onNicheChosen?.(choice);
    };

    const loadPreviews = async () => {
        if (!project || !selected.size || previewLoading) return;
        setPreviewLoading(true);
        try {
            const out = {};
            await Promise.all([...selected].map(async (index) => {
                out[index] = await apiJson('/api/social/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: project.job_id, clip_index: index, niche: nicheChoice?.niche || null }),
                });
            }));
            setPreviews(out);
        } catch (e) {
            setError(`Preview failed: ${e.detail || e.message}`);
        } finally {
            setPreviewLoading(false);
        }
    };

    const ready = canPost && !!nicheChoice && selected.size > 0 && platforms.length > 0 && plan.every((p) => p.slot);

    const handleSchedule = async () => {
        if (!ready || scheduling) return;
        savePrefs({ slots, platforms });
        setScheduling(true);
        setError('');
        setResults({});
        const timezone = userTimezone();
        for (const item of plan) {
            try {
                const res = await apiFetch('/api/social/post', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    // No title/description: the server builds one caption
                    // per platform (niche-generator hashtags only).
                    // null for the "now" choice → published right away.
                    body: JSON.stringify(socialPostBody({
                        jobId: project.job_id,
                        clipIndex: item.index,
                        uploadPostKey,
                        profile: activeProfile, // this niche's own accounts
                        platforms,
                        slot: item.slot,
                        niche: nicheChoice?.niche,
                        timezone,
                    })),
                });
                if (!res.ok) throw new Error(await res.text());
                setResults((prev) => ({ ...prev, [item.index]: { ok: true } }));
            } catch (e) {
                setResults((prev) => ({ ...prev, [item.index]: { ok: false, error: e.message } }));
            }
        }
        setScheduling(false);
        setSelected(new Set());
        onScheduled?.();
    };

    // "Checklist only": note the clips in the calendar to post by hand.
    const handleChecklist = async () => {
        if (!project || !selected.size || !platforms.length || adding) return;
        setAdding(true);
        setError('');
        try {
            const created = await Promise.all(plan.flatMap(({ index, clip, slot }) => platforms.map((platform) => apiJson('/api/schedule', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: project.job_id,
                    clip_index: index,
                    title: clip.title,
                    video_url: clip.video_url,
                    platform,
                    date: slot?.date,
                    time: slot?.time || '',
                    profile: activeProfile,
                }),
            }))));
            onEntriesAdded?.(created);
            setSelected(new Set());
        } catch {
            setError('Could not add these clips to the checklist.');
        } finally {
            setAdding(false);
        }
    };

    const okCount = Object.values(results).filter((r) => r.ok).length;
    const failed = Object.values(results).filter((r) => !r.ok);

    if (!project) return null;

    return (
        <div className="space-y-6">
            <ProjectNicheBar
                choice={nicheChoice}
                proposed={project.niche_guess || lastNiche}
                isAiGuess={!!project.niche_guess}
                onChoose={chooseNiche}
                profiles={profiles}
                defaultProfile={project.upload_profile || uploadUserId}
                disabled={scheduling}
            />

            {/* The clips, picked in posting order. */}
            <fieldset className="space-y-3 min-w-0">
                <legend className="readout mb-2">Clips</legend>
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm text-ink2" aria-live="polite">
                        {selected.size
                            ? <><span className="text-ink font-semibold">{selected.size}</span> selected · click order = posting order</>
                            : 'Click the clips in the order you want them posted.'}
                    </p>
                    <div className="flex gap-1.5 shrink-0">
                        <button type="button" disabled={scheduling} onClick={() => setSelected(new Set(ranked.map((c) => c.index)))} className="btn-quiet px-3 py-1.5 text-xs">All</button>
                        <button type="button" disabled={scheduling} onClick={() => setSelected(new Set(ranked.slice(0, 3).map((c) => c.index)))} className="btn-quiet px-3 py-1.5 text-xs">Best 3</button>
                        {selected.size > 0 && (
                            <button type="button" disabled={scheduling} onClick={() => setSelected(new Set())} className="btn-quiet px-3 py-1.5 text-xs">Clear</button>
                        )}
                    </div>
                </div>
                {ranked.length === 0 && (
                    <p className="tray text-sm text-muted py-8 px-4 text-center">Every clip of this project is already posted.</p>
                )}
                {ranked.length > 0 && (
                    <ul className="grid grid-cols-3 min-[420px]:grid-cols-4 sm:grid-cols-6 lg:grid-cols-8 gap-2">
                        {ranked.map((c) => {
                            const on = selected.has(c.index);
                            const order = orderedSelection.findIndex((r) => r.index === c.index);
                            const res = results[c.index];
                            const label = [
                                c.title,
                                Number.isFinite(c.predicted_score) && `viral score ${c.predicted_score}`,
                                on && !res && `posting position ${order + 1}${tileTag(order) ? ` (${tileTag(order)})` : ''}`,
                                res && (res.ok ? 'scheduled' : 'failed'),
                            ].filter(Boolean).join(', ');
                            return (
                                <li key={c.index}>
                                    <button
                                        type="button"
                                        onClick={() => toggleClip(c.index)}
                                        aria-pressed={on}
                                        aria-label={label}
                                        title={c.title}
                                        className={`relative block w-full aspect-[9/16] rounded-input overflow-hidden bg-black border transition-all ${on
                                            ? 'border-vermilion ring-2 ring-vermilion'
                                            : selected.size ? 'border-rule2 opacity-60 hover:opacity-100' : 'border-rule2 hover:border-ink'}`}
                                    >
                                        {c.video_url && (
                                            <video src={`${getApiUrl(c.video_url)}#t=1`} preload="metadata" muted playsInline aria-hidden="true" tabIndex={-1} className="absolute inset-0 w-full h-full object-cover pointer-events-none" />
                                        )}
                                        {Number.isFinite(c.predicted_score) && (
                                            <span className="absolute top-1 right-1 readout !text-ink px-1.5 rounded bg-paper/85" aria-hidden="true">{c.predicted_score}</span>
                                        )}
                                        <span className="absolute bottom-0 inset-x-0 px-1.5 py-1 bg-paper/85 text-xs leading-tight text-ink text-left truncate" aria-hidden="true">{c.title}</span>
                                        {on && !res && (
                                            <span className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-paper/35 pointer-events-none" aria-hidden="true">
                                                <span className="w-7 h-7 rounded-input bg-vermilion text-brassink text-sm font-semibold flex items-center justify-center">{order + 1}</span>
                                                {tileTag(order) && <span className="readout !text-ink px-1.5 rounded bg-paper/90">{tileTag(order)}</span>}
                                            </span>
                                        )}
                                        {res && (
                                            <span className="absolute inset-0 flex items-center justify-center bg-paper/60 pointer-events-none" aria-hidden="true">
                                                {res.ok ? <CheckCircle size={24} className="text-ok" /> : <AlertCircle size={24} className="text-danger" />}
                                            </span>
                                        )}
                                    </button>
                                </li>
                            );
                        })}
                    </ul>
                )}
            </fieldset>

            <div className="grid gap-5 lg:grid-cols-3">
                <fieldset className="min-w-0">
                    <legend className="readout mb-2">Platforms</legend>
                    <SegmentedControl multi columns={3} options={PLATFORM_OPTIONS} value={platforms} onChange={setPlatforms} />
                </fieldset>
                <fieldset className="min-w-0">
                    <legend className="readout mb-2">Start</legend>
                    <SegmentedControl options={dayOptions} value={dayOffset} onChange={setDayOffset} columns={4} size="sm" />
                </fieldset>
                <fieldset className="min-w-0">
                    <legend className="readout mb-2">Times · 1st click → 1st slot</legend>
                    <SegmentedControl multi options={timeOptions} value={slots} onChange={setSlots} columns={3} size="sm" />
                </fieldset>
            </div>

            {platforms.includes('tiktok') && <TikTokDraftNotice />}

            {/* Real dates before sending: "12h" on a tile doesn't say which day. */}
            {plan.length > 0 && (
                <div className="tray p-3 sm:p-4 space-y-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="readout">Goes out</p>
                        <button
                            type="button"
                            onClick={() => (previews ? setPreviews(null) : loadPreviews())}
                            disabled={previewLoading || !nicheChoice}
                            aria-expanded={!!previews}
                            title={nicheChoice ? '' : 'Confirm the niche first — the hashtags depend on it'}
                            className="btn-quiet px-3 py-1.5 text-xs"
                        >
                            {previewLoading && <Loader2 size={12} className="animate-spin" aria-hidden="true" />}
                            {previews ? 'Hide texts' : 'Preview texts'}
                        </button>
                    </div>
                    <ol className="flex flex-wrap gap-1.5" aria-label="Posting dates, in order">
                        {plan.map((p, k) => (
                            <li key={p.index} className={`readout px-2 py-1 rounded border bg-paper2 ${p.slot?.now ? 'border-ok/40 !text-ok' : 'border-rule2 !text-ink2'}`}>
                                {k + 1} · {p.slot ? slotLabel(p.slot) : '—'}
                            </li>
                        ))}
                    </ol>
                </div>
            )}

            {/* Exactly what each platform receives — same server code as the send. */}
            {previews && (
                <div className="space-y-4 p-3 sm:p-4 rounded-input bg-paper border border-rule max-h-[28rem] overflow-y-auto custom-scrollbar">
                    {plan.map((p, k) => {
                        const c = previews[p.index];
                        if (!c) return null;
                        const rows = [
                            platforms.includes('youtube') && ['youtube · title', c.youtube_title],
                            platforms.includes('youtube') && ['youtube · description', c.youtube_description],
                            platforms.includes('tiktok') && ['tiktok · caption', c.tiktok],
                            platforms.includes('instagram') && ['instagram · caption', c.instagram],
                        ].filter(Boolean);
                        return (
                            <article key={p.index} className="space-y-2">
                                <h4 className="text-sm text-ink font-medium break-words">{k + 1} · {p.clip.title}</h4>
                                {nicheChoice?.niche && !(c.niche_hashtags || []).length && (
                                    <p className="text-xs text-warn flex items-start gap-1.5">
                                        <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                                        <span>The niche generator found no hashtags for “{nicheChoice.niche}” (YouTube quota used up, or no results) — the AI's own hashtags would go out instead.</span>
                                    </p>
                                )}
                                <div className="space-y-2 pl-3 border-l border-rule2">
                                    {rows.map(([label, text]) => (
                                        <div key={label} className="text-xs">
                                            <span className="readout">{label}</span>
                                            {label === 'youtube · title' && <span className="readout text-muted ml-2">{text.length}/100</span>}
                                            <p className="text-ink2 whitespace-pre-wrap break-words mt-0.5">{text}</p>
                                        </div>
                                    ))}
                                </div>
                            </article>
                        );
                    })}
                </div>
            )}

            {error && (
                <p role="alert" className="flex items-start gap-2 text-sm text-danger break-words">
                    <AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden="true" /> {error}
                </p>
            )}

            <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-4 border-t border-rule">
                <p className="text-xs text-muted flex-1" aria-live="polite">
                    {!canPost
                        ? 'Set your Upload-Post key in Settings to schedule automatically.'
                        : !nicheChoice
                            ? 'Confirm the niche above to schedule.'
                            : Object.keys(results).length
                                ? (failed.length
                                    ? <span className="text-danger">{okCount} scheduled, {failed.length} failed: {String(failed[0].error || '').slice(0, 120)}</span>
                                    : <span className="text-ok inline-flex items-center gap-1"><Check size={13} aria-hidden="true" /> {okCount} scheduled on Upload-Post — you can turn the PC off.</span>)
                                : 'Posts go out on their own at the chosen time — the PC can be off.'}
                </p>
                <div className="flex flex-col-reverse min-[420px]:flex-row gap-2">
                    {allowChecklist && (
                        <button
                            type="button"
                            onClick={handleChecklist}
                            disabled={adding || scheduling || !selected.size || !platforms.length}
                            className="btn-ghost px-3 py-2 text-xs"
                            title="Just note it in the calendar — you'll post it yourself"
                        >
                            {adding ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Plus size={13} aria-hidden="true" />}
                            Checklist only
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={handleSchedule}
                        disabled={!ready || scheduling}
                        className="btn-accent px-4 py-2.5 text-sm"
                    >
                        {scheduling ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Calendar size={14} aria-hidden="true" />}
                        {scheduling
                            ? `Scheduling ${Object.keys(results).length + 1}/${plan.length}…`
                            : selected.size ? `Schedule ${selected.size} on Upload-Post` : 'Schedule on Upload-Post'}
                    </button>
                </div>
            </div>
        </div>
    );
}
