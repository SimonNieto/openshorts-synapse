import { Loader2, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { DATE_LOCALE, SCORE_SOURCES, STAYED_LINE, aiScore, fmtPct, realStayed, scoreSource, spectatorScore } from '../../lib/lineup';

// A 0-100 bar. `line`: the 63 % mark, drawn only under a REAL "Stayed to watch" (a score is a rank, not a
// Studio percentage: comparing it to that line would be a promise it can't keep).
function Bar({ value, line }) {
  const pct = Math.max(0, Math.min(100, value));
  const strong = line ? value >= STAYED_LINE : false;
  return (
    <span className="relative mt-2 block h-1.5 rounded-full bg-paper3" aria-hidden="true">
      <span className={`absolute inset-y-0 left-0 rounded-full ${strong ? 'bg-ink' : 'bg-ink2/70'}`} style={{ width: `${pct}%` }} />
      {line && <span className="absolute -top-1 -bottom-1 w-px bg-muted" style={{ left: `${STAYED_LINE}%` }} />}
    </span>
  );
}

/**
 * The clip's headline number, with where it comes from in plain words (`rank_score_source`):
 *  - published and measured: the REAL "Stayed to watch" (63 % line), the scores after it, small;
 *  - watched by the spectator: its score out of 100, the AI's pick score after it;
 *  - otherwise the AI's pick score — "not tested yet" when the spectator is on.
 */
export default function ScoreBlock({ clip, running = false, size = 'lg', spectatorOn = false }) {
  const source = scoreSource(clip, spectatorOn);
  const stayed = realStayed(clip);
  const score = spectatorScore(clip);
  const ai = aiScore(clip);
  const big = size === 'lg' ? 'text-[2.75rem]' : 'text-[2rem]';
  const views = Number.isFinite(clip.stats?.views) ? ` · ${clip.stats.views.toLocaleString(DATE_LOCALE)} views` : '';

  if (source === 'stayed') {
    const above = stayed >= STAYED_LINE;
    // (5-oct-2026) Spectator test kept for later at the user's request: its score only when it is on.
    const second = spectatorOn && score !== null ? `Spectator ${score}` : ai !== null ? `AI pick score ${ai}` : '';
    return (
      <div className="min-w-0">
        <p className="readout">{SCORE_SOURCES.stayed}</p>
        <p className={`font-quote text-ink leading-none mt-1.5 ${big}`}>{fmtPct(stayed)}</p>
        <Bar value={stayed} line />
        <p className={`mt-1.5 text-[11px] leading-snug flex items-center gap-1 ${above ? 'text-ok' : 'text-ink2'}`}>
          {above ? <ArrowUpRight size={12} aria-hidden="true" /> : <ArrowDownRight size={12} aria-hidden="true" />}
          {above ? 'Above' : 'Below'} the {STAYED_LINE}% line
        </p>
        {(second || views) && <p className="readout mt-1">{second}{views}</p>}
      </div>
    );
  }

  if (spectatorOn && running) {
    return (
      <div className="min-w-0">
        <p className="readout">{SCORE_SOURCES.jury}</p>
        <p className="mt-2 text-sm text-ink2 flex items-center gap-2">
          <Loader2 size={15} className="animate-spin" aria-hidden="true" /> Watching…
        </p>
      </div>
    );
  }

  const value = source === 'jury' ? score : ai;
  const notes = [
    clip.status === 'published' && 'Studio number not in yet',
    source === 'jury' && ai !== null && `AI pick score ${ai}`,
    source === 'ai' && spectatorOn && 'Not tested by the spectator yet',
    source === 'ai' && ai === null && 'No score from the AI',
  ].filter(Boolean);
  return (
    <div className="min-w-0">
      <p className="readout">{SCORE_SOURCES[source]}</p>
      <p className={`font-quote leading-none mt-1.5 ${big} ${value === null ? 'text-muted' : 'text-ink'}`}>
        {value === null
          ? <><span aria-hidden="true">—</span><span className="sr-only">none</span></>
          : <>{value}<span className="sr-only"> out of 100</span></>}
      </p>
      {value !== null && <Bar value={value} line={false} />}
      {notes.map((n) => <p key={n} className="mt-1.5 text-[11px] text-muted leading-snug">{n}</p>)}
    </div>
  );
}
