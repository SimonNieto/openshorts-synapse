import React, { useState, useEffect, useMemo } from 'react';
import { Loader2, Download, FolderOpen, Trash2, Pin, PinOff, AlertCircle } from 'lucide-react';
import { apiJson } from '../lib/api';
import { getApiUrl } from '../config';

// Cloud: the signed-in user's saved video library (stored in R2, private
// signed links). Self-host: no R2 archive exists, so this instead lists
// whatever job directories are still on local disk (/api/local-projects,
// default 24h retention) and reopens them straight from there. Either way,
// projects are grouped by job with a "reopen" action that restores the whole
// job for further editing in the Clip Generator.
export default function HistoryTab({ onReopenProject, billingEnabled }) {
  const [videos, setVideos] = useState(null);
  const [projects, setProjects] = useState({});
  const [localProjects, setLocalProjects] = useState(null);
  const [reopening, setReopening] = useState(null);
  const [reopenError, setReopenError] = useState('');
  const [error, setError] = useState('');
  const [deleting, setDeleting] = useState(null);
  const [keeping, setKeeping] = useState(null);

  useEffect(() => {
    if (billingEnabled) {
      apiJson('/api/history')
        .then((d) => setVideos(d.videos || []))
        .catch(() => setError('Could not load your library.'));
      apiJson('/api/projects')
        .then((d) => {
          const map = {};
          for (const p of d.projects || []) map[p.job_id] = p;
          setProjects(map);
        })
        .catch(() => {});
    } else {
      apiJson('/api/local-projects')
        .then((d) => setLocalProjects(d.projects || []))
        .catch(() => setError('Could not load local projects.'));
    }
  }, [billingEnabled]);

  // Group videos by job, preserving the newest-first order of /api/history.
  const cloudGroups = useMemo(() => {
    const byJob = new Map();
    for (const v of videos || []) {
      const key = v.job_id || v.id;
      if (!byJob.has(key)) byJob.set(key, []);
      byJob.get(key).push(v);
    }
    return [...byJob.entries()];
  }, [videos]);

  // Normalize both sources into one shape so the grid below renders once.
  const sections = useMemo(() => {
    if (billingEnabled) {
      return cloudGroups.map(([jobId, vids]) => ({
        jobId,
        title: projects[jobId]?.title || vids[0]?.title || 'Project',
        date: vids[0]?.created_at,
        reopenable: !!projects[jobId],
        clips: vids.map((v) => ({
          key: v.id,
          title: v.title || 'Short',
          date: v.created_at,
          videoSrc: v.view_url,
          downloadHref: v.download_url,
        })),
      }));
    }
    return (localProjects || []).map((p) => ({
      jobId: p.job_id,
      title: p.title || 'Project',
      date: p.updated_at ? p.updated_at * 1000 : null,
      reopenable: true,
      kept: !!p.kept,
      clips: p.clips.map((c, i) => ({
        key: `${p.job_id}_${i}`,
        title: c.title || `Clip ${i + 1}`,
        date: null,
        videoSrc: getApiUrl(c.video_url),
        downloadHref: getApiUrl(c.video_url),
      })),
    }));
  }, [billingEnabled, cloudGroups, projects, localProjects]);

  const loading = billingEnabled ? (videos === null && !error) : (localProjects === null && !error);

  const handleReopen = async (jobId) => {
    if (!onReopenProject || reopening) return;
    setReopening(jobId);
    setReopenError('');
    try {
      await onReopenProject(jobId);
    } catch (e) {
      setReopenError('Could not reopen this project. Please try again.');
      setReopening(null);
    }
  };

  const handleDelete = async (jobId) => {
    if (billingEnabled || deleting) return;
    if (!window.confirm('Delete this project and all its clips? This cannot be undone.')) return;
    setDeleting(jobId);
    try {
      await apiJson(`/api/local-projects/${jobId}`, { method: 'DELETE' });
      setLocalProjects((prev) => (prev || []).filter((p) => p.job_id !== jobId));
    } catch (e) {
      setError('Could not delete this project. Please try again.');
    } finally {
      setDeleting(null);
    }
  };

  const handleToggleKeep = async (jobId, currentlyKept) => {
    if (billingEnabled || keeping) return;
    setKeeping(jobId);
    try {
      await apiJson(`/api/local-projects/${jobId}/keep`, { method: currentlyKept ? 'DELETE' : 'POST' });
      setLocalProjects((prev) => (prev || []).map((p) => (
        p.job_id === jobId ? { ...p, kept: !currentlyKept } : p
      )));
    } catch (e) {
      setError('Could not update this project. Please try again.');
    } finally {
      setKeeping(null);
    }
  };

  const fmtDate = (d) => (d ? new Date(d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '');

  if (loading) {
    return (
      <div role="status" className="flex items-center justify-center gap-3 py-20 text-muted">
        <Loader2 size={18} className="animate-spin" aria-hidden="true" />
        <span className="text-sm">Loading your projects…</span>
      </div>
    );
  }

  const totalClips = sections.reduce((n, s) => n + s.clips.length, 0);

  return (
    <div className="animate-fade space-y-8">
      {/* Archive header: what this is, and the two numbers that matter. */}
      <header className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between border-b border-rule pb-6">
        <div className="min-w-0">
          <p className="eyebrow">Library</p>
          <h2 className="page-title mt-2">Your projects</h2>
          <p className="page-lede mt-2">
            {billingEnabled
              ? "All the shorts you've generated, saved while your plan is active. Kept for 7 days after your plan ends. Reopen a project to keep editing its clips."
              : "Recent projects still on this machine's disk (cleaned up automatically after a while). Keep one to protect it from cleanup, or reopen it to keep editing its clips."}
          </p>
        </div>
        {sections.length > 0 && (
          <dl className="flex gap-8 shrink-0">
            <div>
              <dt className="readout">Projects</dt>
              <dd className="font-quote text-4xl text-ink leading-none mt-1.5">{sections.length}</dd>
            </div>
            <div>
              <dt className="readout">Clips</dt>
              <dd className="font-quote text-4xl text-ink leading-none mt-1.5">{totalClips}</dd>
            </div>
          </dl>
        )}
      </header>

      {(error || reopenError) && (
        <div role="alert" className="tray px-4 py-3 space-y-1.5">
          {error && (
            <p className="flex items-start gap-2 text-sm text-danger">
              <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" /> {error}
            </p>
          )}
          {reopenError && (
            <p className="flex items-start gap-2 text-sm text-danger">
              <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" /> {reopenError}
            </p>
          )}
        </div>
      )}

      {sections.length === 0 && (
        <div className="tray p-5 sm:p-8 grid gap-6 sm:grid-cols-[minmax(0,15rem)_1fr] sm:items-center">
          <figure className="w-full max-w-[15rem] mx-auto sm:mx-0">
            <div className="aspect-[16/10] bg-black border border-rule2 rounded-card overflow-hidden">
              <img src="/landing/universe.jpg" alt="" loading="lazy" className="w-full h-full object-cover" />
            </div>
            <figcaption className="readout mt-2">Drawn B-roll · universe</figcaption>
          </figure>
          <div>
            <h3 className="font-display text-xl text-ink">No projects yet</h3>
            <p className="text-sm text-muted mt-2 max-w-md leading-relaxed">
              Generate your first short from the Clip Generator. Every project lands here, ready to reopen.
            </p>
          </div>
        </div>
      )}

      {sections.length > 0 && (
        <ol className="space-y-5" aria-label="Projects, newest first">
          {sections.map((section) => {
            const headingId = `history-${section.jobId}`;
            return (
              <li key={section.jobId}>
                <article aria-labelledby={headingId} className="card p-4 sm:p-6">
                  <div className="grid gap-4 lg:grid-cols-[10rem_minmax(0,1fr)] lg:gap-8">
                    {/* The date column of the archive: when, and how much. */}
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 lg:flex-col lg:gap-1.5 lg:border-r lg:border-rule lg:pr-6">
                      <p className="readout text-ink2">{fmtDate(section.date) || 'Undated'}</p>
                      <p className="readout">{section.clips.length} clip{section.clips.length === 1 ? '' : 's'}</p>
                      {!billingEnabled && section.kept && (
                        <p className="readout inline-flex items-center gap-1 text-ink2">
                          <Pin size={11} className="fill-current" aria-hidden="true" /> Kept
                        </p>
                      )}
                    </div>

                    <div className="min-w-0 space-y-4">
                      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                        <h3 id={headingId} className="font-display text-lg sm:text-xl text-ink leading-snug break-words min-w-0">
                          {section.title}
                        </h3>
                        <div className="flex flex-wrap items-center gap-2 shrink-0">
                          {section.reopenable && onReopenProject && (
                            <button
                              type="button"
                              onClick={() => handleReopen(section.jobId)}
                              disabled={!!reopening}
                              className="btn-primary px-3.5 py-2 text-xs"
                              title="Restore this project in the Clip Generator to keep editing subtitles, hooks, effects and dubbing"
                            >
                              {reopening === section.jobId
                                ? <><Loader2 size={14} className="animate-spin" aria-hidden="true" /> Reopening…</>
                                : <><FolderOpen size={14} aria-hidden="true" /> Reopen project</>}
                            </button>
                          )}
                          {!billingEnabled && (
                            <button
                              type="button"
                              onClick={() => handleToggleKeep(section.jobId, section.kept)}
                              disabled={!!keeping}
                              aria-pressed={!!section.kept}
                              className="btn-ghost px-3 py-2 text-xs"
                              title={section.kept
                                ? "Stop keeping this project — it goes back to ageing out automatically"
                                : "Keep this project — exempt it from automatic cleanup"}
                            >
                              {keeping === section.jobId
                                ? <><Loader2 size={14} className="animate-spin" aria-hidden="true" /> Saving…</>
                                : section.kept
                                  ? <><Pin size={14} className="fill-current" aria-hidden="true" /> Kept</>
                                  : <><PinOff size={14} aria-hidden="true" /> Keep</>}
                            </button>
                          )}
                          {!billingEnabled && (
                            <button
                              type="button"
                              onClick={() => handleDelete(section.jobId)}
                              disabled={!!deleting}
                              className="btn-danger px-3 py-2 text-xs"
                              title="Delete this project and all its clips from disk"
                            >
                              {deleting === section.jobId
                                ? <><Loader2 size={14} className="animate-spin" aria-hidden="true" /> Deleting…</>
                                : <><Trash2 size={14} aria-hidden="true" /> Delete</>}
                            </button>
                          )}
                        </div>
                      </div>

                      <ul className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-x-4 gap-y-5" aria-label={`Clips of ${section.title}`}>
                        {section.clips.map((c) => (
                          <li key={c.key}>
                            <figure className="group">
                              <div className="aspect-[9/16] bg-black border border-rule2 rounded-card overflow-hidden">
                                <video
                                  src={c.videoSrc}
                                  controls
                                  preload="metadata"
                                  aria-label={c.title}
                                  className="w-full h-full object-contain"
                                />
                              </div>
                              <figcaption className="mt-2.5 space-y-1">
                                <p className="text-sm text-ink leading-snug line-clamp-2 break-words" title={c.title}>{c.title}</p>
                                <div className="flex flex-wrap items-center justify-between gap-x-2">
                                  {c.date && <span className="readout">{fmtDate(c.date)}</span>}
                                  <a
                                    href={c.downloadHref}
                                    aria-label={`Download ${c.title}`}
                                    className="inline-flex items-center gap-1.5 text-xs text-ink2 hover:text-ink transition-colors py-1 [@media(pointer:coarse)]:min-h-[44px]"
                                  >
                                    <Download size={14} aria-hidden="true" /> Download
                                  </a>
                                </div>
                              </figcaption>
                            </figure>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </article>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
