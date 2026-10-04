import React from 'react';
import {
  Sparkles, Scissors, Subtitles, Type, Brush, Share2, ArrowRight, Plus, Minus, Image as ImageIcon, Flame,
  Calendar, Clapperboard, LayoutGrid, Eraser, Rocket, Link2, Github, ShieldCheck, KeyRound,
} from 'lucide-react';
import { openConsentManager } from './lib/consent';
import './landing.css';

/* Synapse AI — the landing page (4-oct-2026, « Synapse · Graphite », design.md). Built on OpenShorts (MIT). */

const FEATURES = [
  { icon: Sparkles, title: 'Finds the moments', text: 'Reads the whole conversation and keeps the moments that stand on their own: a surprising idea, a turn, a punchline.' },
  { icon: Scissors, title: 'Cuts to 9:16', text: 'Reframes every clip for the phone, follows who speaks, keeps the faces in frame.' },
  { icon: Type, title: 'Writes the hook', text: 'A first line that makes people stay, a title and a description in your channel’s voice.' },
  { icon: Subtitles, title: 'Word-level captions', text: 'Captions that light up word by word, styled for the feed and readable on a phone.' },
  { icon: Brush, title: 'Draws every idea', text: 'Drawn B-roll in one style per episode: each picture shows what the sentence means, not just the word.' },
  { icon: Share2, title: 'Publishes', text: 'TikTok, Reels and YouTube Shorts from one place, scheduled when your audience is there.' },
];

// The studio's own one-line descriptions (App.jsx navItems), so the landing never promises more than the app does.
const MODES = [
  { icon: Rocket, label: 'Synapse Cut', text: 'Your channel profiles: moments, hooks, captions and drawn B-roll, in your house style.' },
  { icon: Sparkles, label: 'AI Shorts', text: 'Generate a short from a script or a product, voiced and edited by AI.' },
  { icon: Clapperboard, label: 'Story Channel', text: 'Long stories told as a series of shorts.' },
  { icon: LayoutGrid, label: 'UGC Gallery', text: 'The videos generated with AI actors.' },
  { icon: ImageIcon, label: 'YouTube Studio', text: 'Thumbnails, titles and descriptions for YouTube.' },
  { icon: Flame, label: 'Viral Finder', text: 'Find the videos that are taking off in your niche.' },
  { icon: Eraser, label: 'Clip Reworker', text: 'Take a viral clip and make it yours.' },
  { icon: Calendar, label: 'Publish Plan', text: 'Plan and schedule your posts across platforms.' },
];

const STEPS = [
  { kicker: 'First', title: 'Drop a long video', text: 'A podcast, an interview, a talk: paste a link or upload the file.', readout: 'YouTube link · file upload' },
  { kicker: 'Then', title: 'Synapse AI makes the shorts', text: 'Moments found, cut, captioned, hooked and illustrated, in your channel’s style.', readout: 'Moments · 9:16 · hook · captions · drawings' },
  { kicker: 'Last', title: 'Review and publish', text: 'Keep what you like, tweak the rest, send it to every platform.', readout: 'TikTok · Reels · YouTube Shorts' },
];

const FACTS = [
  { value: '9:16', label: 'Vertical, reframed on whoever speaks' },
  { value: 'Word by word', label: 'Captions, lit as they are said' },
  { value: 'One style', label: 'Drawn B-roll, per episode' },
  { value: 'Three platforms', label: 'TikTok · Reels · YouTube Shorts' },
];

// The product's own drawn B-roll. Quoted lines are the sentences each picture was drawn for; the two
// without a known line are described, never given an invented quote.
const PLATES = [
  {
    src: '/landing/negation.jpg', lead: true,
    said: '“nothing to do with ibogaine whatsoever”', idea: 'Negation · the red double stroke',
    alt: 'Drawing of a potted orange tree on a windowsill, crossed out with a red double stroke',
  },
  {
    src: '/landing/dmt.jpg',
    said: '“the outcomes are very, very good for a lot of people”', idea: 'Outcome · many faces, one feeling',
    alt: 'Drawing of four smiling people with closed eyes, framed by swirling warm colour',
  },
  {
    src: '/landing/universe.jpg',
    said: '“an image of the known universe… is it a brain cell?”', idea: 'Comparison · two prints, side by side',
    alt: 'Drawing of a visitor in a gallery between two framed prints, one like a web of galaxies, one like a neuron',
  },
  {
    src: '/landing/dopamine.jpg',
    said: '“the largest dump of dopamine in the brain”', idea: 'Metaphor · a jar of rewards, spilling',
    alt: 'Drawing of a tipped glass jar spilling glowing golden stars across a wooden floor',
  },
  {
    src: '/landing/voice.jpg',
    said: '“the first thing he ever said was: hello”', idea: 'Emotion · the face, not the device',
    alt: 'Drawn close-up of a young man with tears on his cheeks and a small speaker beside his head',
  },
  {
    src: '/landing/wheelchair.jpg',
    said: 'A voice in a quiet room, drawn as light from a small speaker.', idea: 'Sound · shown, not written',
    alt: 'Drawing of a man in a wheelchair turning toward a small glowing speaker on a windowsill',
  },
  {
    src: '/landing/frustration.jpg',
    said: 'Frustration, drawn as a face and the colour around it.', idea: 'Feeling · from the inside',
    alt: 'Drawn close-up of a young man frowning with his eyes shut, colour swirling around him',
  },
];

