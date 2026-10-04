import { useEffect, useLayoutEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, CheckCircle2, LayoutDashboard, Sparkles } from 'lucide-react';
import Modal from './ui/Modal';

const TOUR = [
  {
    target: '[data-tutorial="nav-clips"]',
    title: 'Clip Generator',
    body: 'This is the tool people come for. A long video in, vertical shorts out. The other menu items stay locked until you finish one run.',
  },
  {
    target: '[data-tutorial="source-tabs"]',
    title: 'Upload or paste a link',
    body: 'Drop an MP4, or switch to Video URL and paste YouTube, TikTok, Instagram…',
  },
  {
    target: '[data-tutorial="drop-zone"]',
    title: 'Your video',
    body: 'Click the box or paste the link here. Keep files under 500MB.',
  },
  {
    target: '[data-tutorial="output-format"]',
    title: 'Output format',
    body: '9:16 is TikTok, Reels and Shorts. Leave it unless you need a square feed post or landscape.',
  },
  {
    target: '[data-tutorial="generate"]',
    title: 'Generate',
    body: 'Tick that you have the rights, then generate. That is the whole first run.',
  },
];

function visibleTarget(selector) {
  return [...document.querySelectorAll(selector)].find((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2;
  }) || null;
}

function placeTip(rect, tipW, tipH, vw, vh) {
  const m = 12;
  const gap = 12;
  const mobile = vw < 640;
  if (mobile) {
    return {
      top: Math.max(m, vh - tipH - m - 8),
      left: m,
      width: vw - m * 2,
    };
  }
  let top = rect.bottom + gap;
  if (top + tipH > vh - m) top = rect.top - gap - tipH;
  if (top < m) top = m;
  let left = rect.left + rect.width / 2 - tipW / 2;
  left = Math.max(m, Math.min(left, vw - m - tipW));
  return { top, left, width: tipW };
}

/**
 * First-login Clip Generator tutorial.
 *  - intro: blocking modal
 *  - coach: Next/Back spotlight on each Clip Generator control
 *  - celebrate: modal after the first successful job
 *
 * QA: #app?tutorial=1
 */
