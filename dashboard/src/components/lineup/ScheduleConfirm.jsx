import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Calendar, CheckCircle, AlertCircle, Loader2, Video, Instagram, Youtube } from 'lucide-react';
import Modal from '../ui/Modal';
import SegmentedControl from '../ui/SegmentedControl';
import TikTokDraftNotice from '../TikTokDraftNotice';
import TopicTag from './TopicTag';
import { apiFetch } from '../../lib/api';
import { userTimezone } from '../../lib/postSlots';
import { loadSchedulePrefs, saveSchedulePrefs, savedNicheChoice, socialPostBody } from '../../lib/schedulePost';
import { DEFAULT_PLATFORMS, fmtDay, slotPassed } from '../../lib/lineup';

const PLATFORM_OPTIONS = [
  { value: 'tiktok', label: 'TikTok', icon: <Video size={14} /> },
  { value: 'instagram', label: 'Instagram', icon: <Instagram size={14} /> },
  { value: 'youtube', label: 'YouTube', icon: <Youtube size={14} /> },
];

/**
 * The last word before anything is sent: every post with its day, time, account and niche, the
 * platforms, and why a post can't go (no niche confirmed on its project, a time already passed).
 * "Schedule" then sends POST /api/social/post clip by clip — exactly ScheduleComposer's request
 * (lib/schedulePost.js), with each clip's OWN project account and niche, as in the Publish plan.
 *
 * items: [{ date, time, clip, project }] — project = { niche, upload_profile } of the clip's project (the
 * catalogue sends them on each clip; /api/local-projects otherwise), null when unknown.
 */
