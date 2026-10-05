import { useState } from 'react';
import { AlertTriangle, Check, Clock, CalendarPlus, ChevronUp, ChevronDown, X, CheckCircle2 } from 'lucide-react';
import ClipThumb from './ClipThumb';
import TopicTag, { TopicSwatch } from './TopicTag';
import { topicFill, topicLabel, topicOrder } from '../../lib/topics';
import { dayLabel, daysBetween, episodeShort, fmtDay, fmtPct, newAlerts, realStayed, titleFormLabel } from '../../lib/lineup';

const KIND_WORD = { published: 'published', scheduled: 'scheduled', proposed: 'suggested, not sent yet' };

const iconBtn = 'w-8 h-8 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-input flex items-center justify-center text-muted hover:text-ink hover:bg-paper3 transition-colors disabled:opacity-30 disabled:hover:bg-transparent disabled:cursor-not-allowed';

// One post of the week: a large square picture (face and set: two posts that look alike show at a
// glance), the topic's colour under it (solid, or an outline for a topic outside the niche), the time, the
// title, where it stands. A suggested post also says why it is there, and can be taken out.
function Tile({ clip, item, kind, lit, onOpen, onRemove }) {
  const title = clip?.title || item.title || item.ref;
  const stayed = clip ? realStayed(clip) : null;
  const state = kind === 'published'
    ? <><Check size={12} className="text-ok" aria-hidden="true" /> Published{stayed !== null && <> · stayed {fmtPct(stayed)}</>}</>
    : kind === 'proposed'
      ? <><CalendarPlus size={12} className="text-vermilion" aria-hidden="true" /> Suggested</>
      : <><Clock size={12} aria-hidden="true" /> Scheduled</>;
  const label = `${item.time} · ${title}${clip ? ` · ${topicLabel(clip.category, clip.category_label)}` : ''} · ${KIND_WORD[kind]}`
    + `${stayed !== null ? `, stayed to watch ${fmtPct(stayed)}` : ''}${clip?.video_url ? '. Play' : ''}`;
  return (
    <li className="relative">
      <button
        type="button"
        onClick={clip?.video_url ? () => onOpen(clip) : undefined}
        disabled={!clip?.video_url}
        title={kind === 'proposed' && item.why ? item.why : title}
        className={`w-full text-left rounded-input border overflow-hidden transition-colors disabled:cursor-default
          ${kind === 'proposed' ? 'border-dashed border-vermilion/70 bg-vermilionsoft/40' : 'border-rule bg-paper3 enabled:hover:border-rule2'}
          ${lit ? 'outline outline-2 outline-offset-1 outline-warn' : ''}`}
        aria-label={label}
      >
        <span className="relative block" aria-hidden="true">
          {clip
            ? <ClipThumb clip={clip} crop className="w-full !rounded-none !border-0" />
            : <span className="flex aspect-square items-center justify-center bg-black text-[11px] text-muted px-2 text-center">Not on this computer</span>}
          <span className="absolute top-1 left-1 readout !text-ink px-1.5 py-0.5 rounded bg-paper/85">{item.time}</span>
        </span>
        <span className="block h-1" style={clip ? topicFill(clip.category, 1.5) : {}} aria-hidden="true" />
        <span className="block p-1.5 space-y-0.5" aria-hidden="true">
          <span className="block text-xs text-ink leading-snug line-clamp-2 break-words">{title}</span>
          {clip && (
            <span className="flex items-center gap-1 text-[11px] text-muted min-w-0">
              <TopicSwatch id={clip.category} size={8} />
              <span className="truncate">{topicLabel(clip.category, clip.category_label)}</span>
            </span>
          )}
          <span className="flex items-center gap-1 text-[11px] text-muted">{state}</span>
          {kind === 'proposed' && item.why && (
            <span className="block text-[11px] text-ink2 leading-snug line-clamp-3">{item.why}</span>
          )}
        </span>
      </button>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="absolute top-1 right-1 w-7 h-7 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-input bg-paper/85 border border-rule2 text-ink2 hover:text-danger flex items-center justify-center"
          aria-label={`Take “${title}” out of the suggestion`}
          title="Take it out"
        >
          <X size={14} aria-hidden="true" />
        </button>
      )}
    </li>
  );
}