export default function ClipTutorial({ phase, jobStatus, onStart, onSkip, onDismissCelebrate }) {
  const [step, setStep] = useState(0);
  const [spot, setSpot] = useState(null);

  useEffect(() => {
    if (phase === 'coach') setStep(0);
  }, [phase]);

  useLayoutEffect(() => {
    if (phase !== 'coach' || jobStatus === 'processing' || jobStatus === 'error') {
      setSpot(null);
      return;
    }
    const measure = () => {
      const spec = TOUR[step];
      if (!spec) { setSpot(null); return; }
      const el = visibleTarget(spec.target);
      if (el) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      const rect = el ? el.getBoundingClientRect() : null;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const r = (n) => Math.round(n);
      const mobile = vw < 640;
      const tipW = Math.min(360, vw - 24);
      const tipH = 220;
      const hole = rect
        ? { top: r(rect.top - 6), left: r(rect.left - 6), width: r(rect.width + 12), height: r(rect.height + 12) }
        : null;
      const rawTip = hole
        ? placeTip({ top: hole.top, bottom: hole.top + hole.height, left: hole.left, width: hole.width }, tipW, tipH, vw, vh)
        : { top: mobile ? vh - 240 : vh / 2 - 80, left: 12, width: vw - 24 };
      const tip = { top: r(rawTip.top), left: r(rawTip.left), width: r(rawTip.width) };
      setSpot((prev) => {
        const next = { hole, tip, mobile };
        try {
          if (prev && JSON.stringify(prev) === JSON.stringify(next)) return prev;
        } catch (_) { /* ignore */ }
        return next;
      });
    };
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [phase, step, jobStatus]);

  if (phase === 'intro') {
    return (
      <Modal isOpen hideClose eyebrow="First clips" title="Let's make your first shorts" size="md">
        <div className="flex items-start gap-3 mb-5">
          <span aria-hidden="true" className="w-10 h-10 rounded-input border border-rule2 bg-paper3 flex items-center justify-center shrink-0 text-ink">
            <LayoutDashboard size={18} />
          </span>
          <p className="text-sm text-ink2 leading-relaxed">
            People come here for <b className="text-ink font-medium">Clip Generator</b>: a long video in,
            vertical shorts out. We will walk the screen, then you run one video.
          </p>
        </div>
        <button type="button" onClick={onStart} className="btn-accent w-full">
          Show me around <ArrowRight size={16} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={onSkip}
          className="w-full mt-2 min-h-[44px] rounded-input text-muted hover:text-ink hover:bg-paper3 text-sm transition-colors"
        >
          I'll explore later
        </button>
      </Modal>
    );
  }

  if (phase === 'coach' && (jobStatus === 'processing' || jobStatus === 'error')) {
    return (
      <div
        className="fixed z-[80] left-3 right-3 md:left-auto md:right-6 md:w-[22rem]
          bottom-3 md:bottom-6 card-print p-4"
        role="status"
      >
        <p className="readout mb-1.5">First clips</p>
        <p className={`text-sm leading-relaxed ${jobStatus === 'error' ? 'text-danger' : 'text-ink2'}`}>
          {jobStatus === 'error'
            ? 'That run failed. Try another video — other tools stay locked until one job finishes.'
            : 'Hang on — Clip Generator is finding the moments and cutting vertical shorts.'}
        </p>
      </div>
    );
  }

  if (phase === 'coach') {
    const last = step >= TOUR.length - 1;
    const spec = TOUR[step] || TOUR[0];
    const onLast = () => setStep(TOUR.length);

    if (step >= TOUR.length) {
      return (
        <div
          className="fixed z-[80] inset-x-3 bottom-3 md:inset-x-auto md:right-6 md:bottom-6 md:max-w-sm
            card-print pl-4 pr-2 py-2 flex flex-wrap items-center gap-x-3 gap-y-1"
          role="status"
        >
          <p className="text-sm text-ink2 leading-snug flex-1 min-w-0 py-1.5">
            Your turn — add a video and generate.
          </p>
          <button
            type="button"
            onClick={onSkip}
            className="shrink-0 min-h-[44px] px-3 rounded-input text-sm text-muted hover:text-ink hover:bg-paper3 transition-colors"
          >
            Skip
          </button>
        </div>
      );
    }

    const hole = spot?.hole;
    const tip = spot?.tip;
    // The dim around the spotlight: the canvas itself, at 78%, so the page
    // recedes into the night instead of being washed out.
    const scrim = 'color-mix(in oklab, var(--color-paper) 78%, transparent)';

    return (
      <div className="fixed inset-0 z-[80]" role="dialog" aria-modal="true" aria-labelledby="clip-tutorial-title">
        {!hole && <div className="absolute inset-0" style={{ background: scrim }} />}
        {hole && (
          <div
            className="absolute rounded-input pointer-events-none border border-vermilion"
            style={{
              top: hole.top,
              left: hole.left,
              width: hole.width,
              height: hole.height,
              boxShadow: `0 0 0 9999px ${scrim}`,
            }}
          />
        )}
        <div
          className="absolute card-print p-4 sm:p-5 max-h-[min(70vh,24rem)] overflow-y-auto custom-scrollbar"
          style={{
            top: tip?.top ?? 16,
            left: tip?.left ?? 12,
            width: tip?.width ?? undefined,
            maxWidth: 'calc(100vw - 24px)',
          }}
        >
          <div className="flex items-center justify-between gap-3 mb-3">
            <p className="readout">Tour · step {step + 1} of {TOUR.length}</p>
            {/* where we are in the tour, as nodes on a filament */}
            <span aria-hidden="true" className="flex items-center gap-1.5">
              {TOUR.map((t, i) => (
                <span
                  key={t.target}
                  className={`h-1.5 rounded-full transition-all duration-200 ${i === step ? 'w-4 bg-ink' : i < step ? 'w-1.5 bg-ink2' : 'w-1.5 bg-[color:var(--color-rule-2)]'}`}
                />
              ))}
            </span>
          </div>
          <h3 id="clip-tutorial-title" className="font-display text-lg text-ink leading-tight mb-2">{spec.title}</h3>
          <p className="text-sm text-ink2 leading-relaxed mb-4">{spec.body}</p>
          <div className="flex flex-wrap items-center gap-2">
            {step > 0 && (
              <button type="button" onClick={() => setStep((s) => s - 1)} className="btn-ghost text-sm px-3">
                <ArrowLeft size={14} aria-hidden="true" /> Back
              </button>
            )}
            <button
              type="button"
              onClick={last ? onLast : () => setStep((s) => s + 1)}
              className="btn-primary text-sm px-4 ml-auto"
            >
              {last ? 'Got it' : 'Next'} <ArrowRight size={14} aria-hidden="true" />
            </button>
          </div>
          <button
            type="button"
            onClick={onSkip}
            className="mt-3 -ml-2 min-h-[40px] [@media(pointer:coarse)]:min-h-[44px] px-2 rounded-input text-xs text-muted hover:text-ink hover:bg-paper3 transition-colors"
          >
            Skip the tour and unlock the rest
          </button>
        </div>
      </div>
    );
  }

  if (phase === 'celebrate') {
    return (
      <Modal isOpen onClose={onDismissCelebrate} hideClose eyebrow="Done" title="You made your first clips" size="sm">
        <div className="text-center py-2">
          <span aria-hidden="true" className="inline-flex h-14 w-14 items-center justify-center rounded-full border border-rule2 bg-paper3 text-ok mb-4">
            <CheckCircle2 size={26} />
          </span>
          <p className="text-sm text-ink2 leading-relaxed mb-1">
            That is the whole product, on one video.
          </p>
          <p className="text-sm text-muted leading-relaxed mb-6">
            The other tools are unlocked. Come back to Clip Generator whenever you have another long video.
          </p>
          <button type="button" onClick={onDismissCelebrate} className="btn-accent w-full">
            <Sparkles size={16} aria-hidden="true" /> See my clips
          </button>
        </div>
      </Modal>
    );
  }

  return null;
}
