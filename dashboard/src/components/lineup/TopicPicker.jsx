import { useId, useState } from 'react';
import { AlertCircle, Loader2, RotateCcw, Check } from 'lucide-react';
import Modal from '../ui/Modal';
import { TopicSwatch } from './TopicTag';
import { TOPICS, topicLabel } from '../../lib/topics';
import { apiJson } from '../../lib/api';

// The channel's niche first (solid swatches), then the topics outside it (hollow) and "other".
const GROUPS = [
  { id: 'niche', label: 'Your niche', topics: TOPICS.filter((t) => !t.offNiche && t.id !== 'other') },
  { id: 'off', label: 'Outside your niche', topics: TOPICS.filter((t) => t.offNiche || t.id === 'other') },
];

/**
 * Correct a clip's topic: one click on the right one (POST /api/lineup/category), or back to the AI's
 * choice (category null). The server answers with the updated clip.
 */
export default function TopicPicker({ clip, onClose, onSaved }) {
  const uid = useId();
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState('');
  if (!clip) return null;

  const save = async (category) => {
    if (busy) return;
    setBusy(category || 'ai');
    setError('');
    try {
      const res = await apiJson('/api/lineup/category', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: clip.job_id, clip_index: clip.clip_index, category }),
      });
      onSaved?.(res?.clip || res);
      onClose();
    } catch (e) {
      setError(`Could not change the topic: ${e.detail || e.message}`);
    } finally {
      setBusy(null);
    }
  };

  const manual = clip.category_source === 'manual';
  return (
    <Modal isOpen onClose={onClose} eyebrow="Topic" title="What is this clip about?" size="md">
      <div className="space-y-4">
        <p className="text-sm text-ink2 line-clamp-2 break-words">{clip.title}</p>
        {manual && clip.ai_category && (
          <p className="text-xs text-muted">The AI had chosen: <span className="text-ink2">{topicLabel(clip.ai_category)}</span></p>
        )}
        {GROUPS.map((g) => (
          <div key={g.id} className="space-y-2">
            <p className="readout" id={`${uid}-${g.id}`}>{g.label}</p>
            <div className="grid grid-cols-1 min-[420px]:grid-cols-2 gap-1.5" role="group" aria-labelledby={`${uid}-${g.id}`}>
              {g.topics.map((t) => {
                const current = clip.category === t.id;
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => (current ? onClose() : save(t.id))}
                    aria-pressed={current}
                    disabled={!!busy}
                    className={`min-h-[44px] px-3 py-2 rounded-input border text-left text-sm flex items-center gap-2.5 transition-colors
                      ${current ? 'border-ink bg-paper3 text-ink' : 'border-rule2 bg-paper2 text-ink2 hover:border-ink hover:text-ink'}`}
                  >
                    <TopicSwatch id={t.id} size={12} />
                    <span className="flex-1 truncate">{topicLabel(t.id, current ? clip.category_label : null)}</span>
                    {busy === t.id && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
                    {current && busy !== t.id && <Check size={14} className="text-ink" aria-hidden="true" />}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
        {manual && (
          <button type="button" onClick={() => save(null)} disabled={!!busy} className="btn-quiet px-3 py-2 text-xs">
            {busy === 'ai' ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <RotateCcw size={13} aria-hidden="true" />}
            Back to the AI's choice
          </button>
        )}
        {error && (
          <p role="alert" className="flex items-start gap-2 text-sm text-danger break-words">
            <AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden="true" /> {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
