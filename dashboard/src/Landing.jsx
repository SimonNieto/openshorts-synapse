import React from 'react';
import {
  Sparkles, Scissors, Subtitles, Type, Brush, Share2, ArrowRight, ChevronDown, Bot, Image as ImageIcon, Flame,
  Calendar, Clapperboard, LayoutGrid, Eraser, Rocket, Link2, Github, ShieldCheck, Cpu,
} from 'lucide-react';
import './landing.css';

/* Synapse AI — the landing page (4-oct-2026, theme « Nuit synapse »). Built on OpenShorts (MIT). */

const FEATURES = [
  { icon: Sparkles, title: 'Finds the moments', text: 'Reads the whole conversation and keeps the moments that stand on their own: a surprising idea, a turn, a punchline.' },
  { icon: Scissors, title: 'Cuts to 9:16', text: 'Reframes every clip for the phone, follows who speaks, keeps the faces in frame.' },
  { icon: Type, title: 'Writes the hook', text: 'A first line that makes people stay, a title and a description in your channel’s voice.' },
  { icon: Subtitles, title: 'Word-level captions', text: 'Captions that light up word by word, styled for the feed and readable on a phone.' },
  { icon: Brush, title: 'Draws every idea', text: 'Drawn B-roll in one style per episode: each picture shows what the sentence means, not just the word.' },
  { icon: Share2, title: 'Publishes', text: 'TikTok, Reels and YouTube Shorts from one place, scheduled when your audience is there.' },
];

const MODES = [
  { icon: Rocket, label: 'Clip Generator++' }, { icon: Sparkles, label: 'AI Shorts' }, { icon: Bot, label: 'AI Agent' },
  { icon: Clapperboard, label: 'Story Channel' }, { icon: LayoutGrid, label: 'UGC Gallery' },
  { icon: ImageIcon, label: 'YouTube Studio' }, { icon: Flame, label: 'Viral Finder' }, { icon: Eraser, label: 'Clip Reworker' },
  { icon: Calendar, label: 'Publish Plan' },
];

const STEPS = [
  { n: '01', title: 'Drop a long video', text: 'A podcast, an interview, a talk: paste a link or upload the file.' },
  { n: '02', title: 'Synapse AI makes the shorts', text: 'Moments found, cut, captioned, hooked and illustrated, in your channel’s style.' },
  { n: '03', title: 'Review and publish', text: 'Keep what you like, tweak the rest, send it to every platform.' },
];

const SHOWCASE = [
  { src: '/landing/fridge.jpg', said: '“videos of guys carrying refrigerators down the street”' },
  { src: '/landing/dmt.jpg', said: '“the outcomes are very, very good for a lot of people”' },
  { src: '/landing/universe.jpg', said: '“an image of the known universe… is it a brain cell?”' },
  { src: '/landing/dopamine.jpg', said: '“the largest dump of dopamine in the brain”' },
  { src: '/landing/voice.jpg', said: '“the first thing he ever said was: hello”' },
  { src: '/landing/negation.jpg', said: '“nothing to do with ibogaine whatsoever”' },
];

const FAQ = [
  { q: 'What is Synapse AI?', a: 'An AI clip studio: it turns long videos and podcasts into vertical shorts for TikTok, Reels and YouTube Shorts — the moments found and cut, the hook and captions written, and every idea illustrated with a drawn picture.' },
  { q: 'What makes the pictures different?', a: 'Synapse AI does not paste stock images on keywords. An art director reads each sentence for its idea, draws the simplest symbol of it in one style for the whole episode, and a safety check keeps anything gory, cruel or misleading out.' },
  { q: 'What do I need to run it?', a: 'Docker, your own API keys (Gemini, Claude, Upload-Post) and, for the drawn B-roll, a GPU running ComfyUI with Z-Image. Your videos and keys stay on your machine.' },
  { q: 'Which platforms can it publish to?', a: 'TikTok, Instagram Reels and YouTube Shorts, through Upload-Post, with scheduling.' },
  { q: 'Is it open source?', a: 'Synapse AI is built on OpenShorts, an open source clip generator released under the MIT license.' },
];

