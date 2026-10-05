// The topic of a clip (playbook.TOPIC_BUCKETS) as the Line-up draws it (5-oct-2026, design.md « Topic colours »).
// A topic colour is DATA: it marks a chip, a tile or a bar, and always travels with its label — never alone,
// never on the interface's frame. The labels mirror playbook.HOOK_CATEGORY; the server's own
// `category_label` wins when it sends one.

// Display order (also the colour order validated in tokens.css): the channel's niche first, solid; the
// topics outside the niche drawn hollow (outline, same hues); "other" last, grey.
export const TOPICS = [
  { id: 'medical_mystery', label: 'Medicine' },
  { id: 'substances', label: 'Substances' },
  { id: 'mind_psychology', label: 'Psychology' },
  { id: 'brain_danger', label: 'Brain' },
  { id: 'psychosis_mental_illness', label: 'Mental health' },
  { id: 'self_improvement', label: 'Self-improvement' },
  { id: 'crime_dark', label: 'True crime' },
  { id: 'science_other', label: 'Science', offNiche: true },
  { id: 'sports_combat', label: 'Combat sports', offNiche: true },
  { id: 'entertainment', label: 'Entertainment', offNiche: true },
  { id: 'business_money', label: 'Money', offNiche: true },
  { id: 'other', label: 'Other' },
];

const BY_ID = Object.fromEntries(TOPICS.map((t) => [t.id, t]));

export const topicOf = (id) => BY_ID[id] || BY_ID.other;

export const topicLabel = (id, serverLabel) => serverLabel || topicOf(id).label;

export const topicColor = (id) => `var(--cat-${topicOf(id).id})`;

export const topicOrder = (id) => {
  const i = TOPICS.findIndex((t) => t.id === id);
  return i < 0 ? TOPICS.length : i;
};

// The style of a topic mark (swatch, bar, tile edge): solid for the niche, an outline for the topics
// outside it. `size`: the outline's width in px.
export function topicFill(id, size = 1.5) {
  const t = topicOf(id);
  const color = topicColor(t.id);
  return t.offNiche
    ? { background: 'transparent', boxShadow: `inset 0 0 0 ${size}px ${color}` }
    : { background: color };
}