export default function ScheduleConfirm({ isOpen, onClose, items, uploadPostKey, uploadUserId, isManaged, onDone, onOpenPlan }) {
  const [platforms, setPlatforms] = useState(() => loadSchedulePrefs().platforms || DEFAULT_PLATFORMS);
  const [sending, setSending] = useState(false);
  const [results, setResults] = useState({});
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    if (!isOpen) return undefined;
    setResults({});
    setNow(new Date());
    setPlatforms(loadSchedulePrefs().platforms || DEFAULT_PLATFORMS);
    const t = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(t);
  }, [isOpen]);

  const rows = useMemo(() => (items || []).map((it) => {
    const choice = savedNicheChoice(it.project, uploadUserId);
    const blocker = !choice
      ? "No niche confirmed for this clip's project: confirm it once in Publish plan."
      : slotPassed(it, now)
        ? 'This time has passed — suggest the order again.'
        : '';
    return { ...it, choice, blocker, key: `${it.clip.job_id}:${it.clip.clip_index}` };
  }), [items, uploadUserId, now]);

  const sendable = rows.filter((r) => !r.blocker);
  const canPost = !!(isManaged || (uploadPostKey && sendable.every((r) => r.choice?.profile)));
  const done = Object.keys(results).length > 0 && !sending;
  const ready = canPost && sendable.length > 0 && platforms.length > 0 && !sending && !done;
  const okCount = Object.values(results).filter((r) => r.ok).length;
  const failed = Object.values(results).filter((r) => !r.ok);

  const handleSchedule = async () => {
    if (!ready) return;
    saveSchedulePrefs({ ...loadSchedulePrefs(), platforms });
    setSending(true);
    setResults({});
    const timezone = userTimezone();
    for (const r of sendable) {
      try {
        const res = await apiFetch('/api/social/post', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(socialPostBody({
            jobId: r.clip.job_id,
            clipIndex: r.clip.clip_index,
            uploadPostKey,
            profile: r.choice.profile,
            platforms,
            slot: { date: r.date, time: r.time },
            niche: r.choice.niche,
            timezone,
          })),
        });
        if (!res.ok) throw new Error(await res.text());
        setResults((prev) => ({ ...prev, [r.key]: { ok: true } }));
      } catch (e) {
        setResults((prev) => ({ ...prev, [r.key]: { ok: false, error: e.message } }));
      }
    }
    setSending(false);
    onDone?.();
  };

  const n = sendable.length;
  const blocked = rows.length - n;
  const status = !canPost
    ? (isManaged || uploadPostKey ? 'Some posts have no Upload-Post account.' : 'Set your Upload-Post key in Settings to schedule.')
    : sending
      ? `Scheduling ${Object.keys(results).length + 1} of ${n}…`
      : done
        ? (failed.length
          ? <span className="text-danger">{okCount} scheduled, {failed.length} failed: {String(failed[0].error || '').slice(0, 140)}</span>
          : <span className="text-ok inline-flex items-center gap-1"><CheckCircle size={13} aria-hidden="true" /> {okCount} scheduled on Upload-Post — the PC can be off.</span>)
        : `${blocked ? `${n} will be sent, ${blocked} can't go (see above). ` : ''}Posts go out on their own at these times — the PC can be off.`;

  const footer = (
    <div className="flex flex-col sm:flex-row sm:items-center gap-3">
      <p className="text-xs text-muted flex-1" aria-live="polite">{status}</p>
      <div className="flex flex-col-reverse min-[420px]:flex-row gap-2">
        <button type="button" onClick={onClose} disabled={sending} className="btn-ghost px-4 py-2 text-sm">
          {done ? 'Close' : 'Cancel'}
        </button>
        {!done && (
          <button type="button" onClick={handleSchedule} disabled={!ready} className="btn-accent px-4 py-2.5 text-sm">
            {sending ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Calendar size={14} aria-hidden="true" />}
            {sending ? 'Scheduling…' : `Schedule ${n} on Upload-Post`}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <Modal
      isOpen={isOpen}
      onClose={sending ? undefined : onClose}
      dismissOnOverlay={!sending}
      hideClose={sending}
      eyebrow="Check before sending"
      title={`Schedule ${rows.length} post${rows.length === 1 ? '' : 's'} on Upload-Post?`}
      size="lg"
      footer={footer}
    >
      <div className="space-y-5">
        <p className="text-sm text-ink2">
          Each clip goes to Upload-Post with its own project's account and niche, at the time shown.
          Nothing is sent before you press “Schedule”.
        </p>
        <fieldset className="min-w-0" disabled={sending || done}>
          <legend className="readout mb-2">Platforms</legend>
          <SegmentedControl multi columns={3} options={PLATFORM_OPTIONS} value={platforms} onChange={setPlatforms} />
        </fieldset>
        {platforms.includes('tiktok') && <TikTokDraftNotice />}
        <div>
          <p className="readout mb-2">Goes out · times in {userTimezone()}</p>
          <ol className="space-y-2">
            {rows.map((r) => {
              const res = results[r.key];
              return (
                <li key={r.key} className={`tray p-3 flex items-start gap-3 ${r.blocker ? 'opacity-80' : ''}`}>
                  <div className="w-[5.5rem] shrink-0">
                    <p className="text-sm text-ink">{fmtDay(r.date)}</p>
                    <p className="readout !text-ink2">{r.time}</p>
                  </div>
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="text-sm text-ink leading-snug line-clamp-2 break-words">{r.clip.title}</p>
                    <TopicTag id={r.clip.category} label={r.clip.category_label} source={r.clip.category_source} />
                    {r.choice && (
                      <p className="readout normal-case tracking-[0.04em]">
                        Account {r.choice.profile || '—'} · niche {r.choice.niche}
                      </p>
                    )}
                    {r.blocker && (
                      <p className="text-xs text-warn flex items-start gap-1.5">
                        <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                        <span>
                          {r.blocker} Not sent.
                          {!r.choice && onOpenPlan && (
                            <> <button type="button" onClick={onOpenPlan} className="underline underline-offset-2 hover:text-ink">Open Publish plan</button></>
                          )}
                        </span>
                      </p>
                    )}
                  </div>
                  {res && (
                    <span className="shrink-0 pt-0.5">
                      {res.ok
                        ? <><CheckCircle size={18} className="text-ok" aria-hidden="true" /><span className="sr-only">Scheduled</span></>
                        : <><AlertCircle size={18} className="text-danger" aria-hidden="true" /><span className="sr-only">Failed</span></>}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </Modal>
  );
}
