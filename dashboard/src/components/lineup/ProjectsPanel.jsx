import { useState } from 'react';
import { ChevronDown, HardDrive, Trash2, Loader2, AlertTriangle, AlertCircle } from 'lucide-react';
import Modal from '../ui/Modal';
import { apiFetch } from '../../lib/api';
import { ageLabel, fmtBytes } from '../../lib/lineup';

/**
 * Projects on this computer (5-oct-2026). Nothing is deleted on its own any more: the user keeps what she
 * wants and deletes a project here, by hand — after a confirmation that says exactly what goes
 * (DELETE /api/local-projects/{job_id}, irreversible). A project with clips still scheduled to go out
 * can't be deleted: Upload-Post's posts and the calendar still point at those clips.
 *
 * projects: lib/lineup.js projectsOf(); disk: lib/lineup.js diskOf() or null.
 */
export default function ProjectsPanel({ projects, disk, onDeleted }) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState('');

  const total = projects.reduce((s, p) => s + (p.size || 0), 0);
  const used = disk?.used ?? (total || null);

  const doDelete = async () => {
    if (!confirm || deleting) return;
    setDeleting(true);
    setError('');
    try {
      const res = await apiFetch(`/api/local-projects/${confirm.job_id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(await res.text());
      setConfirm(null);
      onDeleted?.(confirm.job_id);
    } catch (e) {
      setError(`Could not delete this project: ${String(e.message || e).slice(0, 160)}`);
    } finally {
      setDeleting(false);
    }
  };

  const consequence = (p) => (p.notPublished > 0
    ? `Deletes ${p.clips} clip${p.clips === 1 ? '' : 's'} from disk, including ${p.notPublished} not published yet.`
    : `Deletes ${p.clips} clip${p.clips === 1 ? '' : 's'} from disk — all already published.`);

  return (
    <section aria-labelledby="lu-projects-title" className="border-t border-rule pt-5">
      <h3 id="lu-projects-title" className="m-0">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls="lu-projects-body"
          className="w-full flex flex-wrap items-center gap-x-3 gap-y-1 text-left rounded-input py-2 min-h-[44px] group"
        >
          <HardDrive size={16} className="text-muted" aria-hidden="true" />
          <span className="font-display text-base text-ink">Projects on this computer</span>
          <span className="readout">
            {projects.length} project{projects.length === 1 ? '' : 's'}
            {used ? ` · ${fmtBytes(used)}` : ''}
            {disk?.sources ? ` · sources ${fmtBytes(disk.sources)}` : ''}
            {disk?.free != null ? ` · ${fmtBytes(disk.free)} free` : ''}
          </span>
          <ChevronDown size={16} className={`ml-auto text-muted transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
        </button>
      </h3>

      {open && (
        <div id="lu-projects-body" className="mt-3 space-y-3">
          <p className="text-sm text-muted">
            Nothing is deleted on its own: keep what you want, delete a project here when it is too old.
          </p>
          {error && (
            <p role="alert" className="flex items-start gap-2 text-sm text-danger break-words">
              <AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden="true" /> {error}
            </p>
          )}
          {projects.length === 0 && <p className="tray p-4 text-sm text-muted">No project on this computer.</p>}
          <ul className="space-y-2">
            {projects.map((p) => {
              const blocked = p.scheduled > 0;
              const why = `lu-proj-why-${p.job_id}`;
              return (
                <li key={p.job_id} className="card p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center gap-3">
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="text-sm text-ink break-words">{p.title}</p>
                    <p className="readout normal-case tracking-[0.04em]">
                      {[ageLabel(p.age), fmtBytes(p.size), `${p.clips} clip${p.clips === 1 ? '' : 's'}`].filter(Boolean).join(' · ')}
                    </p>
                    <p className="text-xs text-muted">
                      {p.published} published · {p.scheduled} scheduled · {p.available} available
                    </p>
                    {blocked && (
                      <p id={why} className="text-xs text-ink2 flex items-start gap-1.5">
                        <AlertTriangle size={13} className="text-warn mt-0.5 shrink-0" aria-hidden="true" />
                        <span>
                          {p.scheduled} clip{p.scheduled === 1 ? ' is' : 's are'} scheduled to go out: their posts still need
                          these files. Delete it once they are out (or cancel them in Publish plan).
                        </span>
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => setConfirm(p)}
                    disabled={blocked}
                    aria-describedby={blocked ? why : undefined}
                    className="btn-danger px-3 py-2 text-xs shrink-0 self-start sm:self-center"
                  >
                    <Trash2 size={13} aria-hidden="true" /> Delete project
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <Modal
        isOpen={!!confirm}
        onClose={deleting ? undefined : () => { setConfirm(null); setError(''); }}
        dismissOnOverlay={!deleting}
        eyebrow="Can't be undone"
        title="Delete this project?"
        size="md"
        footer={(
          <div className="flex flex-col-reverse min-[420px]:flex-row min-[420px]:justify-end gap-2">
            <button type="button" onClick={() => setConfirm(null)} disabled={deleting} className="btn-ghost px-4 py-2 text-sm">Keep it</button>
            <button type="button" onClick={doDelete} disabled={deleting} className="btn-danger px-4 py-2 text-sm">
              {deleting ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Trash2 size={14} aria-hidden="true" />}
              Delete for good
            </button>
          </div>
        )}
      >
        {confirm && (
          <div className="space-y-3">
            <p className="text-sm text-ink break-words">{confirm.title}</p>
            <p className="text-sm text-ink2 flex items-start gap-2">
              <AlertTriangle size={15} className="text-warn mt-0.5 shrink-0" aria-hidden="true" />
              <span>{consequence(confirm)} The video files go too{confirm.size ? ` (${fmtBytes(confirm.size)})` : ''}. This can't be undone.</span>
            </p>
            {error && (
              <p role="alert" className="flex items-start gap-2 text-sm text-danger break-words">
                <AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden="true" /> {error}
              </p>
            )}
          </div>
        )}
      </Modal>
    </section>
  );
}
