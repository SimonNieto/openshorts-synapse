# Design — Synapse AI · « Synapse · Graphite »

The locked design system of Synapse AI (dashboard + landing + account + legal),
built on OpenShorts (MIT). Every page redesign reads this file before writing
code. Extend this file when the system needs to grow; never invent a parallel
system inside a page.

## The idea

**The synapse night, made sober.** Synapse AI keeps its identity — a dark
night, a neuron, filaments, a node that fires — but with almost no colour: a
graphite-black canvas, white ink, hairline filaments, and ONE desaturated cyan
signal (the firing node). It should feel calm, precise and premium, like a
well-made pro tool at night. The colour of the site is its content: the drawn
B-roll images the product makes. The chrome around them stays monochrome.

Retired: the violet, the gradients, the glow soup, the lowercase headings, the
numbered eyebrows (old « Nuit synapse » / « Night Foundry »), and the light
newsprint experiment (« Édition »). **Dark, monochrome, one signal, sentence
case.**

## Tokens (src/tokens.css · Tailwind names in brackets)

| token | value | use |
|---|---|---|
| `--color-paper` [`paper`] | oklch(14.5% 0.006 265) | the canvas: graphite black |
| `--color-paper-2` [`paper2`] | oklch(18% 0.007 265) | raised sheet: cards, modals, inputs |
| `--color-paper-3` [`paper3`] | oklch(22% 0.008 265) | sunken / hover: rail tiles, chips, quiet buttons, trays |
| `--color-ink` [`ink`] | oklch(96.5% 0.003 265) | white ink: headlines, strong buttons |
| `--color-ink-2` [`ink2`] | oklch(85% 0.005 265) | body text |
| `--color-muted` [`muted`] | oklch(66% 0.008 265) | secondary text (≥ 5:1 on paper) |
| `--color-rule` / `-2` [`border-rule`, `border-rule2`] | white 9% / 17% | hairline filaments |
| `--color-accent` [`vermilion` / legacy `brass`, `cyan`, `primary`] | oklch(82% 0.095 212) | THE signal (desaturated cyan): the one main action of a view, the active/selected state, the firing node. Nothing else. |
| `--color-accent-soft` [`vermilionsoft`] | dark cyan wash | selected rows / tiles |
| `--color-accent-ink` [`brassink`] | near-black | text on the signal |
| `--color-accent-2` [`cobalt` / legacy `coral`, `violet`, `accent`] | oklch(78% 0.04 250) | quiet steel: links, info |
| `--color-ok` / `warn` / `danger` | muted green / ochre / red | real states only, always with an icon or a word |
| `shadow-print` / `shadow-print-accent` / `shadow-sheet` | hairline + deep shadow / signal ring / resting | depth (no offset "print" shadows, no neon) |

The Tailwind name `vermilion` is historical: it IS the cyan signal now. No
hard-coded hex, no `white/xx`, `black/xx`, `zinc-*`, `gray-*`, `slate-*`, no
per-feature hues on UI chrome. Real media surfaces (video players, 9:16
previews, image lightboxes) sit on `bg-black` framed by a hairline
`border-rule2`.

**Colour budget per screen:** the accent on at most the main action + the
active/selected state (+ one underlined word or firing node on hero screens).
Everything else is ink / ink2 / muted / rules.

## Topic colours (data only · 5-oct-2026)

The Line-up colours each clip by its topic (`playbook.TOPIC_BUCKETS`). These
colours are **data, not decoration**: they mark a topic chip, a week tile's
edge, a mix bar — never a button, a heading, a border of the frame or a
background. They never replace the label: a topic colour always travels with
its words. Tokens `--cat-<bucket>` in `src/tokens.css`; names, order and the
solid/hollow rule in `src/lib/topics.js`.

| topic | token | mark |
|---|---|---|
| Medicine (`medical_mystery`) | `--cat-medical_mystery` blue | solid |
| Substances | `--cat-substances` orange | solid |
| Psychology (`mind_psychology`) | `--cat-mind_psychology` aqua | solid |
| Brain (`brain_danger`) | `--cat-brain_danger` amber | solid |
| Mental health (`psychosis_mental_illness`) | `--cat-psychosis_mental_illness` magenta | solid |
| Self-improvement | `--cat-self_improvement` green | solid |
| True crime (`crime_dark`) | `--cat-crime_dark` wine | solid |
| Science · Combat sports · Entertainment · Money | the aqua · orange · magenta · amber hues | **hollow** (outline only) |
| Other | `--cat-other` grey | solid |

- The seven niche topics are validated on the card surface (paper-2):
  adjacent colour-blind ΔE ≥ 8.1, normal-vision ΔE ≥ 19.3, contrast ≥ 3:1
  (wine is 2.9:1 on paper-3: the label is the relief). No violet, nothing
  near the cyan signal, steps distinct from ok / warn / danger.
- Twelve hues can't all stay apart for a colour-blind reader, so the four
  topics outside the channel's niche reuse a niche hue drawn **hollow**: the
  shape tells them apart, and it says "off niche" at the same time.
- The signal (cyan) keeps its one job on this screen: the selection and
  "Suggest an order" / "Schedule". Status colours keep theirs (published ✓,
  "Deleted in N days").

## Type

- **Headlines: Geist 600** (`font-display`, `.page-title`), sentence case,
  tracking -0.035em. One `h1` per page (the shell's top bar owns it in the
  app); `h2` for sections, `h3` for cards.
- **Big numbers: Geist 300** (`font-quote`) — durations, counts, scores.
- **Body / UI: Geist** 400/500/600 (default).
- **Labels: JetBrains Mono** (`.eyebrow` in the signal colour, `.readout`
  muted, badges) — UPPERCASE micro labels and machine data only.
