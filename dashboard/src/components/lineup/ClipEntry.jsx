import { useId } from 'react';
import { Check, Clock, CalendarPlus } from 'lucide-react';
import ClipThumb from './ClipThumb';
import TopicTag from './TopicTag';
import ScoreBlock from './ScoreBlock';
import SpectatorDetails, { SpectatorLine } from './SpectatorNotes';
import { ageLabel, episodeFull, episodeShort, fmtDay, fmtDuration, stateOf } from '../../lib/lineup';

// Where the clip stands: free to plan, in the suggested order, on Upload-Post this week or later, or out.
function StatusLine({ clip, planned, weekTo }) {
  if (clip.status === 'published') {
    const when = clip.published_at ? fmtDay(String(clip.published_at).slice(0, 10), { day: 'numeric', month: 'short' }) : '';
    return (
      <span className="inline-flex items-center gap-1 text-xs text-ink2">
        <Check size={13} className="text-ok" aria-hidden="true" /> Published{when && ` ${when}`}
      </span>
    );
  }
  if (clip.status === 'scheduled') {
    const s = (clip.slots || [])[0];
    return (
      <span className="inline-flex items-center gap-1 text-xs text-ink2">
        <Clock size={13} className="text-muted" aria-hidden="true" />
        {stateOf(clip, weekTo) === 'later' ? 'Scheduled later' : 'Scheduled this week'}{s ? ` · ${fmtDay(s.date)} · ${s.time}` : ''}
        {(clip.slots || []).length > 1 && <span className="text-muted"> +{clip.slots.length - 1}</span>}
      </span>
    );
  }
  if (planned) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-ink">
        <CalendarPlus size={13} className="text-vermilion" aria-hidden="true" /> Suggested {fmtDay(planned.date)} · {planned.time}
      </span>
    );
  }
  return <span className="text-xs text-muted">Available</span>;
}

function SelectBox({ clip, selected, onToggle }) {
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer text-xs text-ink2 hover:text-ink rounded-input px-1 -mx-1 min-h-[32px] [@media(pointer:coarse)]:min-h-[44px]">
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        className="w-4 h-4 cursor-pointer accent-[color:var(--color-accent)]"
      />
      <span>{selected ? 'Selected' : 'Select'}<span className="sr-only"> “{clip.title}”</span></span>
    </label>
  );
}

/**
 * One clip of the pool. `layout="row"`: a line of the ranking (rank, picture, words, the number on the
 * right). `layout="card"`: a card of the grid (picture left, everything else right).
 */
export default function ClipEntry({
  clip, layout = 'row', rank, selectable, selected, onToggle, onPlay, onEditTopic,
  onRetest, retesting, running, planned, weekTo, spectatorOn = false,
}) {
  const titleId = useId();
  // The scores live in ScoreBlock (with where each comes from); this line is the episode, the length and,
  // quietly, how old the project is (nothing is deleted on its own: the Projects panel does it by hand).
  const meta = [episodeShort(clip), fmtDuration(clip.duration), ageLabel(clip.project_age_days)].filter(Boolean).join(' · ');
  const ring = selected ? 'border-vermilion/60 shadow-print-accent' : '';

  const words = (
    <>
      <h4 id={titleId} className="text-sm sm:text-[15px] font-medium text-ink leading-snug line-clamp-2 break-words">{clip.title}</h4>
      {clip.hook && <p className="text-xs text-muted leading-snug line-clamp-2 break-words">Hook: <span className="text-ink2">“{clip.hook}”</span></p>}
      {clip.hook_line && (
        <p className="text-xs text-muted leading-snug line-clamp-2 break-words" title={clip.hook_line}>Opens on: “{clip.hook_line}”</p>
      )}
      {meta && <p className="readout normal-case tracking-[0.06em] truncate" title={episodeFull(clip)}>{meta}</p>}
    </>
  );
  // (5-oct-2026) Spectator test kept for later at the user's request: shown only when the API turns it on.
  // In a card the verdict and the fix are clamped; the details then show them whole.
  const spectator = spectatorOn ? (
    <>
      <SpectatorLine jury={clip.jury} compact={layout === 'card'} />
      <SpectatorDetails jury={clip.jury} onRetest={onRetest} retesting={retesting} full={layout === 'card'} />
    </>
  ) : null;

  if (layout === 'card') {
    return (
      <article aria-labelledby={titleId} className={`card p-3 flex gap-3 min-w-0 transition-shadow ${ring}`}>
        <div className="w-28 sm:w-32 shrink-0">
          <ClipThumb clip={clip} onPlay={onPlay} className="w-full" />
          {Number.isFinite(rank) && <p className="readout mt-2 text-center">Rank {rank}</p>}
        </div>
        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <TopicTag id={clip.category} label={clip.category_label} source={clip.category_source} onEdit={onEditTopic} />
            {selectable && <SelectBox clip={clip} selected={selected} onToggle={onToggle} />}
          </div>
          {words}
          <StatusLine clip={clip} planned={planned} weekTo={weekTo} />
          <div className="pt-2 border-t border-rule">
            <ScoreBlock clip={clip} running={running} size="md" spectatorOn={spectatorOn} />
          </div>
          {spectator}
        </div>
      </article>
    );
  }

  return (
    <article
      aria-labelledby={titleId}
      className={`card p-3 sm:p-4 grid gap-3 sm:gap-4 grid-cols-[5.5rem_minmax(0,1fr)] md:grid-cols-[2.5rem_7rem_minmax(0,1fr)_12rem] items-start transition-shadow ${ring}`}
    >
      <p className="hidden md:block font-quote text-[2.25rem] leading-none text-muted text-right pt-1" aria-hidden={!Number.isFinite(rank)}>
        {Number.isFinite(rank) ? <><span className="sr-only">Rank </span>{rank}</> : '—'}
      </p>
      <ClipThumb clip={clip} onPlay={onPlay} className="w-[5.5rem] md:w-28" />
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          {Number.isFinite(rank) && <span className="md:hidden readout !text-ink2">Rank {rank}</span>}
          <TopicTag id={clip.category} label={clip.category_label} source={clip.category_source} onEdit={onEditTopic} />
          <StatusLine clip={clip} planned={planned} weekTo={weekTo} />
          {selectable && <span className="ml-auto"><SelectBox clip={clip} selected={selected} onToggle={onToggle} /></span>}
        </div>
        {words}
        {spectator}
      </div>
      <div className="col-span-2 md:col-span-1 md:border-l md:border-rule md:pl-4 pt-3 md:pt-0 border-t border-rule md:border-t-0">
        <ScoreBlock clip={clip} running={running} spectatorOn={spectatorOn} />
      </div>
    </article>
  );
}
