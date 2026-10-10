import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Loader2, RefreshCw, Eye, Shuffle, Calendar, X, LayoutGrid, ListOrdered, Upload, BarChart3 } from 'lucide-react';
import { apiJson } from '../lib/api';
import { getApiUrl } from '../config';
import { SLOT_OPTIONS, localDateStr } from '../lib/postSlots';
import { loadSchedulePrefs, savedNicheChoice } from '../lib/schedulePost';
import { TOPICS, topicLabel, topicOrder } from '../lib/topics';
import {
  DEFAULT_PLATFORMS, GROUP_ORDER, JURY_POLL_MS, SORTS, STATES, calibrationSentence, clipKey, diskOf, episodeFull,
  episodesOf, fmtDay, fmtDuration, freeSlotsFor, groupOf, isUntested, projectsOf, ranksOf, sortClips, sortPlan, stateOf,
  swapPlanClips,
} from '../lib/lineup';
import Modal from './ui/Modal';
import SegmentedControl from './ui/SegmentedControl';
import WeekBoard from './lineup/WeekBoard';
import ClipEntry from './lineup/ClipEntry';
import TopicPicker from './lineup/TopicPicker';
import ScheduleConfirm from './lineup/ScheduleConfirm';
import ProjectsPanel from './lineup/ProjectsPanel';
import { TopicSwatch } from './lineup/TopicTag';

// The view of the pool the user last chose (the ranking list or cards) — a per-browser convenience.
const VIEW_KEY = 'openshorts_lineup_view_v1';
const loadView = () => { try { return localStorage.getItem(VIEW_KEY) === 'cards' ? 'cards' : 'ranking'; } catch { return 'ranking'; } };
const saveView = (v) => { try { localStorage.setItem(VIEW_KEY, v); } catch { /* storage blocked */ } };

const VIEW_OPTIONS = [
  { value: 'ranking', label: 'Ranking', icon: <ListOrdered size={14} /> },
  { value: 'cards', label: 'Cards', icon: <LayoutGrid size={14} /> },
];

// "Mix my week" asks the engine to fill every free slot up to the end of the week shown: at most this many.
const MIX_MAX_SLOTS = 21;

// The groups of "Best first": never two scales in one list (lib/lineup.js groupOf).
const GROUPS = {
  tested: { title: 'To publish', how: 'ranked by the spectator',
    note: 'The spectator watched the first seconds of each clip like someone scrolling Shorts: its score is the estimated chance that a viewer stays.' },
  todo: { title: 'To publish', how: 'ranked by AI pick score',
    note: "AI pick score: how strong the AI judged the moment when it cut the clip (0–100). It isn't a YouTube number." },
  todoUntested: { title: 'Not tested yet', how: 'by AI pick score',
    note: 'The spectator hasn’t watched these yet: they come after, in the AI’s order.' },
  done: { title: 'Published', how: 'ranked by Stayed to watch',
    note: "YouTube Studio's own number: at 63% or more, 5 shorts out of 8 got a second wave." },
};

const chipCls = (on) => `min-h-[36px] [@media(pointer:coarse)]:min-h-[44px] px-2.5 rounded-input border text-xs inline-flex items-center gap-1.5 transition-colors
  ${on ? 'border-ink bg-ink text-paper2' : 'border-rule2 bg-paper2 text-ink2 hover:border-ink hover:text-ink'}`;

/**
 * Line-up (5-oct-2026): every clip made, in one place, and the simplest way to vary what goes out.
 *  - "Mix my week" (THE action): every clip still available → POST /api/lineup/plan on the week's free
 *    slots (nothing is published) → the suggestion shows in the week, picture by picture, with why each
 *    clip is there → take one out or swap → "Schedule on Upload-Post", after a confirmation that shows
 *    everything (POST /api/social/post, one per clip, exactly as ScheduleComposer).
 *  - the week (today → +6): what goes out on YouTube, day by day, big pictures (two posts that look alike
 *    show at once), the variety alerts and the week's mix;
 *  - the pool: every clip as a ranking line or a card, its topic in colour (click to correct it), where it
 *    stands (available / this week / later / published), its real numbers first (Studio's "Stayed to
 *    watch"), then the spectator's score, then the AI's; filters; manual selection → "Suggest an order";
 *  - Projects: nothing is deleted on its own; a project is deleted here, by hand.
 * The spectator's parts show only when the API turns it on (`jury_enabled`).
 * Data: GET /api/lineup (contract C2, output/_lineup/BRIEF.md).
 */
