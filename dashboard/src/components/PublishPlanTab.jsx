import React, { useState, useEffect, useMemo } from 'react';
import { Loader2, Trash2, Check, CalendarClock, Video, Instagram, Youtube, Zap, RefreshCw, AlertCircle } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';
import ScheduleComposer from './ScheduleComposer';
import { localDateStr } from '../lib/postSlots';

// Platforms as small monochrome marks (design.md: colour is rare, no
// per-feature hues) — the label always travels with the mark for readers.
const PLATFORM_META = {
  tiktok: { label: 'TikTok', icon: <Video size={13} aria-hidden="true" /> },
  instagram: { label: 'Instagram', icon: <Instagram size={13} aria-hidden="true" /> },
  youtube: { label: 'YouTube', icon: <Youtube size={13} aria-hidden="true" /> },
};
const PLATFORM_ORDER = ['tiktok', 'instagram', 'youtube'];

// The daily target from the brand foundation (3 posts/day/platform). Purely
// a display goal for the progress bars — nothing here enforces it.
const DAILY_TARGET_PER_PLATFORM = 3;

// Uploads are stored under "<job uuid>_<n>" — meaningless on a chip. The
// project's date + its best clip's title is what you'd recognise it by.
const projectLabel = (p) => {
  const best = (p.clips || []).filter((c) => !c.published)
    .sort((a, b) => (b.predicted_score ?? -1) - (a.predicted_score ?? -1))[0];
  const when = p.updated_at
    ? new Date(p.updated_at * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
    : '';
  return [when, best?.title || p.title].filter(Boolean).join(' · ');
};

// Entries saved by the old picker carry "<job uuid>_<n> — <clip title>", and
// the stored title is the hashtag-padded YouTube one: show the clip's name.
const cleanTitle = (t) => String(t || '').replace(/^[0-9a-f]{8}-[0-9a-f-]{27,}(_\d+)?\s+—\s+/i, '');
const displayTitle = (t) => {
  const clean = cleanTitle(t);
  return clean.replace(/(^|\s)#\w+/g, '').replace(/\s{2,}/g, ' ').trim() || clean;
};

// One calendar row per post: the same clip at the same slot on the same
// account, whatever the number of platforms it goes to.
function groupPosts(entries) {
  const byPost = new Map();
  for (const e of entries) {
    const key = `${e.job_id}:${e.clip_index}:${e.date}:${e.time}:${e.profile || ''}:${e.auto ? 'auto' : 'hand'}`;
    if (!byPost.has(key)) byPost.set(key, { key, entries: [] });
    byPost.get(key).entries.push(e);
  }
  const posts = [...byPost.values()];
  posts.forEach((p) => p.entries.sort((a, b) => PLATFORM_ORDER.indexOf(a.platform) - PLATFORM_ORDER.indexOf(b.platform)));
  return posts.sort((a, b) => (a.entries[0].time || '99:99').localeCompare(b.entries[0].time || '99:99'));
}

const dayFromOffset = (offset) => {
  const d = new Date();
  d.setDate(d.getDate() + Number(offset));
  return localDateStr(d);
};

/**
 * The one place to plan posting across every project:
 *  - schedule: the shared ScheduleComposer (same form as the Clip Generator's
 *    "schedule clips"), for the project picked in the chips;
 *  - waiting on upload-post: its real queue, read live, with a true cancel;
 *  - calendar: everything planned, one row per post.
 */
export default function PublishPlanTab({ uploadPostKey, uploadUserId, profiles = [], isManaged, lastNiche = '', onNicheUsed }) {
  const [projects, setProjects] = useState(null);
  const [entries, setEntries] = useState(null);
  const [projectId, setProjectId] = useState('');
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);
  // What Upload-Post REALLY has queued (read live from them), not our record.
  const [queue, setQueue] = useState(null);
  const [queueError, setQueueError] = useState('');
  const [cancelingId, setCancelingId] = useState(null);
  const [expandedJob, setExpandedJob] = useState(null);

  const upHeaders = uploadPostKey ? { 'X-Upload-Post-Key': uploadPostKey } : {};

  // Projects with at least one clip still to post — posted clips have left
  // their project (app.py _mark_clip_published) and are never offered again.
  const loadProjects = (keepSelection = false) => apiJson('/api/local-projects')
    .then((d) => {
      const list = (d.projects || []).filter((p) => (p.clips || []).some((c) => !c.published));
      setProjects(list);
      setProjectId((cur) => (keepSelection && list.some((p) => p.job_id === cur) ? cur : (list[0]?.job_id || '')));
    })
    .catch(() => setError('Could not load clips from History.'));

  const loadEntries = () => apiJson('/api/schedule')
    .then((d) => setEntries(d.entries || []))
    .catch(() => setError('Could not load the publish plan.'));

  // Every niche account (Upload-Post profile) has its own queue; the server
  // endpoint is scoped to one profile at a time, so ask each and merge.
  const loadQueue = async () => {
    if (!uploadPostKey && !isManaged) return;
    const names = profiles.map((p) => p.username).filter(Boolean);
    const users = names.length ? names : (uploadUserId ? [uploadUserId] : []);
    try {
      const pages = await Promise.all(users.map(async (user) => {
        const res = await apiFetch(`/api/social/scheduled?user=${encodeURIComponent(user)}`, { headers: upHeaders });
        if (!res.ok) throw new Error(await res.text());
        return (await res.json()).scheduled_posts || [];
      }));
      setQueue(pages.flat().sort((a, b) => (a.scheduled_date || '').localeCompare(b.scheduled_date || '')));
      setQueueError('');
    } catch (e) {
      setQueueError(`Could not read Upload-Post's queue: ${String(e.message || e).slice(0, 160)}`);
    }
  };

  useEffect(() => {
    loadProjects();
    loadEntries();
  }, []);

  useEffect(() => {
    loadQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadPostKey, isManaged, uploadUserId, profiles.length]);

  const project = (projects || []).find((p) => p.job_id === projectId);
  // The shared form wants each clip's original index as its identity.
  const composerProject = useMemo(() => (project ? {
    ...project,
    clips: (project.clips || []).map((c, index) => ({ ...c, index })),
  } : null), [project]);

  // niche + account confirmed for this project → saved on it (and in the
  // niche → account memory), so the next session doesn't ask again.
  const saveNiche = async (choice) => {
    if (!project) return;
    if (choice.niche) onNicheUsed?.(choice.niche, choice.profile);
    try {
      await apiFetch(`/api/jobs/${project.job_id}/niche`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ niche: choice.niche || null, profile: choice.profile || null }),
      });
      setProjects((prev) => (prev || []).map((p) => (p.job_id === project.job_id
        ? { ...p, niche: choice.niche || null, upload_profile: choice.profile || p.upload_profile }
        : p)));
    } catch { /* kept for this session; confirming again retries */ }
  };

  // A queued job's lines in our calendar: by external_id (every send since it
  // was added), else by title + the local date/time we sent (older sends).
  const entriesForJob = (post) => (entries || []).filter((e) => e.source === 'upload-post' && !e.posted && (
    post.external_id
      ? post.external_id === `openshorts:${e.job_id}:${e.clip_index}`
      : (e.title === post.title && !!post.original_scheduled_str
        && e.date === post.original_scheduled_str.slice(0, 10)
        && e.time === post.original_scheduled_str.slice(11, 16))
  ));

  // The queued posts a set of calendar lines stands for (the inverse of entriesForJob).
  const queuedFor = (lines) => (queue || []).filter((q) => entriesForJob(q).some((e) => lines.some((l) => l.id === e.id)));

  // Cancel one queued post for real: Upload-Post first, then our calendar
  // lines, then the clip goes back in its project, ready to be scheduled
  // again. The clip is found from the calendar lines OR the post's own
  // external id ("openshorts:<job>:<clip>"), so a post whose calendar line was
  // already removed still gets its clip back (4-oct-2026: 12 rows deleted from
  // the calendar left 12 posts queued and their clips hidden).
  const cancelOnUploadPost = async (post) => {
    const owner = post.profile_username || uploadUserId;
    const res = await apiFetch(`/api/social/scheduled/${post.job_id}?user=${encodeURIComponent(owner)}`, { method: 'DELETE', headers: upHeaders });
    if (!res.ok) throw new Error(await res.text());
    const lines = entriesForJob(post);
    await Promise.all(lines.map((e) => apiFetch(`/api/schedule/${e.id}`, { method: 'DELETE' }).catch(() => {})));
    const clips = new Map(lines.map((e) => [`${e.job_id}:${e.clip_index}`, { job_id: e.job_id, clip_index: e.clip_index }]));
    const ext = /^openshorts:([^:]+):(\d+)$/.exec(post.external_id || '');
    if (ext) clips.set(`${ext[1]}:${ext[2]}`, { job_id: ext[1], clip_index: Number(ext[2]) });
    await Promise.all([...clips.values()].map((c) => apiFetch(`/api/clip/${c.job_id}/${c.clip_index}/restore`, { method: 'POST' }).catch(() => {})));
    setEntries((prev) => (prev || []).filter((e) => !lines.some((l) => l.id === e.id)));
  };

  const handleCancelQueued = async (post) => {
    if (cancelingId) return;
    if (!window.confirm(`Cancel "${(post.title || '').slice(0, 60)}" on Upload-Post? It won't be published.`)) return;
    setCancelingId(post.job_id);
    setQueueError('');
    try {
      await cancelOnUploadPost(post);
    } catch (e) {
      setQueueError(`Cancel failed: ${String(e.message || e).slice(0, 160)}`);
    } finally {
      setCancelingId(null);
      loadProjects(true);
      loadQueue();
    }
  };

  // Every queued post at once, one confirmation.
  const handleCancelAll = async () => {
    const posts = queue || [];
    if (cancelingId || !posts.length) return;
    if (!window.confirm(`Cancel all ${posts.length} posts waiting on Upload-Post? None of them will be published.`)) return;
    setCancelingId('all');
    setQueueError('');
    const failed = [];
    for (const post of posts) {
      try {
        await cancelOnUploadPost(post);
      } catch (e) {
        failed.push(`${(post.title || '').slice(0, 40)} (${String(e.message || e).slice(0, 60)})`);
      }
    }
    if (failed.length) setQueueError(`${failed.length} could not be cancelled: ${failed.join(' · ')}`);
    setCancelingId(null);
    loadProjects(true);
    loadQueue();
  };

  const handleTogglePosted = async (entry) => {
    if (busyId || entry.auto) return;
    setBusyId(entry.id);
    try {
      const updated = await apiJson(`/api/schedule/${entry.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ posted: !entry.posted }),
      });
      setEntries((prev) => (prev || []).map((e) => (e.id === entry.id ? updated : e)));
      // Ticking the last platform of a clip takes it out of its project
      // server-side — refresh so it leaves the picker too.
      loadProjects(true);
    } catch {
      setError('Could not update this entry.');
    } finally {
      setBusyId(null);
    }
  };

  // A calendar row is a whole post: removing it removes all its platforms.
  // A row still waiting on Upload-Post is cancelled THERE too — removing only
  // our line used to leave the post going out (4-oct-2026).
  const handleDeletePost = async (list) => {
    if (busyId || !list.length) return;
    const queued = queuedFor(list);
    if (queued.length && !window.confirm(`"${displayTitle(list[0].title).slice(0, 60)}" is waiting on Upload-Post. Cancel it there too? It won't be published.`)) return;
    setBusyId(list[0].id);
    try {
      for (const post of queued) await cancelOnUploadPost(post);
      await Promise.all(list.map((e) => apiJson(`/api/schedule/${e.id}`, { method: 'DELETE' }).catch(() => {})));
      setEntries((prev) => (prev || []).filter((e) => !list.some((l) => l.id === e.id)));
      if (queued.length) { loadProjects(true); loadQueue(); }
    } catch (e) {
      setError(`Could not remove this post: ${String(e.message || e).slice(0, 160)}`);
    } finally {
      setBusyId(null);
    }
  };

  // Today and upcoming days first (soonest on top), then the past, newest
  // first — the day you need to act on is always the first thing on screen.
  const groups = useMemo(() => {
    const today = localDateStr(new Date());
    const byDate = new Map();
    for (const e of entries || []) {
      if (!byDate.has(e.date)) byDate.set(e.date, []);
      byDate.get(e.date).push(e);
    }
    const all = [...byDate.entries()].map(([date, list]) => ({ date, entries: list }));
    const upcoming = all.filter((g) => g.date >= today).sort((a, b) => a.date.localeCompare(b.date));
    const past = all.filter((g) => g.date < today).sort((a, b) => b.date.localeCompare(a.date));
    return [...upcoming, ...past];
  }, [entries]);

  const fmtDate = (d) => {
    const parsed = new Date(`${d}T00:00:00`);
    const label = parsed.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
    if (d === localDateStr(new Date())) return `Today · ${label}`;
    if (d === dayFromOffset(1)) return `Tomorrow · ${label}`;
    return label;
  };

  if (projects === null || entries === null) {
    return (
      <div role="status" className="flex items-center justify-center gap-3 py-20 text-muted">
        <Loader2 size={18} className="animate-spin" aria-hidden="true" />
        <span className="text-sm">Loading the publish plan…</span>
      </div>
    );
  }

  const today = localDateStr(new Date());
  const upcoming = groups.filter((g) => g.date >= today);
  const past = groups.filter((g) => g.date < today);

  // One day of the calendar: a column on wide screens, a block of the list on phones.
  const renderDay = (group, isPast) => {
    const counts = Object.fromEntries(Object.keys(PLATFORM_META).map((p) => [
      p, group.entries.filter((e) => e.platform === p && (e.posted || e.auto)).length,
    ]));
    const dayId = `plan-day-${group.date}`;
    return (
      <section key={group.date} aria-labelledby={dayId} className={`card flex flex-col min-w-0 ${isPast ? 'opacity-75' : ''}`}>
        <header className="px-4 pt-4 pb-3 border-b border-rule">
          <h4 id={dayId} className="font-display text-base text-ink">{fmtDate(group.date)}</h4>
          {/* The daily target (3 per platform): a display goal, nothing enforces it. */}
          <ul className="mt-3 grid grid-cols-3 gap-3" aria-label={`Daily target: ${DAILY_TARGET_PER_PLATFORM} posts per platform`}>
            {Object.entries(PLATFORM_META).map(([p, meta]) => {
              const done = counts[p];
              const pct = Math.min(100, (done / DAILY_TARGET_PER_PLATFORM) * 100);
              return (
                <li key={p} className="min-w-0">
                  <span className="flex items-center gap-1.5 text-muted">
                    {meta.icon}
                    <span className="readout text-ink2">{done}/{DAILY_TARGET_PER_PLATFORM}</span>
                    <span className="sr-only">{meta.label}</span>
                  </span>
                  <span className="mt-1.5 block h-1 rounded-full bg-paper3 overflow-hidden" aria-hidden="true">
                    <span className="block h-full rounded-full bg-ink2 transition-all" style={{ width: `${pct}%` }} />
                  </span>
                </li>
              );
            })}
          </ul>
        </header>
        {/* One sheet per POST (clip + slot + account), its platforms as
            marks — the data keeps one line per platform (each has its
            own "posted" tick), but three rows per clip read as
            duplicates. */}
        <ol className="p-3 space-y-2 grow" aria-label={`Posts on ${fmtDate(group.date)}`}>
          {groupPosts(group.entries).map((post) => {
            const first = post.entries[0];
            const allPosted = post.entries.every((e) => e.posted);
            const isAuto = post.entries.every((e) => e.auto);
            return (
              <li key={post.key} className={`tray p-3 transition-opacity ${allPosted ? 'opacity-60' : ''}`}>
                <div className="flex items-start gap-3">
                  <div className="w-10 shrink-0 aspect-[9/16] bg-black border border-rule2 rounded overflow-hidden" aria-hidden="true">
                    <video src={getApiUrl(first.video_url)} preload="metadata" tabIndex={-1} className="w-full h-full object-cover" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="readout text-ink2">{first.time || '—'}</p>
                    <p className={`text-sm text-ink leading-snug line-clamp-2 break-words mt-0.5 ${allPosted ? 'line-through' : ''}`} title={displayTitle(first.title)}>
                      {displayTitle(first.title)}
                    </p>
                    <p className="readout mt-1 flex items-center gap-1.5 flex-wrap">
                      {isAuto
                        ? <span className="text-ink2 inline-flex items-center gap-1"><Zap size={11} aria-hidden="true" /> {allPosted ? 'Published' : 'Auto · Upload-Post'}</span>
                        : <span>By hand · tick each platform once live</span>}
                      {profiles.length > 1 && <span className="normal-case">· {first.profile || uploadUserId}</span>}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeletePost(post.entries)}
                    disabled={!!busyId}
                    aria-label={`Remove “${displayTitle(first.title)}” from the plan`}
                    className="-m-1 p-1.5 rounded-input text-muted hover:text-danger transition-colors shrink-0 inline-flex items-center justify-center [@media(pointer:coarse)]:min-h-[44px] [@media(pointer:coarse)]:min-w-[44px]"
                    title={isAuto ? 'Remove from the plan and cancel it on Upload-Post' : 'Remove from plan'}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </div>
                {/* Platforms: static for Upload-Post, one tick each by hand. */}
                <div className="mt-2.5 flex items-center gap-1.5">
                  {post.entries.map((entry) => {
                    const meta = PLATFORM_META[entry.platform] || PLATFORM_META.tiktok;
                    const cls = `w-8 h-8 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-input border flex items-center justify-center transition-colors ${entry.posted ? 'bg-ink border-ink text-paper2' : 'border-rule2 text-muted'}`;
                    return entry.auto ? (
                      <span key={entry.id} className={cls} title={`${meta.label} · ${entry.posted ? 'published' : 'scheduled on Upload-Post'}`}>
                        {meta.icon}
                        <span className="sr-only">{meta.label}: {entry.posted ? 'published' : 'scheduled on Upload-Post'}</span>
                      </span>
                    ) : (
                      <button
                        key={entry.id}
                        type="button"
                        onClick={() => handleTogglePosted(entry)}
                        disabled={busyId === entry.id}
                        aria-pressed={!!entry.posted}
                        aria-label={`Posted on ${meta.label}`}
                        className={`${cls} hover:border-ink hover:text-ink`}
                        title={`${meta.label} · ${entry.posted ? 'posted — click to undo' : 'click once posted'}`}
                      >
                        {entry.posted ? <Check size={14} strokeWidth={3} aria-hidden="true" /> : meta.icon}
                      </button>
                    );
                  })}
                </div>
              </li>
            );
          })}
        </ol>
      </section>
    );
  };

  return (
    <div className="animate-fade space-y-10">
      <header className="border-b border-rule pb-6">
        <p className="eyebrow">Publishing</p>
        <h2 className="page-title mt-2">Posting calendar</h2>
        <p className="page-lede mt-2">
          Plan posts across every project: schedule them on Upload-Post, or note them in the calendar to post by hand.
        </p>
      </header>

      {error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-danger">
          <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" /> {error}
        </p>
      )}

      {/* The desk: pick a project, then the shared scheduling form. */}
      <section aria-labelledby="plan-compose-title" className="card-print p-4 sm:p-6 space-y-5">
        <div>
          <h3 id="plan-compose-title" className="font-display text-lg text-ink">Schedule a project</h3>
          <p className="text-sm text-muted mt-1">
            Pick a project, click its clips in posting order, schedule. A posted clip leaves its project — no double posts.
          </p>
        </div>
        {/* Projects as tiles — one click switches the form below. */}
        <fieldset>
          <legend className="readout mb-2">Project</legend>
          {projects.length === 0 && <p className="text-sm text-muted">No clips left to post in History.</p>}
          <div className="flex flex-wrap gap-2">
            {projects.map((p) => {
              const active = p.job_id === projectId;
              return (
                <button
                  key={p.job_id}
                  type="button"
                  onClick={() => setProjectId(p.job_id)}
                  aria-pressed={active}
                  className={`max-w-full sm:max-w-[18rem] min-h-[44px] px-3 py-2 rounded-input border text-left transition-colors ${active
                    ? 'border-ink bg-ink text-paper2'
                    : 'border-rule2 bg-paper2 text-ink2 hover:border-ink hover:text-ink'}`}
                  title={projectLabel(p)}
                >
                  <span className="block text-xs font-medium truncate">{projectLabel(p)}</span>
                  <span className={`block readout mt-0.5 ${active ? '!text-paper2/75' : ''}`}>
                    {(p.clips || []).filter((c) => !c.published).length} clips to post
                  </span>
                </button>
              );
            })}
          </div>
        </fieldset>

        {composerProject && (
          <div className="pt-5 border-t border-rule">
            <ScheduleComposer
              project={composerProject}
              entries={entries}
              uploadPostKey={uploadPostKey}
              uploadUserId={uploadUserId}
              profiles={profiles}
              isManaged={isManaged}
              lastNiche={lastNiche}
              onNicheChosen={saveNiche}
              onScheduled={() => { loadEntries(); loadProjects(true); loadQueue(); }}
              allowChecklist
              onEntriesAdded={(created) => setEntries((prev) => [...(prev || []), ...created])}
            />
          </div>
        )}
      </section>

      {/* Read live from Upload-Post: the only true answer to "what is going
          to be published", and where a post gets cancelled for real. */}
      {(uploadPostKey || isManaged) && (
        <section aria-labelledby="plan-queue-title" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-rule">
            <h3 id="plan-queue-title" className="font-display text-lg text-ink flex items-center gap-2">
              <Zap size={16} className="text-muted" aria-hidden="true" /> Waiting on Upload-Post
              {queue && <span className="readout">{queue.length}</span>}
            </h3>
            <div className="flex gap-2">
              {(queue || []).length > 1 && (
                <button type="button" onClick={handleCancelAll} disabled={!!cancelingId} className="btn-danger px-3 py-1.5 text-xs">
                  {cancelingId === 'all'
                    ? <><Loader2 size={13} className="animate-spin" aria-hidden="true" /> Cancelling…</>
                    : `Cancel all (${queue.length})`}
                </button>
              )}
              <button type="button" onClick={loadQueue} className="btn-quiet px-3 py-1.5 text-xs">
                <RefreshCw size={13} aria-hidden="true" /> Refresh
              </button>
            </div>
          </div>
          <p className="text-xs text-muted">Read live from Upload-Post: what will really go out. Cancelling here stops the post for real.</p>
          {queueError && (
            <p role="alert" className="flex items-start gap-2 text-sm text-danger break-words">
              <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" /> {queueError}
            </p>
          )}
          {queue === null && !queueError && (
            <p role="status" className="flex items-center gap-2 text-sm text-muted">
              <Loader2 size={16} className="animate-spin" aria-hidden="true" /> Reading the queue…
            </p>
          )}
          {queue && queue.length === 0 && !queueError && (
            <p className="text-sm text-muted">Nothing queued on Upload-Post right now.</p>
          )}
          {(queue || []).length > 0 && (
            <ul className="space-y-2">
              {(queue || []).map((post) => {
                const local = post.original_scheduled_str
                  ? new Date(post.original_scheduled_str.slice(0, 16))
                  : new Date(post.scheduled_date);
                const when = `${local.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })} · ${local.toTimeString().slice(0, 5)}`;
                const detailsId = `plan-queue-${post.job_id}`;
                return (
                  <li key={post.job_id} className="card p-3 sm:p-4">
                    <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <p className="readout text-ink2">{when}</p>
                        <p className="text-sm text-ink truncate mt-0.5" title={post.title}>{displayTitle(post.title)}</p>
                        <p className="readout mt-1">
                          {(post.platforms || []).join(' · ')}
                          {profiles.length > 1 && <span className="normal-case"> · {post.profile_username}</span>}
                        </p>
                      </div>
                      <div className="flex gap-2 shrink-0">
                        <button
                          type="button"
                          onClick={() => setExpandedJob(expandedJob === post.job_id ? null : post.job_id)}
                          aria-expanded={expandedJob === post.job_id}
                          aria-controls={detailsId}
                          className="btn-quiet px-3 py-1.5 text-xs"
                        >
                          {expandedJob === post.job_id ? 'Hide details' : 'Details'}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleCancelQueued(post)}
                          disabled={!!cancelingId}
                          className="btn-danger px-3 py-1.5 text-xs"
                          title="Cancel on Upload-Post, remove it from this calendar and put the clip back in its project"
                        >
                          {cancelingId === post.job_id
                            ? <><Loader2 size={13} className="animate-spin" aria-hidden="true" /> Cancelling…</>
                            : 'Cancel post'}
                        </button>
                      </div>
                    </div>
                    {/* As Upload-Post stored it — i.e. what will be published. */}
                    {expandedJob === post.job_id && (
                      <div id={detailsId} className="mt-3 pt-3 border-t border-rule space-y-3">
                        {Object.entries(post.platform_content || {}).map(([platform, content]) => (
                          <div key={platform} className="text-xs">
                            <p className="readout">{platform}</p>
                            {content?.title && <p className="text-ink mt-1 break-words"><span className="text-muted">Title · </span>{content.title}</p>}
                            {content?.caption && <p className="text-ink2 mt-1 whitespace-pre-wrap break-words"><span className="text-muted">Caption · </span>{content.caption}</p>}
                          </div>
                        ))}
                        {!Object.keys(post.platform_content || {}).length && (
                          <p className="text-xs text-ink2 whitespace-pre-wrap break-words">{post.description || post.caption || post.title}</p>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {/* The calendar: today and upcoming days first (soonest first), then the past. */}
      <section aria-labelledby="plan-calendar-title" className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3 pb-3 border-b border-rule">
          <h3 id="plan-calendar-title" className="font-display text-lg text-ink">Coming up</h3>
          <p className="readout">Target · {DAILY_TARGET_PER_PLATFORM} a day per platform</p>
        </div>

        {groups.length === 0 && (
          <div className="tray p-8 text-center">
            <CalendarClock size={28} className="mx-auto mb-3 text-muted" aria-hidden="true" />
            <p className="text-sm text-ink2">Nothing planned yet.</p>
            <p className="text-sm text-muted mt-1">Schedule clips above and they appear here, day by day.</p>
          </div>
        )}
        {groups.length > 0 && upcoming.length === 0 && (
          <p className="text-sm text-muted">Nothing planned from today on.</p>
        )}
        {upcoming.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 items-start">
            {upcoming.map((group) => renderDay(group, false))}
          </div>
        )}
      </section>

      {past.length > 0 && (
        <section aria-labelledby="plan-past-title" className="space-y-4">
          <div className="pb-3 border-b border-rule">
            <h3 id="plan-past-title" className="font-display text-lg text-ink">Past</h3>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 items-start">
            {past.map((group) => renderDay(group, true))}
          </div>
        </section>
      )}
    </div>
  );
}