const FAQ = [
  { q: 'What is Synapse AI?', a: 'An AI clip studio: it turns long videos and podcasts into vertical shorts for TikTok, Reels and YouTube Shorts — the moments found and cut, the hook and captions written, and every idea illustrated with a drawn picture.' },
  { q: 'What makes the pictures different?', a: 'Synapse AI does not paste stock images on keywords. An art director reads each sentence for its idea, draws the simplest symbol of it in one style for the whole episode, and a safety check keeps anything gory, cruel or misleading out.' },
  { q: 'What do I need to run it?', a: 'Docker, your own API keys (Gemini, Claude, Upload-Post) and, for the drawn B-roll, a GPU running ComfyUI with Z-Image. Your videos and keys stay on your machine.' },
  { q: 'Which platforms can it publish to?', a: 'TikTok, Instagram Reels and YouTube Shorts, through Upload-Post, with scheduling.' },
  { q: 'Is it open source?', a: 'Synapse AI is built on OpenShorts, an open source clip generator released under the MIT license.' },
];

const CAPTION_WORDS = ['videos', 'of', 'guys', 'carrying', 'refrigerators'];

// main.jsx keeps the landing mounted only for its own list of hashes (#landing, #features,
// #how-it-works, #pricing, #comparison, #faq): any other hash would hand a returning visitor to the
// app. Jumps to the other sections (and the skip link) scroll and move focus without touching the URL.
const jumpTo = (id) => (e) => {
  e.preventDefault();
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ block: 'start' });
  el.focus({ preventScroll: true });
};

/* The brand motif, hand-built: a neuron in thin white lines whose axon ends on the plate's edge, the
   idea passing from the sentence to the picture. One cyan nucleus fires; nothing else is coloured.
   viewBox 600 × 660 mirrors .lp-art-box; the plate sits at x 300–576, y 85–576. */
