import { Pencil } from 'lucide-react';
import { topicFill, topicLabel, topicOf } from '../../lib/topics';

// The topic swatch: solid for the channel's niche, an outline for a topic outside it (design.md « Topic
// colours »). Decorative: the label next to it carries the meaning.
export function TopicSwatch({ id, size = 10 }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block shrink-0 rounded-[3px]"
      style={{ width: size, height: size, ...topicFill(id, size > 9 ? 1.5 : 1.25) }}
    />
  );
}

/**
 * A clip's topic, colour + words. With `onEdit` it is the button that corrects it (the AI's choice can be
 * wrong); "yours" marks a topic set by hand.
 */
export default function TopicTag({ id, label, source, onEdit, className = '' }) {
  const text = topicLabel(id, label);
  const manual = source === 'manual';
  const base = `inline-flex items-center gap-1.5 max-w-full rounded-[4px] border border-rule2 bg-paper2 px-2 py-0.5 text-xs text-ink2 ${className}`;
  const inner = (
    <>
      <TopicSwatch id={topicOf(id).id} />
      <span className="truncate">{text}</span>
      {manual && <span className="readout !text-[9.5px] !tracking-[0.08em]">yours</span>}
    </>
  );
  if (!onEdit) return <span className={base}>{inner}</span>;
  return (
    <button
      type="button"
      onClick={onEdit}
      className={`${base} hover:border-ink hover:text-ink transition-colors [@media(pointer:coarse)]:min-h-[44px]`}
      aria-label={`Topic: ${text}${manual ? ', set by you' : ", the AI's choice"}. Change the topic`}
      title="Change the topic"
    >
      {inner}
      <Pencil size={11} className="text-muted shrink-0" aria-hidden="true" />
    </button>
  );
}
