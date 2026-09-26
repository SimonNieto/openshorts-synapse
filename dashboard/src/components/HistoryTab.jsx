import React, { useState, useEffect, useMemo } from 'react';
import { Loader2, Download, Film, FolderOpen, Trash2, Pin, PinOff } from 'lucide-react';
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
    return <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brass" /></div>;
  }

  return (
    <div className="h-full overflow-y-auto p-8 max-w-5xl mx-auto animate-fade">
      <p className="eyebrow mb-1.5">06 · HISTORY</p>
      <h1 className="font-display lowercase text-2xl text-ink mb-2">Your library</h1>
      <p className="text-muted text-sm mb-8 lowercase">
        {billingEnabled
          ? "All the shorts you've generated, saved while your plan is active. Kept for 7 days after your plan ends. Reopen a project to keep editing its clips."
          : "Recent projects still on this machine's disk (cleaned up automatically after a while). Pin one to keep it around, or reopen it to keep editing its clips."}
      </p>

      {error && <p className="text-danger text-sm">{error}</p>}
      {reopenError && <p className="text-danger text-sm mb-4">{reopenError}</p>}

      {sections.length === 0 && (
        <div className="text-center py-20 text-muted">
          <Film size={40} className="mx-auto mb-4 text-muted" />
          <p className="lowercase">No videos yet. Generate your first short from the Clip Generator.</p>
        </div>
      )}

      <div className="space-y-10">
        {sections.map((section) => (
          <section key={section.jobId}>
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4 pb-2 border-b border-rule">
              <div className="min-w-0">
                <p className="text-sm text-ink font-medium truncate" title={section.title}>
                  {section.title}
                </p>
                <p className="readout mt-0.5">
                  {fmtDate(section.date)} · {section.clips.length} clip{section.clips.length === 1 ? '' : 's'}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {!billingEnabled && (
                  <button
                    onClick={() => handleToggleKeep(section.jobId, section.kept)}
                    disabled={!!keeping}
                    className={`btn-ghost px-3 py-2 text-xs shrink-0 ${section.kept ? 'text-brass' : ''}`}
                    title={section.kept
                      ? "Stop keeping this project — it goes back to ageing out automatically"
                      : "Keep this project — exempt it from automatic cleanup"}
                  >
                    {keeping === section.jobId
                      ? <><Loader2 size={14} className="animate-spin" /> …</>
                      : section.kept
                        ? <><Pin size={14} className="fill-current" /> kept</>
                        : <><PinOff size={14} /> keep</>}
                  </button>
                )}
                {section.reopenable && onReopenProject && (
                  <button
                    onClick={() => handleReopen(section.jobId)}
                    disabled={!!reopening}
                    className="btn-ghost px-3 py-2 text-xs shrink-0"
                    title="Restore this project in the Clip Generator to keep editing subtitles, hooks, effects and dubbing"
                  >
                    {reopening === section.jobId
                      ? <><Loader2 size={14} className="animate-spin" /> reopening…</>
                      : <><FolderOpen size={14} /> reopen project</>}
                  </button>
                )}
                {!billingEnabled && (
                  <button
                    onClick={() => handleDelete(section.jobId)}
                    disabled={!!deleting}
                    className="btn-ghost px-3 py-2 text-xs shrink-0 text-danger hover:text-danger"
                    title="Delete this project and all its clips from disk"
                  >
                    {deleting === section.jobId
                      ? <><Loader2 size={14} className="animate-spin" /> deleting…</>
                      : <><Trash2 size={14} /> delete</>}
                  </button>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
              {section.clips.map((c) => (
                <div key={c.key} className="card card-hover overflow-hidden group">
                  <div className="aspect-[9/16] bg-black">
                    <video src={c.videoSrc} controls preload="metadata" className="w-full h-full object-contain" />
                  </div>
                  <div className="p-3">
                    <p className="text-sm text-ink font-medium line-clamp-2 mb-1" title={c.title}>{c.title}</p>
                    <div className="flex items-center justify-between">
                      <span className="readout">{fmtDate(c.date)}</span>
                      <a href={c.downloadHref} className="text-micro font-mono uppercase text-brass hover:text-ink flex items-center gap-1 transition-colors" title="Download">
                        <Download size={14} /> Download
                      </a>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