// Bars of the week's mix: one line per value, its words and its count; topics in their colour.
function MixBars({ title, rows, total, colored = false }) {
  return (
    <div className="min-w-0">
      <p className="readout mb-2">{title}</p>
      {rows.length === 0 && <p className="text-xs text-muted">Nothing yet.</p>}
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.id} className="min-w-0">
            <span className="flex items-baseline justify-between gap-2 text-xs">
              <span className="text-ink2 truncate flex items-center gap-1.5" title={r.title || r.label}>
                {colored && <TopicSwatch id={r.id} size={8} />}
                {r.label}
              </span>
              <span className="readout !text-ink2 shrink-0">{r.count}<span className="text-muted">/{total}</span></span>
            </span>
            <span className="mt-1 block h-1.5 rounded-full bg-paper3" aria-hidden="true">
              <span
                className={`block h-full rounded-full ${colored ? '' : 'bg-ink2/70'}`}
                style={{ width: `${total ? Math.max(4, (r.count / total) * 100) : 0}%`, ...(colored ? topicFill(r.id, 1.25) : {}) }}
              />
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// The first few alerts, the rest one click away: a long list hides the point.
const ALERTS_SHOWN = 4;

function AlertList({ alerts, lit, setLit, label }) {
  const [all, setAll] = useState(false);
  if (!alerts?.length) return null;
  const shown = all ? alerts : alerts.slice(0, ALERTS_SHOWN);
  return (
    <>
      <ul className="space-y-1.5" aria-label={label}>
        {shown.map((a, i) => {
          const key = `${a.kind}-${a.date || ''}-${i}`;
          const on = lit === key;
          return (
            <li key={key}>
              <button
                type="button"
                onClick={() => setLit(on ? null : key)}
                aria-pressed={on}
                className={`w-full text-left flex items-start gap-2 rounded-input px-2.5 py-2 text-sm transition-colors border
                  ${on ? 'border-warn/50 bg-paper3' : 'border-transparent hover:bg-paper3'}`}
                title={on ? 'Stop showing these clips' : 'Show these clips in the week'}
              >
                <AlertTriangle size={15} className="text-warn shrink-0 mt-0.5" aria-hidden="true" />
                <span className="flex-1 min-w-0 text-ink2">{a.message}</span>
                {a.date && <span className="readout shrink-0 pt-0.5">{fmtDay(a.date)}</span>}
              </button>
            </li>
          );
        })}
      </ul>
      {alerts.length > ALERTS_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all} className="btn-quiet px-3 py-1.5 text-xs">
          {all ? 'Show fewer' : `Show all ${alerts.length} alerts`}
        </button>
      )}
    </>
  );
}

/**
 * The week, today → +6 days: one column per day, one tile per YouTube post; the suggested order (not
 * sent) in dashed tiles; the variety alerts in words; the week's mix in simple bars. The strip scrolls on
 * its own on a phone — the page never does.
 */
