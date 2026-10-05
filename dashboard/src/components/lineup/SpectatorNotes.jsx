import { Check, X, HelpCircle, Lightbulb, RotateCcw, Loader2 } from 'lucide-react';
import { CRITERIA, STOP_LABEL, fmtDuration } from '../../lib/lineup';

// (5-oct-2026) What the spectator (hook jury, hook_jury.py, contract C1) said about one clip, in its own
// words. Shown only when the API turns the spectator on.

function Mark({ value }) {
  if (value === true) return <><Check size={13} className="text-ok shrink-0 mt-0.5" aria-hidden="true" /><span className="sr-only">yes: </span></>;
  if (value === false) return <><X size={13} className="text-warn shrink-0 mt-0.5" aria-hidden="true" /><span className="sr-only">no: </span></>;
  return <><HelpCircle size={13} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /><span className="sr-only">not sure: </span></>;
}

// Would it stop the scroll: a word, with a mark that doesn't lean on colour alone.
function StopWord({ stop }) {
  const word = STOP_LABEL[stop];
  if (!word) return null;
  const cls = stop === 'yes' ? 'text-ok' : stop === 'no' ? 'text-warn' : 'text-ink';
  return <span className={cls}>{word}</span>;
}

/**
 * The short line, always visible: the verdict, would it stop scrolling, how it felt, the head-to-heads,
 * and the fix ("Start at …") — the one thing to do about a weak opening.
 */
export function SpectatorLine({ jury, compact = false }) {
  if (!jury) return null;
  const games = jury.rank_check && Number.isFinite(jury.rank_check.games) && jury.rank_check.games > 0;
  return (
    <div className="space-y-1.5">
      {jury.verdict && (
        <p className={`text-ink2 leading-snug ${compact ? 'text-xs line-clamp-3' : 'text-sm'}`} title={compact ? jury.verdict : undefined}>
          {jury.verdict}
        </p>
      )}
      <p className="text-xs text-muted leading-relaxed">
        {STOP_LABEL[jury.stop] && <span>Would stop scrolling: <StopWord stop={jury.stop} /></span>}
        {jury.feeling && <span>{STOP_LABEL[jury.stop] && <span aria-hidden="true"> · </span>}Felt: <span className="text-ink2">{jury.feeling}</span></span>}
        {games && <span><span aria-hidden="true"> · </span>Verified in head-to-heads: <span className="text-ink2">{jury.rank_check.wins} wins / {jury.rank_check.games}</span></span>}
      </p>
      {jury.fix && (
        <p className={`text-xs text-ink flex items-start gap-1.5 ${compact ? 'line-clamp-3' : ''}`}>
          <Lightbulb size={13} className="text-muted shrink-0 mt-0.5" aria-hidden="true" />
          <span><span className="text-muted">To fix: </span>{jury.fix}</span>
        </p>
      )}
    </div>
  );
}

export default function SpectatorDetails({ jury, onRetest, retesting = false, full = false }) {
  if (!jury) return null;
  const votes = Array.isArray(jury.votes) ? jury.votes.filter((v) => Number.isFinite(v)) : [];
  const extra = [
    jury.topic_guess && ['Thought it was about', jury.topic_guess],
    jury.hook_problem && ['Hook problem', jury.hook_problem],
    jury.true_hook && ['A truer hook', jury.true_hook],
    jury.better_start && ['Better start', `“${jury.better_start}”${Number.isFinite(jury.better_start_at) ? ` (at ${fmtDuration(jury.better_start_at)})` : ''}`],
  ].filter(Boolean);
  return (
    <details className="group">
      <summary className="cursor-pointer select-none text-xs text-ink2 hover:text-ink inline-flex items-center gap-1 rounded-input py-1 [@media(pointer:coarse)]:min-h-[44px]">
        <span className="group-open:hidden">What the spectator checked</span>
        <span className="hidden group-open:inline">Hide the details</span>
      </summary>
      <div className="mt-2 tray p-3 space-y-3">
        {full && jury.verdict && <p className="text-xs text-ink2 leading-relaxed">{jury.verdict}</p>}
        {full && jury.fix && <p className="text-xs text-ink"><span className="text-muted">To fix: </span>{jury.fix}</p>}
        <ul className="space-y-1.5" aria-label="What the spectator checked in the first seconds">
          {CRITERIA.map(([key, label]) => (
            <li key={key} className="flex items-start gap-2 text-xs text-ink2">
              <Mark value={jury.criteria?.[key] ?? null} />
              <span>{label}</span>
            </li>
          ))}
          <li className="flex items-start gap-2 text-xs text-ink2">
            <Mark value={jury.hook_true ?? null} />
            <span>The hook keeps its promise over the whole clip</span>
          </li>
        </ul>
        {extra.length > 0 && (
          <dl className="space-y-1 text-xs">
            {extra.map(([k, v]) => (
              <div key={k}>
                <dt className="inline text-muted">{k}: </dt>
                <dd className="inline text-ink2">{v}</dd>
              </div>
            ))}
          </dl>
        )}
        <p className="readout leading-relaxed">
          {votes.length > 0 && <>Votes {votes.join(' · ')}{Number.isFinite(jury.spread) && <> (spread {jury.spread})</>}</>}
          {Number.isFinite(jury.score_solo) && jury.score_solo !== jury.score && <> · alone {jury.score_solo}</>}
          {Number.isFinite(jury.rank_check?.rank_score) && <> · head-to-head {Math.round(jury.rank_check.rank_score)}</>}
          {jury.at && <> · {String(jury.at).slice(0, 16).replace('T', ' ')}</>}
        </p>
        {onRetest && (
          <button type="button" onClick={onRetest} disabled={retesting} className="btn-quiet px-3 py-1.5 text-xs">
            {retesting ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : <RotateCcw size={12} aria-hidden="true" />}
            Test this opening again
          </button>
        )}
      </div>
    </details>
  );
}