- **Sentence case everywhere** in UI chrome ("New clip", "Save tags"). No
  `lowercase` class on UI text, no Title Case. Never transform user content.
- **Eyebrows are words, never numbers.**
- `.ink-underline` — a thin hand-drawn signal stroke under ONE key word on a
  hero/empty state. Optional, at most one per screen.
- Minimum 12px content text, 10.5px mono labels.

## Shape, space, motion

- Radii: cards 10px (`rounded-card`), inputs/buttons 8px (`rounded-input`),
  badges 4px. No pill buttons.
- 4-pt spacing. Pages breathe: `p-4 sm:p-8`, sections `space-y-8`. Forms
  `max-w-2xl`, galleries/workbenches `max-w-7xl`.
- Motion: `--ease-out`, 180ms states, 500ms reveals, fade or 6px rise.
  Clickable cards: `card-hover` (lift + the hairline lights up in the signal).
  A node may pulse (`synapse-fire`) only while something is actually running.
  `prefers-reduced-motion` collapses everything.

## Component recipes (src/index.css — use these)

- `.card` — raised graphite sheet with hairline. `.card-hover` for clickable.
- `.card-print` — the ONE feature card of a view (stronger hairline, depth, a
  faint lit top edge): the new-clip drop zone, the running job, modal panels.
- `.tray` — sunken well: grouped options, empty states, logs.
- `.btn-accent` — the signal: THE action of the screen (one per view).
- `.btn-primary` — white ink button: strong secondary actions.
- `.btn-ghost` (outlined), `.btn-quiet` (sunken utility), `.btn-danger`.
- `.input-field` — labelled (`htmlFor` or `sr-only`), signal focus ring.
- `.badge-ok|-warn|-danger|-brass|-ink|-float`, `.readout`, `.eyebrow`,
  `.status-pill(-ok|-warn)`, `.chip-byok`, `.page-title`, `.page-lede`.
- `.neural-field` + `.neural-node(-2)` — a local hand-built neuron/filament
  SVG (hero, empty states, progress). The body already carries a faint
  filament field: don't stack more than one extra drawing per screen.
- `<Modal>`, `<SegmentedControl>` (active = white fill), `<StepIndicator>`
  (done = white, current = signal) in src/components/ui — the only versions.
- Icons: lucide 16–18px, `text-muted` default, `text-ink` active, signal only
  for the one signal. Decorative icons `aria-hidden`; icon-only buttons
  `aria-label`.

## Imagery

The product's drawn B-roll (`/landing/*.jpg`: fridge, dmt, universe, dopamine,
voice, negation, frustration, wheelchair) is the only colour-rich imagery:
hero, empty states, how-it-works. Frame it on black with a hairline and a mono
caption. The synapse drawing (neuron, filaments, one cyan nucleus) is the
brand mark and the hero motif. No stock photos, no gradient blobs, no glowing
orbs.

## Shell (App.jsx)

- Left rail (`.shell-rail`): logo + wordmark "Synapse **AI**" (AI in the
  signal), a `btn-accent` "New clip", groups Create · Library · Grow ·
  Settings as mono `.nav-group-label`s; active tool = `.nav-tile-active`
  (raised tile, signal edge) + `aria-current="page"`.
- Top bar (`.shell-topbar`): the page's `h1` + one-line description, status
  pills on the right.
- Phone: bottom tab bar (≤ 5 destinations) + drawer; 44px targets; safe area.
- Skip link to `#main-content`.

## Pages may differ on

- Landing: a hero with the synapse drawing (large neuron in thin white lines,
  one cyan firing nucleus) beside a 9:16 plate; then the drawn B-roll plates,
  a 3-step "how it works", the modes, trust, FAQ, CTA. Same tokens.
- Progress (a job running): the pipeline as a synapse pathway — steps as
  nodes on a thin filament; done = solid white, current = the cyan node
  pulsing softly, pending = hollow; live status in mono; source preview on
  black; logs in a `.tray`. Honest data only, no fake telemetry.
- Legal: typography only, 65ch.

## Accessibility (non-negotiable)

WCAG AA contrast; keyboard reachable everything with visible focus; buttons
not `div onClick`; landmarks (`nav aria-label`, `main#main-content`,
`section aria-labelledby`); labels for every input, `aria-describedby` for
help, `role="alert"` for errors, `aria-live="polite"` for async status,
`role="progressbar"` with values for progress; meaningful `alt`; 44px touch
targets on coarse pointers; reduced motion honoured.

## Hard bans

Light page backgrounds. Violet. Gradients (background or text). Neon glow,
blur glass panels. Pill buttons. Colour beyond the budget above. `lowercase`
UI text. Numbered eyebrows. Emoji as UI icons. Hard-coded colours. Invented
metrics, fake testimonials, fake logos.

## Functional contract (NEVER break)

Redesign = markup structure, classes and UI copy only. Never change state,
effects, handlers, props interfaces, API calls (paths, payloads, headers),
localStorage keys (`gemini_key`, `uploadPostKey_v3`, `elevenLabsKey_v1`,
`falKey_v1`, `uploadUserId`, `openshorts_*` …), hash routing (`#app`,
`#/pricing`, `#/account`, `#legal`, landing anchors), `billingEnabled` /
`isManaged` / `isSignedIn` gating, QuotaError flows, Remotion wiring,
`data-tutorial` attributes. Keep every feature and mode (AI Shorts, AI Agent,
UGC Gallery, YouTube Studio, …). Licence: keep "Built on OpenShorts (MIT)".