export default function WeekBoard({
  week, today, clipsByRef, plan, planEdited, onOpenClip, onSwap, onRemove,
}) {
  const [lit, setLit] = useState(null);
  const days = daysBetween(week?.from || today, week?.to);
  const timeline = week?.timeline || [];
  const proposed = plan?.plan || [];

  // The refs of the alert being looked at → their tiles get a ring.
  // The suggestion's own notes: the engine repeats the week's alerts, keep only what is new.
  const planAlerts = newAlerts(plan?.alerts, week?.alerts);
  const allAlerts = [...(week?.alerts || []).map((a, i) => ({ ...a, _k: `${a.kind}-${a.date || ''}-${i}` })),
    ...planAlerts.map((a, i) => ({ ...a, _k: `plan-${a.kind}-${a.date || ''}-${i}` }))];
  const litRefs = new Set((allAlerts.find((a) => a._k === lit)?.refs) || []);

  const byDay = Object.fromEntries(days.map((d) => [d, []]));
  for (const t of timeline) if (byDay[t.date]) byDay[t.date].push({ item: t, kind: t.status === 'published' ? 'published' : 'scheduled' });
  proposed.forEach((p, i) => { if (byDay[p.date]) byDay[p.date].push({ item: p, kind: 'proposed', index: i }); });
  for (const d of days) byDay[d].sort((a, b) => (a.item.time || '').localeCompare(b.item.time || ''));
  const postCount = timeline.length;

  const mix = week?.mix || {};
  const sumOf = (o) => Object.values(o || {}).reduce((s, n) => s + (Number(n) || 0), 0);
  const anyClipOf = (pred) => Object.values(clipsByRef).find(pred);
  const topicRows = Object.entries(mix.category || {})
    .map(([id, count]) => ({ id, count, label: topicLabel(id, anyClipOf((c) => c.category === id)?.category_label) }))
    .sort((a, b) => b.count - a.count || topicOrder(a.id) - topicOrder(b.id));
  const episodeRows = Object.entries(mix.episode || {})
    .map(([id, count]) => {
      const c = anyClipOf((x) => x.episode_key === id);
      const named = week?.episodes?.[id];
      return { id, count, label: c ? episodeShort(c) : (named || id), title: named || (c ? [c.show, c.episode, c.guest].filter(Boolean).join(' · ') : id) };
    })
    .sort((a, b) => b.count - a.count);
  const formRows = Object.entries(mix.title_form || {})
    .map(([id, count]) => ({ id, count, label: titleFormLabel(id) }))
    .sort((a, b) => b.count - a.count);

  return (
    <section aria-labelledby="lu-week-title" className="card-print p-4 sm:p-6 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">This week</p>
          <h3 id="lu-week-title" className="font-display text-lg sm:text-xl text-ink mt-1">What goes out on YouTube</h3>
        </div>
        <p className="readout">
          {fmtDay(days[0], { day: 'numeric', month: 'short' })} → {fmtDay(days[days.length - 1], { day: 'numeric', month: 'short' })}
          {' · '}{postCount} post{postCount === 1 ? '' : 's'}
        </p>
      </div>

      {/* The strip: seven columns; on a narrow screen it scrolls sideways by itself. */}
      <div className="overflow-x-auto custom-scrollbar -mx-4 px-4 sm:mx-0 sm:px-0 pb-1" role="region" aria-label="The week, day by day" tabIndex={0}>
        <ol className="grid grid-cols-7 gap-2 min-w-[68rem] xl:min-w-0">
          {days.map((d) => {
            const items = byDay[d];
            const isToday = d === today;
            return (
              <li key={d} className={`min-w-0 rounded-input p-1.5 ${isToday ? 'bg-paper3/60' : ''}`} aria-label={`${dayLabel(d, today)} ${fmtDay(d)}: ${items.length} post${items.length === 1 ? '' : 's'}`}>
                <div className="px-1 pb-2 mb-2 border-b border-rule">
                  <p className={`text-xs font-medium ${isToday ? 'text-ink' : 'text-ink2'}`}>{dayLabel(d, today)}</p>
                  <p className="readout">{fmtDay(d, { day: 'numeric', month: 'short' })} · {items.length}</p>
                </div>
                {items.length === 0
                  ? <p className="px-1 text-[11px] text-muted">Nothing planned</p>
                  : (
                    <ol className="space-y-1.5">
                      {items.map(({ item, kind, index }) => (
                        <Tile
                          key={`${kind}-${item.ref}-${item.time}`}
                          item={item}
                          kind={kind}
                          clip={clipsByRef[item.ref]}
                          lit={litRefs.has(item.ref)}
                          onOpen={onOpenClip}
                          onRemove={kind === 'proposed' ? () => onRemove(index) : undefined}
                        />
                      ))}
                    </ol>
                  )}
              </li>
            );
          })}
        </ol>
      </div>

      {/* The suggested order — nothing is sent until "Schedule on Upload-Post" and its confirmation. */}
      {proposed.length > 0 && (
        <div className="tray p-3 sm:p-4 space-y-3" role="region" aria-labelledby="lu-plan-title">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h4 id="lu-plan-title" className="font-display text-base text-ink">Suggested order</h4>
            <p className="readout">{proposed.length} post{proposed.length === 1 ? '' : 's'} · not sent yet</p>
          </div>
          <ol className="space-y-2">
            {proposed.map((p, i) => {
              const clip = clipsByRef[p.ref];
              const title = clip?.title || p.ref;
              return (
                <li key={`${p.date}-${p.time}`} className="card p-2.5 flex items-start gap-3">
                  <div className="w-[5.5rem] shrink-0 pt-0.5">
                    <p className="text-xs text-ink whitespace-nowrap">{fmtDay(p.date)}</p>
                    <p className="readout !text-ink2 mt-0.5">{p.time}</p>
                  </div>
                  {clip && <ClipThumb clip={clip} className="w-9 hidden min-[420px]:block" />}
                  <div className="min-w-0 flex-1 space-y-1">
                    {clip && <TopicTag id={clip.category} label={clip.category_label} source={clip.category_source} />}
                    <p className="text-sm text-ink leading-snug line-clamp-2 break-words">{title}</p>
                    {p.why && <p className="text-xs text-muted leading-snug"><span className="text-ink2">Why here: </span>{p.why}</p>}
                  </div>
                  <div className="flex flex-col sm:flex-row gap-0.5 shrink-0">
                    <button type="button" className={iconBtn} onClick={() => onSwap(i, i - 1)} disabled={i === 0}
                      aria-label={`Swap “${title}” with the post before`} title="Swap with the post before">
                      <ChevronUp size={16} aria-hidden="true" />
                    </button>
                    <button type="button" className={iconBtn} onClick={() => onSwap(i, i + 1)} disabled={i === proposed.length - 1}
                      aria-label={`Swap “${title}” with the post after`} title="Swap with the post after">
                      <ChevronDown size={16} aria-hidden="true" />
                    </button>
                    <button type="button" className={`${iconBtn} hover:!text-danger`} onClick={() => onRemove(i)}
                      aria-label={`Take “${title}” out of the suggested order`} title="Take it out">
                      <X size={16} aria-hidden="true" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
          {planEdited && (
            <p className="text-xs text-muted">You changed the order: the notes below were written for the suggestion.</p>
          )}
          {planAlerts.length > 0 && (
            <div className="space-y-1.5">
              <p className="readout">Still to watch in this order</p>
              <AlertList
                alerts={planAlerts}
                lit={lit && lit.startsWith('plan-') ? lit.slice(5) : null}
                setLit={(k) => setLit(k ? `plan-${k}` : null)}
                label="Variety notes on the suggested order"
              />
            </div>
          )}
          {(plan?.left_out || []).length > 0 && (
            <p className="text-xs text-muted">
              <span className="text-ink2">Left out to keep the mix varied: </span>
              {plan.left_out.map((ref) => clipsByRef[ref]?.title || ref).join(' · ')}
            </p>
          )}
        </div>
      )}

      {/* Variety, in words: what repeats too much this week. */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="space-y-2 min-w-0">
          <p className="readout">Variety alerts</p>
          {(week?.alerts || []).length === 0
            ? (
              <p className="text-sm text-ink2 flex items-center gap-2">
                <CheckCircle2 size={15} className="text-ok" aria-hidden="true" /> No variety alert this week.
              </p>
            )
            : <AlertList alerts={week.alerts} lit={lit} setLit={setLit} label="Variety alerts of the week" />}
        </div>
        <div className="grid gap-5 sm:grid-cols-3 min-w-0">
          <MixBars title="Topics" rows={topicRows} total={sumOf(mix.category)} colored />
          <MixBars title="Episodes" rows={episodeRows} total={sumOf(mix.episode)} />
          <MixBars title="Title shapes" rows={formRows} total={sumOf(mix.title_form)} />
        </div>
      </div>
    </section>
  );
}
