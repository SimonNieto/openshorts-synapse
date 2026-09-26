import React, { useState, useEffect, useMemo } from 'react';
import { Loader2, Trash2, Check, CalendarClock, Video, Instagram, Youtube, Zap } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';
import ScheduleComposer from './ScheduleComposer';
import { localDateStr } from '../lib/postSlots';

// Per-platform accent so a glance at the calendar tells the platforms apart
// without reading the label — mirrors each app's own brand color, kept subtle
// (used as text/border tints, never a solid fill) so it still reads on dark.
const PLATFORM_META = {
  tiktok: { label: 'tiktok', icon: <Video size={14} />, color: '#25F4EE' },
  instagram: { label: 'instagram', icon: <Instagram size={14} />, color: '#E1306C' },
  youtube: { label: 'youtube', icon: <Youtube size={14} />, color: '#FF0000' },
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

  const handleCancelQueued = async (post) => {
    if (cancelingId) return;
    if (!window.confirm(`Cancel "${(post.title || '').slice(0, 60)}" on Upload-Post? It won't be published.`)) return;
    setCancelingId(post.job_id);
    setQueueError('');
    try {
      const owner = post.profile_username || uploadUserId;
      const res = await apiFetch(`/api/social/scheduled/${post.job_id}?user=${encodeURIComponent(owner)}`, { method: 'DELETE', headers: upHeaders });
      if (!res.ok) throw new Error(await res.text());
      // Cancelled for real → drop our calendar lines and put the clip back
      // in its project, ready to be scheduled again.
      const lines = entriesForJob(post);
      await Promise.all(lines.map((e) => apiFetch(`/api/schedule/${e.id}`, { method: 'DELETE' }).catch(() => {})));
      const clips = [...new Map(lines.map((e) => [`${e.job_id}:${e.clip_index}`, e])).values()];
      await Promise.all(clips.map((e) => apiFetch(`/api/clip/${e.job_id}/${e.clip_index}/restore`, { method: 'POST' }).catch(() => {})));
      setEntries((prev) => (prev || []).filter((e) => !lines.some((l) => l.id === e.id)));
      loadProjects(true);
      loadQueue();
    } catch (e) {
      setQueueError(`Cancel failed: ${String(e.message || e).slice(0, 160)}`);
    } finally {
      setCancelingId(null);
    }
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
  const handleDeletePost = async (list) => {
    if (busyId || !list.length) return;
    setBusyId(list[0].id);
    try {
      await Promise.all(list.map((e) => apiJson(`/api/schedule/${e.id}`, { method: 'DELETE' })));
      setEntries((prev) => (prev || []).filter((e) => !list.some((l) => l.id === e.id)));
    } catch {
      setError('Could not remove this post.');
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
    if (d === localDateStr(new Date())) return `today · ${label}`;
    if (d === dayFromOffset(1)) return `tomorrow · ${label}`;
    return label;
  };

  if (projects === null || entries === null) {
    return <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brass" /></div>;
  }

  return (
    <div className="max-w-5xl mx-auto animate-fade">
      <p className="eyebrow mb-1.5">08 · PUBLISH PLAN</p>
      <h1 className="font-display lowercase text-2xl text-ink mb-2">Posting calendar</h1>
      <p className="text-muted text-sm mb-8 lowercase">
        Pick a project, click its clips in posting order, schedule. A posted clip leaves its project — no double posts.
      </p>

      {error && <p className="text-danger text-sm mb-4">{error}</p>}

      <div className="card p-5 mb-10 space-y-4">
        {/* Projects as chips — one click switches the form below. */}
        <div>
          <label className="eyebrow block mb-2">project</label>
          {projects.length === 0 && <p className="text-sm text-muted">No clips left to post in History.</p>}
          <div className="flex flex-wrap gap-1.5">
            {projects.map((p) => (
              <button
                key={p.job_id}
                type="button"
                onClick={() => setProjectId(p.job_id)}
                className={`readout px-2.5 py-1.5 rounded-full max-w-[16rem] truncate transition-colors ${p.job_id === projectId
                  ? 'bg-brass/20 text-brass border border-brass/50'
                  : 'bg-paper3 hover:bg-paper2 text-ink2 border border-transparent'}`}
                title={projectLabel(p)}
              >
                {projectLabel(p)} · {(p.clips || []).filter((c) => !c.published).length} clips
              </button>
            ))}
          </div>
        </div>

        {composerProject && (
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
        )}
      </div>

      {/* Read live from Upload-Post: the only true answer to "what is going
          to be published", and where a post gets cancelled for real. */}
      {(uploadPostKey || isManaged) && (
        <section className="mb-10">
          <div className="flex items-center justify-between gap-3 mb-3 pb-3 border-b border-rule">
            <p className="text-sm text-ink font-medium lowercase flex items-center gap-2">
              <Zap size={14} className="text-brass" /> waiting on upload-post{queue ? ` · ${queue.length}` : ''}
            </p>
            <button type="button" onClick={loadQueue} className="readout px-2 py-1 rounded-full bg-paper3 hover:bg-paper2">refresh</button>
          </div>
          {queueError && <p className="text-danger text-xs mb-2">{queueError}</p>}
          {queue === null && !queueError && <Loader2 size={16} className="animate-spin text-brass" />}
          {queue && queue.length === 0 && !queueError && (
            <p className="text-xs text-muted lowercase">Nothing queued on Upload-Post right now.</p>
          )}
          <div className="space-y-2">
            {(queue || []).map((post) => {
              const local = post.original_scheduled_str
                ? new Date(post.original_scheduled_str.slice(0, 16))
                : new Date(post.scheduled_date);
              const when = `${local.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })} · ${local.toTimeString().slice(0, 5)}`;
              return (
                <div key={post.job_id} className="p-3 rounded-input border border-rule bg-paper">
                  <div className="flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-ink truncate" title={post.title}>{displayTitle(post.title)}</p>
                      <p className="readout mt-0.5 flex items-center gap-1.5 flex-wrap">
                        <span className="text-brass">{when}</span>
                        <span className="text-muted">· {(post.platforms || []).join(', ')}</span>
                        {profiles.length > 1 && <span className="text-muted">· {post.profile_username}</span>}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setExpandedJob(expandedJob === post.job_id ? null : post.job_id)}
                      className="readout px-2 py-1 rounded-full bg-paper3 hover:bg-paper2 shrink-0"
                    >
                      {expandedJob === post.job_id ? 'hide' : 'details'}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleCancelQueued(post)}
                      disabled={!!cancelingId}
                      className="btn-ghost px-3 py-1.5 text-xs shrink-0"
                      title="Cancel on Upload-Post, remove it from this calendar and put the clip back in its project"
                    >
                      {cancelingId === post.job_id ? <Loader2 size={13} className="animate-spin" /> : 'cancel'}
                    </button>
                  </div>
                  {/* As Upload-Post stored it — i.e. what will be published. */}
                  {expandedJob === post.job_id && (
                    <div className="mt-3 pt-3 border-t border-rule space-y-2">
                      {Object.entries(post.platform_content || {}).map(([platform, content]) => (
                        <div key={platform} className="text-xs">
                          <span className="eyebrow">{platform}</span>
                          {content?.title && <p className="text-ink mt-0.5 break-words"><span className="text-muted">title · </span>{content.title}</p>}
                          {content?.caption && <p className="text-ink2 mt-0.5 whitespace-pre-wrap break-words"><span className="text-muted">caption · </span>{content.caption}</p>}
                        </div>
                      ))}
                      {!Object.keys(post.platform_content || {}).length && (
                        <p className="text-xs text-ink2 whitespace-pre-wrap break-words">{post.description || post.caption || post.title}</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {groups.length === 0 && (
        <div className="text-center py-20 text-muted">
          <CalendarClock size={40} className="mx-auto mb-4 text-muted" />
          <p className="lowercase">Nothing planned yet. Schedule clips above.</p>
        </div>
      )}

      <div className="space-y-10">
        {groups.map((group) => {
          const counts = Object.fromEntries(Object.keys(PLATFORM_META).map((p) => [
            p, group.entries.filter((e) => e.platform === p && (e.posted || e.auto)).length,
          ]));
          return (
            <section key={group.date}>
              <div className="flex flex-wrap items-center justify-between gap-4 mb-4 pb-3 border-b border-rule">
                <p className="text-sm text-ink font-medium lowercase">{fmtDate(group.date)}</p>
                <div className="flex gap-4">
                  {Object.entries(PLATFORM_META).map(([p, meta]) => {
                    const done = counts[p];
                    const pct = Math.min(100, (done / DAILY_TARGET_PER_PLATFORM) * 100);
                    return (
                      <div key={p} className="flex items-center gap-2">
                        <span style={{ color: meta.color }}>{meta.icon}</span>
                        <div className="w-14 h-1.5 rounded-full bg-paper3 overflow-hidden">
                          <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: meta.color }} />
                        </div>
                        <span className="readout">{done}/{DAILY_TARGET_PER_PLATFORM}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="space-y-2.5">
                {/* One row per POST (clip + slot + account), its platforms as
                    icons — the data keeps one line per platform (each has its
                    own "posted" tick), but three rows per clip read as
                    duplicates. */}
                {groupPosts(group.entries).map((post) => {
                  const first = post.entries[0];
                  const allPosted = post.entries.every((e) => e.posted);
                  const isAuto = post.entries.every((e) => e.auto);
                  return (
                    <div
                      key={post.key}
                      className={`group flex items-center gap-3 p-3 rounded-input border border-rule bg-paper transition-opacity ${allPosted ? 'opacity-50' : 'hover:border-rule2'}`}
                    >
                      <span className="readout w-11 shrink-0 text-ink2 text-center">{first.time || '—'}</span>
                      <div className="w-16 h-9 bg-black rounded overflow-hidden shrink-0">
                        <video src={getApiUrl(first.video_url)} preload="metadata" className="w-full h-full object-cover" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className={`text-sm text-ink truncate ${allPosted ? 'line-through' : ''}`} title={displayTitle(first.title)}>
                          {displayTitle(first.title)}
                        </p>
                        <p className="readout mt-0.5 flex items-center gap-1.5 flex-wrap">
                          {isAuto
                            ? <span className="text-brass inline-flex items-center gap-1"><Zap size={11} /> {allPosted ? 'published' : 'auto · upload-post'}</span>
                            : <span className="text-muted">by hand · tick each platform once live</span>}
                          {profiles.length > 1 && <span className="text-muted">· {first.profile || uploadUserId}</span>}
                        </p>
                      </div>
                      {/* Platforms: static for Upload-Post, one tick each by hand. */}
                      <div className="flex items-center gap-1.5 shrink-0">
                        {post.entries.map((entry) => {
                          const meta = PLATFORM_META[entry.platform] || PLATFORM_META.tiktok;
                          const cls = `w-7 h-7 rounded-full border flex items-center justify-center transition-colors ${entry.posted ? 'bg-ok/20 border-ok' : 'border-rule2'}`;
                          return entry.auto ? (
                            <span key={entry.id} className={cls} style={{ color: meta.color }} title={`${meta.label} · ${entry.posted ? 'published' : 'scheduled on Upload-Post'}`}>
                              {meta.icon}
                            </span>
                          ) : (
                            <button
                              key={entry.id}
                              type="button"
                              onClick={() => handleTogglePosted(entry)}
                              disabled={busyId === entry.id}
                              className={`${cls} hover:border-brass`}
                              style={{ color: meta.color }}
                              title={`${meta.label} · ${entry.posted ? 'posted — click to undo' : 'click once posted'}`}
                            >
                              {entry.posted ? <Check size={13} strokeWidth={3} className="text-ok" /> : meta.icon}
                            </button>
                          );
                        })}
                      </div>
                      <button
                        onClick={() => handleDeletePost(post.entries)}
                        disabled={!!busyId}
                        className="p-1.5 rounded-full text-muted hover:text-danger transition-colors shrink-0 opacity-0 group-hover:opacity-100"
                        title={isAuto ? 'Remove from this calendar (to cancel it on Upload-Post, use "cancel" in "waiting on upload-post" above)' : 'Remove from plan'}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