function SynapseDrawing() {
  return (
    <svg className="lp-neuron" viewBox="0 0 600 660" aria-hidden="true" focusable="false" preserveAspectRatio="xMidYMid meet">
      {/* far filaments: the network the plate belongs to (they pass behind it) */}
      <path className="lp-filament" d="M214 122 C 300 96 420 70 596 52" />
      <path className="lp-filament" d="M226 556 C 330 604 452 626 598 612" />
      <path className="lp-filament" d="M42 334 C 30 420 40 520 8 640" />
      <path className="lp-filament" d="M72 172 C 96 110 120 60 112 4" />
      <circle className="lp-node-faint" cx="596" cy="52" r="2.5" />
      <circle className="lp-node-faint" cx="598" cy="612" r="2.5" />
      <circle className="lp-node-faint" cx="112" cy="4" r="2" />

      {/* dendrites */}
      <path className="lp-dendrite" d="M165 300 C 145 252 112 205 72 172" />
      <path className="lp-dendrite" d="M72 172 C 58 160 42 154 26 152" />
      <path className="lp-dendrite" d="M72 172 C 66 150 64 128 58 108" />
      <path className="lp-dendrite" d="M165 300 C 172 242 188 178 214 122" />
      <path className="lp-dendrite" d="M214 122 C 208 102 204 86 196 64" />
      <path className="lp-dendrite" d="M214 122 C 228 106 240 96 258 86" />
      <path className="lp-dendrite" d="M165 300 C 122 298 82 312 42 334" />
      <path className="lp-dendrite" d="M42 334 C 32 326 22 316 12 302" />
      <path className="lp-dendrite" d="M165 300 C 146 362 116 424 82 478" />
      <path className="lp-dendrite" d="M82 478 C 64 492 50 500 32 506" />
      <path className="lp-dendrite" d="M82 478 C 84 500 88 520 96 546" />
      <path className="lp-dendrite" d="M165 300 C 182 372 198 452 226 556" />
      <path className="lp-dendrite" d="M226 556 C 220 576 214 594 206 616" />
      <path className="lp-dendrite" d="M226 556 C 240 572 252 584 270 596" />
      <g>
        <circle className="lp-node" cx="26" cy="152" r="3" />
        <circle className="lp-node" cx="58" cy="108" r="3" />
        <circle className="lp-node" cx="196" cy="64" r="3" />
        <circle className="lp-node" cx="258" cy="86" r="3" />
        <circle className="lp-node" cx="12" cy="302" r="3" />
        <circle className="lp-node" cx="32" cy="506" r="3" />
        <circle className="lp-node" cx="96" cy="546" r="3" />
        <circle className="lp-node" cx="206" cy="616" r="3" />
        <circle className="lp-node" cx="270" cy="596" r="3" />
        <circle className="lp-node" cx="72" cy="172" r="2.2" />
        <circle className="lp-node" cx="214" cy="122" r="2.2" />
        <circle className="lp-node" cx="42" cy="334" r="2.2" />
        <circle className="lp-node" cx="82" cy="478" r="2.2" />
        <circle className="lp-node" cx="226" cy="556" r="2.2" />
      </g>

      {/* the axon, reaching the plate: its terminals touch the picture */}
      <path className="lp-axon" d="M165 300 C 205 306 245 318 280 326" />
      <path className="lp-axon" d="M280 326 C 287 318 292 312 297 306" />
      <path className="lp-axon" d="M280 326 C 288 330 292 334 297 338" />
      <path className="lp-axon" d="M280 326 C 286 340 290 350 295 362" />
      <circle className="lp-bouton" cx="297" cy="306" r="3.5" />
      <circle className="lp-bouton" cx="297" cy="338" r="3.5" />
      <circle className="lp-bouton" cx="295" cy="362" r="3.5" />

      {/* the soma and its one firing nucleus */}
      <circle className="lp-soma" cx="165" cy="300" r="24" />
      <circle className="lp-halo" cx="165" cy="300" r="16" />
      <circle className="lp-nucleus lp-nucleus-fire" cx="165" cy="300" r="8.5" />
    </svg>
  );
}