export default function LineupTab({ uploadPostKey, uploadUserId, isManaged, onOpenPlan }) {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [projects, setProjects] = useState([]);
  const [entries, setEntries] = useState([]);
  const [view, setView] = useState(loadView);
  const [topicFilter, setTopicFilter] = useState(() => new Set());
  const [stateFilter, setStateFilter] = useState('all');
  const [episodeFilter, setEpisodeFilter] = useState('');
  const [sort, setSort] = useState('best');
  const [selected, setSelected] = useState([]); // clip keys, in the order they were ticked
  const [plan, setPlan] = useState(null); // { mode: 'week' | 'selection', plan, alerts, left_out }
  const [planEdited, setPlanEdited] = useState(false);
  const [planning, setPlanning] = useState(null);
  const [planError, setPlanError] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [postNowClip, setPostNowClip] = useState(null);
  const [sentSome, setSentSome] = useState(false);
  const [playing, setPlaying] = useState(null);
  const [editing, setEditing] = useState(null);
  const [actionError, setActionError] = useState('');
  const [juryBusy, setJuryBusy] = useState(null);
  const [studioBusy, setStudioBusy] = useState(false);
  const [studioNote, setStudioNote] = useState('');
  const studioRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const d = await apiJson('/api/lineup');
      setData(d);
      setLoadError('');
    } catch (e) {
      setLoadError(e.status === 404
        ? "The line-up isn't on this server yet: it comes with the next update of the app."
        : `Could not load the line-up: ${e.detail || e.message}`);
    }
  }, []);
  // The projects (when each was made, its niche + account as a fallback) and the posting calendar (which
  // slots are taken): read-only, a failure only makes the screen a little less precise.
  const loadSide = useCallback(() => {
    apiJson('/api/local-projects').then((d) => setProjects(d.projects || [])).catch(() => {});
    apiJson('/api/schedule').then((d) => setEntries(d.entries || [])).catch(() => {});
  }, []);
  const reloadAll = useCallback(() => { load(); loadSide(); }, [load, loadSide]);

  useEffect(() => { reloadAll(); }, [reloadAll]);

  const clips = useMemo(() => data?.clips || [], [data]);
  const byKey = useMemo(() => Object.fromEntries(clips.map((c) => [clipKey(c), c])), [clips]);
  const byRef = useMemo(() => Object.fromEntries(clips.map((c) => [c.ref, c])), [clips]);
  const projectById = useMemo(() => Object.fromEntries(projects.map((p) => [p.job_id, p])), [projects]);
  const projectTime = useMemo(() => Object.fromEntries(projects.map((p) => [p.job_id, p.updated_at || 0])), [projects]);
  // (5-oct-2026) Spectator test kept for later at the user's request: everything about it shows only
  // when the API says `jury_enabled: true`.
  const spectatorOn = data?.jury_enabled === true;
  const today = (data?.now || '').slice(0, 10) || localDateStr(new Date());
  const weekTo = data?.week?.to || '';
  const available = useMemo(() => clips.filter((c) => c.status === 'available'), [clips]);

  // The niche + account a clip is posted with: its project's (sent on each clip by the catalogue;
  // /api/local-projects otherwise). Never guessed.
  const nicheSource = useCallback((c) => {
    const p = projectById[c.job_id];
    const niche = c.niche ?? p?.niche ?? null;
    const profile = c.upload_profile ?? p?.upload_profile ?? null;
    return niche || profile ? { niche, upload_profile: profile } : null;
  }, [projectById]);

  // --- the spectator ------------------------------------------------------------------------------------
  const juryRun = data?.jury_run || null;
  const juryRunning = !!juryRun?.running;
  useEffect(() => {
    if (!spectatorOn || !juryRunning) return undefined;
    const t = setInterval(async () => {
      try {
        const run = await apiJson('/api/lineup/jury/status');
        setData((d) => (d ? { ...d, jury_run: run } : d));
        if (!run?.running) load();
      } catch { /* the next tick retries */ }
    }, JURY_POLL_MS);
    return () => clearInterval(t);
  }, [spectatorOn, juryRunning, load]);

  const startJury = async (list, force = false, busyKey = 'all') => {
    if (juryBusy || juryRunning) return;
    setJuryBusy(busyKey);
    setActionError('');
    try {
      const res = await apiJson('/api/lineup/jury', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clips: list, force }),
      });
      const run = res?.jury_run || res;
      setData((d) => (d ? { ...d, jury_run: run } : d));
    } catch (e) {
      setActionError(`Could not start the spectator: ${e.detail || e.message}`);
    } finally {
      setJuryBusy(null);
    }
  };
  const untested = typeof data?.untested === 'number' ? data.untested
    : Array.isArray(data?.untested) ? data.untested.length : clips.filter(isUntested).length;
  const calibration = calibrationSentence(data?.jury_calibration);

  // --- the real numbers: a YouTube Studio export ---------------------------------------------------------
  // Same route and file as the "What works on your channels" card (PlusPanel): the CSV or the ZIP Studio
  // downloads. Published clips then show their real "Stayed to watch" before any score.
  const importStudio = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || studioBusy) return;
    setStudioBusy(true);
    setStudioNote('');
    setActionError('');
    try {
      const body = new FormData();
      body.append('file', file);
      const d = await apiJson('/api/plus/stats/studio', { method: 'POST', body });
      setStudioNote(`${d.rows} shorts read from ${file.name}${Number.isFinite(d.with_stayed) ? `, ${d.with_stayed} with “Stayed to watch”` : ''}.`);
      await load();
    } catch (e) {
      setActionError(`Could not import this export: ${e.detail || e.message}`);
    } finally {
      setStudioBusy(false);
    }
  };
  const studio = data?.stats_export || null;
  // C2 `stats_export` = { file, exported, problem, linked } or null.
  const studioWhen = studio && (studio.exported ? fmtDay(studio.exported, { day: 'numeric', month: 'short', year: 'numeric' }) : studio.file);

  // --- filters ----------------------------------------------------------------------------------------
  const topicCounts = useMemo(() => {
    const out = {};
    for (const c of clips) out[c.category || 'other'] = (out[c.category || 'other'] || 0) + 1;
    return out;
  }, [clips]);
  const presentTopics = TOPICS.filter((t) => topicCounts[t.id])
    .concat(Object.keys(topicCounts).filter((id) => !TOPICS.some((t) => t.id === id)).map((id) => ({ id })))
    .sort((a, b) => topicOrder(a.id) - topicOrder(b.id));
  const episodes = useMemo(() => episodesOf(clips), [clips]);
  const stateCounts = useMemo(() => {
    const out = { all: clips.length, available: 0, week: 0, later: 0, published: 0 };
    for (const c of clips) out[stateOf(c, weekTo)] += 1;
    return out;
  }, [clips, weekTo]);

  const shown = useMemo(() => clips.filter((c) => (
    (!topicFilter.size || topicFilter.has(c.category || 'other'))
    && (stateFilter === 'all' || stateOf(c, weekTo) === stateFilter)
    && (!episodeFilter || c.episode_key === episodeFilter)
  )), [clips, topicFilter, stateFilter, episodeFilter, weekTo]);
  const sorted = useMemo(() => sortClips(shown, sort, projectTime, spectatorOn), [shown, sort, projectTime, spectatorOn]);
  const ranks = useMemo(() => (sort === 'best' ? ranksOf(sorted, spectatorOn) : {}), [sorted, sort, spectatorOn]);
  const groups = sort === 'best'
    ? GROUP_ORDER.map((id) => ({
      id,
      ...GROUPS[id === 'todo' && spectatorOn ? 'todoUntested' : id],
      clips: sorted.filter((c) => groupOf(c, spectatorOn) === id),
    })).filter((g) => g.clips.length)
    : [{ id: 'all', title: '', clips: sorted }];
  const filtersOn = topicFilter.size > 0 || stateFilter !== 'all' || !!episodeFilter;
  const clearFilters = () => { setTopicFilter(new Set()); setStateFilter('all'); setEpisodeFilter(''); };
  const toggleTopic = (id) => setTopicFilter((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // --- "Mix my week", the selection and the suggested order -------------------------------------------
  const selectedClips = selected.map((k) => byKey[k]).filter((c) => c && c.status === 'available');
  const plannedByKey = useMemo(() => Object.fromEntries((plan?.plan || []).map((p) => [`${p.job_id}:${p.clip_index}`, p])), [plan]);

  const toggleSelect = (c) => {
    const k = clipKey(c);
    setSelected((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]));
    // Unticking a clip takes it out of the suggested order too.
    if (plannedByKey[k]) {
      setPlan((p) => (p ? { ...p, plan: p.plan.filter((x) => `${x.job_id}:${x.clip_index}` !== k) } : p));
      setPlanEdited(true);
    }
  };
  const clearAll = () => { setSelected([]); setPlan(null); setPlanEdited(false); setPlanError(''); };

  // 'week': every available clip on every free slot up to the end of the week shown — the engine picks
  // and orders, and leaves out what doesn't fit. 'selection': the ticked clips, one slot each.
  const runPlan = async (mode) => {
    const list = mode === 'week' ? available : selectedClips;
    if (!list.length || planning) return;
    setPlanning(mode);
    setPlanError('');
    try {
      const prefs = loadSchedulePrefs();
      const times = prefs.slots?.length ? prefs.slots : SLOT_OPTIONS.map((s) => s.value);
      const platforms = prefs.platforms?.length ? prefs.platforms : DEFAULT_PLATFORMS;
      const profiles = new Set(list.map((c) => savedNicheChoice(nicheSource(c), uploadUserId)?.profile || uploadUserId));
      const slots = freeSlotsFor({
        count: mode === 'week' ? MIX_MAX_SLOTS : list.length, times, entries, timeline: data?.week?.timeline || [],
        platforms, profiles, fallbackProfile: uploadUserId, until: mode === 'week' ? weekTo : '',
      });
      if (!slots.length) {
        setPlanError(mode === 'week'
          ? `No free slot left this week at your posting times (${times.join(', ')}).`
          : 'No free posting slot found.');
        return;
      }
      const res = await apiJson('/api/lineup/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clips: list.map((c) => [c.job_id, c.clip_index]), slots }),
      });
      setPlan({ mode, plan: sortPlan(res?.plan || []), alerts: res?.alerts || [], left_out: res?.left_out || [] });
      setPlanEdited(false);
      document.getElementById('lu-week-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
      setPlanError(`Could not suggest an order: ${e.detail || e.message}`);
    } finally {
      setPlanning(null);
    }
  };
  const swapPlan = (i, j) => { setPlan((p) => (p ? { ...p, plan: swapPlanClips(p.plan, i, j) } : p)); setPlanEdited(true); };
  const removeFromPlan = (i) => {
    const gone = plan?.plan?.[i];
    setPlan((p) => (p ? { ...p, plan: p.plan.filter((_, k) => k !== i) } : p));
    if (gone) setSelected((prev) => prev.filter((k) => k !== `${gone.job_id}:${gone.clip_index}`));
    setPlanEdited(true);
  };
  // The single « Post now » row: today, this minute (shown as « Now », sent without a time).
  const nowSlot = () => {
    const d = new Date();
    const p2 = (n) => String(n).padStart(2, '0');
    return { date: `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`, time: `${p2(d.getHours())}:${p2(d.getMinutes())}` };
  };
  const confirmItems = (plan?.plan || []).map((p) => {
    const clip = byRef[p.ref] || byKey[`${p.job_id}:${p.clip_index}`];
    return clip ? { date: p.date, time: p.time, clip, project: nicheSource(clip) } : null;
  }).filter(Boolean);

  const closeConfirm = () => {
    setConfirmOpen(false);
    setPostNowClip(null);
    if (sentSome) { clearAll(); setSentSome(false); }
  };

  const topicSaved = (updated) => {
    if (updated && updated.job_id !== undefined) {
      setData((d) => (d ? { ...d, clips: d.clips.map((c) => (clipKey(c) === clipKey(updated) ? { ...c, ...updated } : c)) } : d));
    }
    load(); // the week's mix and alerts follow the new topic
  };

  const projectList = useMemo(() => projectsOf(data?.projects, projects, clips), [data, projects, clips]);
  const disk = diskOf(data?.disk);

  // --- render -------------------------------------------------------------------------------------------
  if (!data && !loadError) {
    return (
      <div role="status" className="flex items-center justify-center gap-3 py-20 text-muted">
        <Loader2 size={18} className="animate-spin" aria-hidden="true" />
        <span className="text-sm">Loading every clip…</span>
      </div>
    );
  }

  const planCount = plan?.plan?.length || 0;
  // One signal per view (design.md): "Mix my week" while nothing is under way; then the bar's action.
  const mixIsTheAction = !planCount && !selectedClips.length;
  const barClips = planCount ? plan.plan.map((p) => byRef[p.ref]).filter(Boolean) : selectedClips;
  const barTopics = {};
  for (const c of barClips) barTopics[c.category || 'other'] = (barTopics[c.category || 'other'] || 0) + 1;

  return (
    <div className="animate-fade space-y-8">
      <header className="border-b border-rule pb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 max-w-2xl">
          <p className="eyebrow">Line-up</p>
          <h2 className="page-title mt-2">Every clip, at a glance</h2>
          <p className="page-lede mt-2">
            By topic and colour: this week, what is queued after, what is already out. One click mixes your
            week from the clips still available — check it in the week below, then schedule it.
          </p>
        </div>
        <div className="flex flex-col gap-2 w-full sm:w-auto sm:items-end">
          <div className="flex flex-col-reverse min-[420px]:flex-row gap-2">
            <button type="button" onClick={reloadAll} className="btn-quiet px-3 py-2 text-xs">
              <RefreshCw size={13} aria-hidden="true" /> Refresh
            </button>
            {data && (
              <button
                type="button"
                onClick={() => runPlan('week')}
                disabled={!!planning || !available.length}
                className={`${mixIsTheAction ? 'btn-accent' : 'btn-ghost'} px-5 py-2.5 text-sm`}
              >
                {planning === 'week' ? <Loader2 size={15} className="animate-spin" aria-hidden="true" /> : <Shuffle size={15} aria-hidden="true" />}
                {plan?.mode === 'week' ? 'Mix again' : 'Mix my week'}
              </button>
            )}
          </div>
          {data && (
            <p className="text-xs text-muted sm:text-right">
              {available.length
                ? `Uses the ${available.length} clip${available.length === 1 ? '' : 's'} still available, on this week's free slots. Nothing is sent.`
                : 'No clip is available to schedule.'}
            </p>
          )}
        </div>
      </header>

      {loadError && (
        <p role="alert" className="flex items-start gap-2 text-sm text-danger">
          <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" /> {loadError}
        </p>
      )}
      {(actionError || planError) && (
        <p role="alert" className="flex items-start gap-2 text-sm text-danger break-words">
          <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" /> {actionError || planError}
        </p>
      )}

      {data && (
        <WeekBoard
          week={data.week}
          today={today}
          clipsByRef={byRef}
          plan={plan}
          planEdited={planEdited}
          onOpenClip={(c) => { if (c?.video_url) setPlaying(c); }}
          onSwap={swapPlan}
          onRemove={removeFromPlan}
        />
      )}

      {data && (
        <section aria-labelledby="lu-pool-title" className="space-y-5">
          <div className="flex flex-wrap items-end justify-between gap-3 pb-3 border-b border-rule">
            <div>
              <h3 id="lu-pool-title" className="font-display text-lg sm:text-xl text-ink">All clips and their numbers</h3>
              <p className="text-sm text-muted mt-1">
                {clips.length} clip{clips.length === 1 ? '' : 's'} · {stateCounts.available} available to schedule
              </p>
            </div>
            <div className="w-full min-[480px]:w-64">
              <SegmentedControl options={VIEW_OPTIONS} value={view} onChange={(v) => { setView(v); saveView(v); }} columns={2} size="sm" />
            </div>
          </div>

          {/* Where the numbers come from: YouTube Studio's real ones, then the spectator's (when on). */}
          <div className={`tray p-3 sm:p-4 grid gap-4 ${spectatorOn ? 'lg:grid-cols-2' : ''}`}>
            <div className="flex flex-col sm:flex-row sm:items-start gap-3 min-w-0">
              <BarChart3 size={18} className="text-muted shrink-0 hidden sm:block mt-0.5" aria-hidden="true" />
              <div className="flex-1 min-w-0 space-y-1">
                {studio ? (
                  <>
                    <p className="text-sm text-ink">Published clips show their real “Stayed to watch” from YouTube Studio.</p>
                    <p className="readout normal-case tracking-[0.04em]">
                      Studio export{studioWhen ? ` of ${studioWhen}` : ''}{Number.isFinite(studio.linked) ? ` · ${studio.linked} clip${studio.linked === 1 ? '' : 's'} matched` : ''}
                    </p>
                    {studio.problem && <p className="text-xs text-warn">Couldn't read this export: {studio.problem}</p>}
                  </>
                ) : (
                  <>
                    <p className="text-sm text-ink">No YouTube Studio export yet: published clips can't show their real “Stayed to watch”.</p>
                    <p className="text-xs text-muted leading-relaxed">
                      In YouTube Studio: Analytics › Advanced mode › Content, filter Shorts, add the metric “Stayed to
                      watch”, then Export current view › Comma-separated values. Import the ZIP (or the CSV inside) here.
                    </p>
                  </>
                )}
                {studioNote && <p role="status" className="text-xs text-ok">{studioNote}</p>}
              </div>
              <input ref={studioRef} type="file" accept=".csv,.zip,.json,.tsv" className="sr-only" tabIndex={-1} aria-hidden="true" onChange={importStudio} />
              <button type="button" onClick={() => studioRef.current?.click()} disabled={studioBusy} className="btn-quiet px-3 py-2 text-xs shrink-0">
                {studioBusy ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Upload size={13} aria-hidden="true" />}
                {studio ? 'Import a newer export' : 'Import Studio export'}
              </button>
            </div>

            {/* (5-oct-2026) Spectator test kept for later at the user's request: shown only when it is on. */}
            {spectatorOn && (
              <div className="flex flex-col sm:flex-row sm:items-start gap-3 min-w-0 lg:border-l lg:border-rule lg:pl-4">
                <Eye size={18} className="text-muted shrink-0 hidden sm:block mt-0.5" aria-hidden="true" />
                <div className="flex-1 min-w-0 space-y-1">
                  <p className="text-sm text-ink">The spectator watches the first seconds of each clip like someone scrolling Shorts.</p>
                  <p className={`text-xs ${calibration.weak ? 'text-muted' : 'text-ink2'}`}>{calibration.text}</p>
                  <div aria-live="polite">
                    {juryRunning && (
                      <div className="mt-2 space-y-1">
                        <p className="text-xs text-ink2">Watched {juryRun.done || 0} of {juryRun.total || 0}…</p>
                        <div role="progressbar" aria-label="The spectator's progress" aria-valuemin={0} aria-valuemax={juryRun.total || 0} aria-valuenow={juryRun.done || 0}
                          className="h-1.5 rounded-full bg-paper2 overflow-hidden">
                          <span className="block h-full bg-ink2 transition-all" style={{ width: `${juryRun.total ? (100 * (juryRun.done || 0)) / juryRun.total : 0}%` }} />
                        </div>
                      </div>
                    )}
                    {!juryRunning && (juryRun?.errors || []).length > 0 && (
                      <p className="text-xs text-warn mt-1">
                        {juryRun.errors.length} clip{juryRun.errors.length === 1 ? '' : 's'} could not be watched: {juryRun.errors.slice(0, 3).map((e) => (typeof e === 'string' ? e : `${e.ref || ''} ${e.error || e.message || ''}`.trim())).join(' · ')}
                      </p>
                    )}
                  </div>
                </div>
                {(untested > 0 || juryRunning) && (
                  <button type="button" onClick={() => startJury(null)} disabled={juryRunning || !!juryBusy} className="btn-quiet px-3 py-2 text-xs shrink-0">
                    {(juryRunning || juryBusy === 'all') && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
                    {juryRunning ? 'Watching…' : `Test with the spectator (${untested})`}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Filters: topic chips with their count, where the clip stands, the episode, the order. */}
          <div className="space-y-4">
            <div role="group" aria-label="Filter by topic" className="flex flex-wrap gap-1.5">
              <button type="button" onClick={() => setTopicFilter(new Set())} aria-pressed={!topicFilter.size} className={chipCls(!topicFilter.size)}>
                All topics <span className={`readout ${!topicFilter.size ? '!text-paper2/75' : ''}`}>{clips.length}</span>
              </button>
              {presentTopics.map((t) => {
                const on = topicFilter.has(t.id);
                return (
                  <button key={t.id} type="button" onClick={() => toggleTopic(t.id)} aria-pressed={on} className={chipCls(on)}>
                    <TopicSwatch id={t.id} />
                    {topicLabel(t.id, clips.find((c) => c.category === t.id)?.category_label)}
                    <span className={`readout ${on ? '!text-paper2/75' : ''}`}>{topicCounts[t.id]}</span>
                  </button>
                );
              })}
            </div>
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)_minmax(0,0.7fr)] items-end">
              <fieldset className="min-w-0">
                <legend className="readout mb-2">Where it stands</legend>
                <SegmentedControl
                  options={STATES.map((s) => ({ ...s, hint: String(stateCounts[s.value] ?? 0) }))}
                  value={stateFilter}
                  onChange={setStateFilter}
                  columns={5}
                  size="sm"
                />
              </fieldset>
              <div className="min-w-0">
                <label htmlFor="lu-episode" className="readout mb-2 block">Episode</label>
                <select id="lu-episode" className="input-field" value={episodeFilter} onChange={(e) => setEpisodeFilter(e.target.value)}>
                  <option value="">All episodes ({episodes.length})</option>
                  {episodes.map((ep) => <option key={ep.key} value={ep.key}>{ep.label} · {ep.count}</option>)}
                </select>
              </div>
              <div className="min-w-0">
                <label htmlFor="lu-sort" className="readout mb-2 block">Order</label>
                <select id="lu-sort" className="input-field" value={sort} onChange={(e) => setSort(e.target.value)}>
                  {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </div>
            </div>
          </div>

          {sorted.length === 0 && (
            <div className="tray p-8 text-center space-y-3">
              <p className="text-sm text-ink2">{clips.length ? 'No clip matches these filters.' : 'No clip yet: the clips you make appear here.'}</p>
              {filtersOn && <button type="button" onClick={clearFilters} className="btn-ghost px-4 py-2 text-sm">Show every clip</button>}
            </div>
          )}

          {groups.map((g) => g.clips.length > 0 && (
            <div key={g.id} className="space-y-3" role="region" aria-label={g.title ? `${g.title}, ${g.how}` : 'Clips'}>
              {g.title && (
                <div className="pt-1">
                  <h4 className="text-sm font-medium text-ink">
                    {g.title} <span className="text-muted font-normal">· {g.clips.length} · {g.how}</span>
                  </h4>
                  {g.note && <p className="text-xs text-muted mt-0.5">{g.note}</p>}
                </div>
              )}
              <ol className={view === 'cards' ? 'grid gap-3 md:grid-cols-2 2xl:grid-cols-3' : 'space-y-2'}>
                {g.clips.map((c) => {
                  const k = clipKey(c);
                  return (
                    <li key={k} className="min-w-0">
                      <ClipEntry
                        clip={c}
                        layout={view === 'cards' ? 'card' : 'row'}
                        rank={ranks[k]}
                        selectable={c.status === 'available'}
                        selected={selected.includes(k)}
                        onToggle={() => toggleSelect(c)}
                        onPlay={c.video_url ? () => setPlaying(c) : undefined}
                        onEditTopic={() => setEditing(c)}
                        onRetest={spectatorOn ? () => startJury([[c.job_id, c.clip_index]], true, k) : undefined}
                        retesting={juryBusy === k || (juryRunning && juryRun?.current === c.ref)}
                        running={spectatorOn && juryRunning && juryRun?.current === c.ref}
                        planned={plannedByKey[k]}
                        weekTo={weekTo}
                        spectatorOn={spectatorOn}
                        onPostNow={c.status === 'available' ? () => setPostNowClip(c) : undefined}
                      />
                    </li>
                  );
                })}
              </ol>
            </div>
          ))}
        </section>
      )}

      {data && (
        <ProjectsPanel projects={projectList} disk={disk} onDeleted={() => { clearAll(); reloadAll(); }} />
      )}

      {/* The bar: what is ticked or suggested, its topics, and THE action of the moment. */}
      {(selectedClips.length > 0 || planCount > 0) && (
        <div className="sticky bottom-0 z-20 -mx-4 sm:mx-0 pt-2 safe-bottom">
          <div className="card-print px-4 py-3" role="region" aria-label={planCount ? 'The suggested order' : 'Your selection'}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <div className="flex-1 min-w-[12rem]" aria-live="polite">
                <p className="text-sm text-ink">
                  {planCount
                    ? <><span className="font-semibold">{planCount}</span> post{planCount === 1 ? '' : 's'} suggested{planEdited ? ' (edited)' : ''} · <span className="text-ink2">not sent yet</span></>
                    : <><span className="font-semibold">{selectedClips.length}</span> selected</>}
                </p>
                <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1" aria-label="Topics">
                  {Object.entries(barTopics).sort((a, b) => b[1] - a[1]).map(([id, n]) => (
                    <li key={id} className="text-[11px] text-muted flex items-center gap-1">
                      <TopicSwatch id={id} size={8} /> {topicLabel(id, barClips.find((c) => c.category === id)?.category_label)} {n}
                    </li>
                  ))}
                </ul>
              </div>
              <button type="button" onClick={clearAll} className="btn-quiet px-3 py-2 text-xs">
                <X size={13} aria-hidden="true" /> Clear
              </button>
              {planCount > 0 ? (
                <>
                  <button type="button" onClick={() => runPlan(plan.mode)} disabled={!!planning} className="btn-ghost px-3 py-2 text-xs">
                    {planning ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Shuffle size={13} aria-hidden="true" />}
                    {plan.mode === 'week' ? 'Mix again' : 'Suggest again'}
                  </button>
                  <button type="button" onClick={() => setConfirmOpen(true)} className="btn-accent px-4 py-2.5 text-sm">
                    <Calendar size={14} aria-hidden="true" /> Schedule {planCount} on Upload-Post
                  </button>
                </>
              ) : (
                <button type="button" onClick={() => runPlan('selection')} disabled={!!planning || !selectedClips.length} className="btn-accent px-4 py-2.5 text-sm">
                  {planning ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Shuffle size={14} aria-hidden="true" />}
                  Suggest an order
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      <ScheduleConfirm
        isOpen={confirmOpen || !!postNowClip}
        onClose={closeConfirm}
        items={postNowClip ? [{ ...nowSlot(), clip: postNowClip, project: nicheSource(postNowClip), now: true }] : confirmItems}
        uploadPostKey={uploadPostKey}
        uploadUserId={uploadUserId}
        isManaged={isManaged}
        onOpenPlan={onOpenPlan}
        onDone={() => { setSentSome(true); reloadAll(); }}
      />

      {editing && <TopicPicker clip={editing} onClose={() => setEditing(null)} onSaved={topicSaved} />}

      <Modal
        isOpen={!!playing}
        onClose={() => setPlaying(null)}
        eyebrow={playing ? topicLabel(playing.category, playing.category_label) : ''}
        title={playing?.title || ''}
        size="md"
      >
        {playing?.video_url && (
          <div className="space-y-3">
            <video
              key={playing.video_url}
              src={getApiUrl(playing.video_url)}
              controls
              autoPlay
              playsInline
              className="block mx-auto w-auto max-w-full max-h-[68vh] aspect-[9/16] bg-black border border-rule2 rounded-input"
            />
            <p className="readout normal-case tracking-[0.04em] text-center">
              {[episodeFull(playing), fmtDuration(playing.duration)].filter(Boolean).join(' · ')}
            </p>
            {playing.hook && <p className="text-sm text-ink2 text-center">Hook: “{playing.hook}”</p>}
          </div>
        )}
      </Modal>
    </div>
  );
}