function NeuralArt() {
  return (
    <svg className="lp-neural" viewBox="0 0 600 600" aria-hidden="true">
      <defs>
        <linearGradient id="lpn" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#5fe3ff" />
          <stop offset="0.55" stopColor="#8b7bff" />
          <stop offset="1" stopColor="#c25cff" />
        </linearGradient>
        <radialGradient id="lpc" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.4" stopColor="#9ff0ff" />
          <stop offset="1" stopColor="#8b7bff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <g stroke="url(#lpn)" strokeWidth="1.6" fill="none" strokeLinecap="round" className="lp-filaments">
        <path d="M300 300 C 240 240, 200 160, 120 120 S 40 60, 10 40" />
        <path d="M300 300 C 380 230, 450 200, 520 120 S 580 60, 600 30" />
        <path d="M300 300 C 390 360, 470 400, 560 470" />
        <path d="M300 300 C 230 380, 180 450, 90 540" />
        <path d="M300 300 C 310 400, 290 480, 320 600" />
        <path d="M300 300 C 200 300, 120 330, 0 320" />
        <path d="M120 120 C 160 80, 170 40, 200 0" />
        <path d="M520 120 C 470 90, 440 50, 430 0" />
        <path d="M560 470 C 590 430, 600 400, 600 380" />
      </g>
      <g fill="url(#lpn)">
        <circle cx="120" cy="120" r="5" className="lp-node" />
        <circle cx="520" cy="120" r="5" className="lp-node lp-node-2" />
        <circle cx="560" cy="470" r="5" className="lp-node lp-node-3" />
        <circle cx="90" cy="540" r="5" className="lp-node lp-node-2" />
        <circle cx="0" cy="320" r="4" />
        <circle cx="320" cy="600" r="4" />
      </g>
      <circle cx="300" cy="300" r="34" fill="url(#lpn)" opacity="0.9" className="lp-soma" />
      <circle cx="300" cy="300" r="26" fill="url(#lpc)" />
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
    <div className="lp min-h-screen text-ink2 overflow-x-clip">
      <a href="#main" className="skip-link">Skip to content</a>

      <header className="lp-nav">
        <div className="lp-wrap flex items-center justify-between gap-4 h-16">
          <a href="#landing" className="flex items-center gap-2.5" aria-label="Synapse AI home">
            <img src="/logo-synapse.svg" alt="" className="w-8 h-8 rounded-[9px] logo-glow" width="32" height="32" />
            <span className="brand-word text-lg">synapse <span className="brand-ai">ai</span></span>
          </a>
          <nav className="hidden md:flex items-center gap-7 text-sm text-ink2/80" aria-label="Page sections">
            <a href="#features" className="hover:text-ink transition-colors">Features</a>
            <a href="#broll" className="hover:text-ink transition-colors">Drawn B-roll</a>
            <a href="#how-it-works" className="hover:text-ink transition-colors">How it works</a>
            <a href="#faq" className="hover:text-ink transition-colors">FAQ</a>
          </nav>
          <button type="button" onClick={onLaunchApp} className="btn-primary px-5 py-2 whitespace-nowrap">
            open the studio <ArrowRight size={15} aria-hidden="true" />
          </button>
        </div>
      </header>

      <main id="main">
        {/* Hero */}
        <section className="lp-hero">
          <div className="lp-wrap grid lg:grid-cols-[1.05fr_0.95fr] gap-12 items-center">
            <div>
              <p className="eyebrow mb-5">AI clip studio · 9:16 · drawn B-roll</p>
              <h1 className="lp-title">
                Long talks into shorts people <span className="text-synapse">understand</span>.
              </h1>
              <p className="lp-lead">
                Synapse AI finds the moments worth sharing in any long video, cuts them to 9:16, writes the hook and
                the captions — and draws a picture for every idea, so viewers see what is said, not just hear it.
              </p>
              <form onSubmit={handleHeroSubmit} className="lp-url" role="search" aria-label="Start from a video link">
                <Link2 size={18} className="text-muted shrink-0" aria-hidden="true" />
                <label htmlFor="hero-url" className="sr-only">Video link</label>
                <input
                  id="hero-url"
                  type="url"
                  inputMode="url"
                  placeholder="Paste a YouTube link…"
                  value={heroUrl}
                  onChange={(e) => setHeroUrl(e.target.value)}
                  className="flex-1 min-w-0 bg-transparent outline-none text-ink placeholder:text-muted"
                />
                <button type="submit" className="btn-primary px-5 py-2.5 whitespace-nowrap">make shorts</button>
              </form>
              <p className="readout mt-4">or open the studio and drop a file — your videos stay on your machine</p>
            </div>

            <div className="lp-stage" aria-label="Example of a short made by Synapse AI">
              <NeuralArt />
              <figure className="lp-phone">
                <img src="/landing/fridge.jpg" alt="Drawn picture of a skinny man carrying a refrigerator down a city street" />
                <span className="lp-hook">Meth strength: real or myth?</span>
                <figcaption>
                  <span className="lp-caption">videos of guys <b>carrying</b> refrigerators</span>
                </figcaption>
                <span className="lp-progress" aria-hidden="true"><i /></span>
              </figure>
            </div>
          </div>
        </section>

        {/* Readouts */}
        <section className="lp-wrap" aria-label="At a glance">
          <ul className="lp-readouts">
            <li><span>9:16</span>vertical, face-tracked</li>
            <li><span>word by word</span>captions</li>
            <li><span>1 style</span>per episode, drawn</li>
            <li><span>3 platforms</span>TikTok · Reels · Shorts</li>
          </ul>
        </section>

        {/* Features */}
        <section id="features" className="lp-section">
          <div className="lp-wrap">
            <p className="eyebrow mb-3">What it does</p>
            <h2 className="lp-h2">From a two-hour podcast to a week of shorts.</h2>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-10">
              {FEATURES.map((f) => (
                <article key={f.title} className="card card-hover p-6">
                  <span className="lp-icon" aria-hidden="true"><f.icon size={18} /></span>
                  <h3 className="text-ink font-semibold text-lg mt-4 mb-2">{f.title}</h3>
                  <p className="text-sm text-muted leading-relaxed">{f.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* Drawn B-roll */}
        <section id="broll" className="lp-section">
          <div className="lp-wrap">
            <p className="eyebrow mb-3">Drawn B-roll</p>
            <h2 className="lp-h2">A picture for the idea, not for the word.</h2>
            <p className="lp-sub">
              An art director reads every sentence, finds what it means and draws its simplest symbol — in one
              editorial style for the whole episode. A safety check keeps anything gory, cruel or misleading out.
            </p>
            <div className="lp-showcase mt-10">
              {SHOWCASE.map((s) => (
                <figure key={s.src} className="lp-shot">
                  <img src={s.src} alt={`Drawn B-roll for ${s.said}`} loading="lazy" />
                  <figcaption>{s.said}</figcaption>
                </figure>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section id="how-it-works" className="lp-section">
          <div className="lp-wrap grid lg:grid-cols-2 gap-12 items-start">
            <div>
              <p className="eyebrow mb-3">How it works</p>
              <h2 className="lp-h2">Three steps. The thinking is done for you.</h2>
              <ol className="mt-10 space-y-6">
                {STEPS.map((s) => (
                  <li key={s.n} className="lp-step">
                    <span className="lp-step-n">{s.n}</span>
                    <div>
                      <h3 className="text-ink font-semibold mb-1">{s.title}</h3>
                      <p className="text-sm text-muted leading-relaxed">{s.text}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
            <div className="card p-6 sm:p-8">
              <p className="eyebrow mb-4">One studio, every mode</p>
              <ul className="flex flex-wrap gap-2.5">
                {MODES.map((m) => (
                  <li key={m.label} className="lp-mode"><m.icon size={15} aria-hidden="true" /> {m.label}</li>
                ))}
              </ul>
              <div className="lp-trust mt-8">
                <p><ShieldCheck size={16} aria-hidden="true" /> Self-hosted: your videos and keys stay with you.</p>
                <p><Cpu size={16} aria-hidden="true" /> Drawn on your own GPU (ComfyUI · Z-Image).</p>
                <p><Github size={16} aria-hidden="true" /> Built on OpenShorts, open source (MIT).</p>
              </div>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="lp-section">
          <div className="lp-wrap max-w-3xl">
            <p className="eyebrow mb-3">FAQ</p>
            <h2 className="lp-h2 mb-8">Questions</h2>
            <div className="space-y-3">
              {FAQ.map((f, i) => {
                const open = openFaq === i;
                return (
                  <div key={f.q} className="card">
                    <h3>
                      <button
                        type="button"
                        className="w-full flex items-center justify-between gap-4 text-left px-5 py-4 min-h-[56px] text-ink font-medium"
                        aria-expanded={open}
                        aria-controls={`faq-${i}`}
                        onClick={() => setOpenFaq(open ? null : i)}
                      >
                        {f.q}
                        <ChevronDown size={18} className={`shrink-0 transition-transform ${open ? 'rotate-180 text-brass' : 'text-muted'}`} aria-hidden="true" />
                      </button>
                    </h3>
                    <div id={`faq-${i}`} hidden={!open} className="px-5 pb-5 text-sm text-ink2/85 leading-relaxed">{f.a}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        {/* Final call */}
        <section className="lp-section">
          <div className="lp-wrap">
            <div className="lp-cta">
              <h2 className="lp-h2">Your next long episode is ten shorts away.</h2>
              <button type="button" onClick={onLaunchApp} className="btn-primary px-7 py-3 text-base">
                open the studio <ArrowRight size={17} aria-hidden="true" />
              </button>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-wrap flex flex-col md:flex-row md:items-center justify-between gap-4 py-8">
          <div className="flex items-center gap-3">
            <img src="/logo-synapse.svg" alt="" className="w-7 h-7 rounded-lg" width="28" height="28" />
            <span className="text-sm text-muted">© {new Date().getFullYear()} Synapse AI</span>
          </div>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-muted">
            <a href="#features" className="hover:text-ink transition-colors">Features</a>
            <a href="#faq" className="hover:text-ink transition-colors">FAQ</a>
            <a href="https://github.com/mutonby/openshorts" target="_blank" rel="noopener noreferrer" className="hover:text-ink transition-colors">
              Built on OpenShorts (MIT)
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