export default function Landing({ onLaunchApp }) {
  const [openFaq, setOpenFaq] = React.useState(0);
  const [heroUrl, setHeroUrl] = React.useState('');

  // Hand the pasted link to the app: MediaInput picks it up on mount, so the
  // user lands with their own video ready.
  const handleHeroSubmit = (e) => {
    e.preventDefault();
    const url = heroUrl.trim();
    if (url) {
      try { localStorage.setItem('os_pending_url', url); } catch { /* ignore */ }
    }
    onLaunchApp();
  };

  return (
    <div id="landing" className="lp min-h-screen text-ink2 overflow-x-clip">
      <a href="#main-content" onClick={jumpTo('main-content')} className="skip-link">Skip to content</a>

      <header className="lp-header">
        <div className="lp-wrap flex items-center justify-between gap-4 h-16">
          <a href="#landing" className="flex items-center gap-2.5 min-h-[44px]" aria-label="Synapse AI home">
            <img src="/logo-synapse.svg" alt="" className="w-8 h-8" width="32" height="32" />
            <span className="brand-word text-lg">Synapse <span className="brand-ai">AI</span></span>
          </a>
          <nav className="hidden md:flex items-center gap-6" aria-label="Page sections">
            <a href="#broll" onClick={jumpTo('broll')} className="lp-navlink">Drawn B-roll</a>
            <a href="#how-it-works" className="lp-navlink">How it works</a>
            <a href="#features" className="lp-navlink">Features</a>
            <a href="#faq" className="lp-navlink">FAQ</a>
          </nav>
          <button type="button" onClick={onLaunchApp} className="btn-ghost px-4 py-2 whitespace-nowrap">
            Open the app <ArrowRight size={15} aria-hidden="true" />
          </button>
        </div>
      </header>

      <main id="main-content" tabIndex={-1}>
        {/* Hero: the promise, the link box, and the synapse firing into a short */}
        <section className="lp-hero" aria-labelledby="hero-title">
          <div className="lp-wrap grid lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] gap-12 lg:gap-10 items-center">
            <div className="min-w-0">
              <p className="lp-kicker mb-5">AI clip studio · drawn B-roll</p>
              <h1 id="hero-title" className="lp-display">
                Long talks into shorts people <span className="ink-underline">understand</span>.
              </h1>
              <p className="lp-lede">
                Synapse AI finds the moments worth sharing in any long video, cuts them to 9:16, writes the hook and
                the captions — and draws a picture for every idea, so viewers see what is said, not just hear it.
              </p>

              <form onSubmit={handleHeroSubmit} className="lp-start card-print" aria-label="Start from a video link">
                <label htmlFor="hero-url" className="block text-sm font-medium text-ink mb-2.5">Start from a video link</label>
                <div className="lp-start-row">
                  <div className="lp-start-field">
                    <Link2 size={17} aria-hidden="true" />
                    <input
                      id="hero-url"
                      type="url"
                      inputMode="url"
                      placeholder="Paste a YouTube link…"
                      value={heroUrl}
                      onChange={(e) => setHeroUrl(e.target.value)}
                      aria-describedby="hero-url-help"
                      className="input-field"
                    />
                  </div>
                  <button type="submit" className="btn-accent">
                    Make shorts <ArrowRight size={16} aria-hidden="true" />
                  </button>
                </div>
                <p id="hero-url-help" className="text-sm text-muted mt-3 leading-relaxed">
                  Or{' '}
                  <button type="button" onClick={onLaunchApp} className="lp-link">open the app</button>
                  {' '}and drop a file. Your videos stay on your machine.
                </p>
              </form>
            </div>

            <figure className="lp-art min-w-0">
              <div className="lp-art-box">
                <SynapseDrawing />
                <div className="lp-plate">
                  <div className="lp-phone">
                    <img
                      src="/landing/fridge.jpg"
                      alt="Drawing of a young man carrying a refrigerator on his back down a busy city street"
                      width="900"
                      height="563"
                    />
                    <span className="lp-hook" aria-hidden="true">Meth strength: real or myth?</span>
                    <span className="lp-caption" aria-hidden="true">
                      {CAPTION_WORDS.map((w) => (
                        <span key={w} className={w === 'carrying' ? 'is-lit' : undefined}>{w}</span>
                      ))}
                    </span>
                    <span className="lp-playhead" aria-hidden="true"><i /></span>
                  </div>
                </div>
              </div>
              <figcaption className="lp-art-caption readout">A short as it comes out · hook · captions · drawing</figcaption>
            </figure>
          </div>

          <div className="lp-wrap mt-12 lg:mt-16">
            <h2 className="sr-only">At a glance</h2>
            <ul className="lp-facts">
              {FACTS.map((f) => (
                <li key={f.value}>
                  <span className="lp-fact-value">{f.value}</span>
                  <span className="lp-fact-label">{f.label}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Drawn B-roll: the colour of the page is the product's own drawings */}
        <section id="broll" tabIndex={-1} className="lp-section" aria-labelledby="broll-title">
          <div className="lp-wrap">
            <p className="lp-kicker mb-3">Drawn B-roll</p>
            <h2 id="broll-title" className="lp-h2">A picture for the idea, not for the word.</h2>
            <p className="lp-sub">
              An art director reads every sentence, finds what it means and draws its simplest symbol — in one
              editorial style for the whole episode. A safety check keeps anything gory, cruel or misleading out.
            </p>
            <ul className="lp-plates">
              {PLATES.map((p) => (
                <li key={p.src} className={p.lead ? 'is-lead' : undefined}>
                  <figure className="lp-plate-fig">
                    <div className="lp-plate-frame">
                      <img src={p.src} alt={p.alt} width="900" height="563" loading="lazy" decoding="async" />
                    </div>
                    <figcaption>
                      <p className="lp-plate-said">{p.said}</p>
                      <p className="readout mt-1.5">{p.idea}</p>
                    </figcaption>
                  </figure>
                </li>
              ))}
              <li className="is-note">
                <div className="lp-note tray h-full">
                  <p className="lp-kicker">About these pictures</p>
                  <p className="text-ink2 leading-relaxed">
                    Every drawing on this page was made by Synapse AI for a real clip. No stock images.
                  </p>
                </div>
              </li>
            </ul>
          </div>
        </section>

        {/* How it works: three steps on one filament */}
        <section id="how-it-works" className="lp-section" aria-labelledby="how-title">
          <div className="lp-wrap">
            <p className="lp-kicker mb-3">How it works</p>
            <h2 id="how-title" className="lp-h2">Three steps. The thinking is done for you.</h2>
            <ol className="lp-steps">
              {STEPS.map((s) => (
                <li key={s.kicker} className="lp-step">
                  <span className="lp-step-node" aria-hidden="true" />
                  <p className="lp-kicker">{s.kicker}</p>
                  <h3>{s.title}</h3>
                  <p>{s.text}</p>
                  <p className="readout mt-3">{s.readout}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="lp-section" aria-labelledby="features-title">
          <div className="lp-wrap">
            <p className="lp-kicker mb-3">What it does</p>
            <h2 id="features-title" className="lp-h2">From a two-hour podcast to a week of shorts.</h2>
            <ul className="lp-index">
              {FEATURES.map((f) => (
                <li key={f.title}>
                  <h3><f.icon size={18} aria-hidden="true" /> {f.title}</h3>
                  <p>{f.text}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Modes */}
        <section id="modes" tabIndex={-1} className="lp-section" aria-labelledby="modes-title">
          <div className="lp-wrap">
            <p className="lp-kicker mb-3">Every mode</p>
            <h2 id="modes-title" className="lp-h2">One studio, every mode.</h2>
            <ul className="lp-index">
              {MODES.map((m) => (
                <li key={m.label}>
                  <h3><m.icon size={18} aria-hidden="true" /> {m.label}</h3>
                  <p>{m.text}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Trust */}
        <section id="trust" className="lp-section" aria-labelledby="trust-title">
          <div className="lp-wrap">
            <p className="lp-kicker mb-3">Yours to run</p>
            <h2 id="trust-title" className="lp-h2">Your machine, your keys, your clips.</h2>
            <ul className="lp-trust">
              <li className="lp-trust-item card">
                <h3><ShieldCheck size={18} aria-hidden="true" /> Self-hosted</h3>
                <p>Synapse AI runs with Docker on your own machine. Your videos, clips and keys stay with you.</p>
              </li>
              <li className="lp-trust-item card">
                <h3><KeyRound size={18} aria-hidden="true" /> Bring your own keys</h3>
                <p>Gemini, Claude and Upload-Post with your own keys. The drawn B-roll runs on your own GPU (ComfyUI · Z-Image).</p>
              </li>
              <li className="lp-trust-item card">
                <h3><Github size={18} aria-hidden="true" /> Open-source core</h3>
                <p>
                  <a href="https://github.com/mutonby/openshorts" target="_blank" rel="noopener noreferrer" className="lp-link">
                    Built on OpenShorts (MIT)
                  </a>
                  , an open source clip generator released under the MIT license.
                </p>
              </li>
            </ul>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="lp-section" aria-labelledby="faq-title">
          <div className="lp-wrap grid lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-8 lg:gap-16">
            <div>
              <p className="lp-kicker mb-3">FAQ</p>
              <h2 id="faq-title" className="lp-h2">Questions</h2>
            </div>
            <ul className="lp-faq">
              {FAQ.map((f, i) => {
                const open = openFaq === i;
                return (
                  <li key={f.q}>
                    <h3>
                      <button
                        type="button"
                        id={`faq-q-${i}`}
                        className="lp-faq-q"
                        aria-expanded={open}
                        aria-controls={`faq-${i}`}
                        onClick={() => setOpenFaq(open ? null : i)}
                      >
                        {f.q}
                        {open ? <Minus size={18} aria-hidden="true" /> : <Plus size={18} aria-hidden="true" />}
                      </button>
                    </h3>
                    <div id={`faq-${i}`} role="region" aria-labelledby={`faq-q-${i}`} hidden={!open} className="lp-faq-a">{f.a}</div>
                  </li>
                );
              })}
            </ul>
          </div>
        </section>

        {/* Final call */}
        <section className="lp-section" aria-labelledby="cta-title">
          <div className="lp-wrap">
            <div className="lp-cta card-print">
              <div className="flex items-center gap-4 min-w-0">
                <img src="/logo-synapse.svg" alt="" width="48" height="48" className="w-12 h-12 shrink-0" />
                <h2 id="cta-title" className="lp-h2">Your next long episode already holds its best shorts.</h2>
              </div>
              <button type="button" onClick={onLaunchApp} className="btn-accent px-6 py-3 text-base whitespace-nowrap shrink-0">
                Open the app <ArrowRight size={17} aria-hidden="true" />
              </button>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-wrap flex flex-col md:flex-row md:items-center justify-between gap-4 py-8">
          <div className="flex items-center gap-3">
            <img src="/logo-synapse.svg" alt="" className="w-7 h-7" width="28" height="28" />
            <span className="text-sm text-muted">© {new Date().getFullYear()} Synapse AI</span>
          </div>
          <nav aria-label="Footer" className="flex flex-wrap items-center gap-x-6 gap-y-1">
            <a href="#features" className="lp-footlink">Features</a>
            <a href="#faq" className="lp-footlink">FAQ</a>
            <button type="button" onClick={openConsentManager} className="lp-footlink">Cookies</button>
            <a href="https://github.com/mutonby/openshorts" target="_blank" rel="noopener noreferrer" className="lp-footlink">
              <Github size={15} aria-hidden="true" /> Built on OpenShorts (MIT)
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
