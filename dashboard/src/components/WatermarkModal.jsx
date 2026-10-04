import React, { useState } from 'react';
import Modal from './ui/Modal';

const DISMISS_KEY = 'os_watermark_notice_dismissed';

// eslint-disable-next-line react-refresh/only-export-components
export function watermarkNoticeDismissed() {
  try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch { return false; }
}

// Shown to free users before their first download: the clip carries a
// watermark, and upgrading removes it. Dismissible for good, like OpusClip's.
export default function WatermarkModal({ onClose, onContinue }) {
  const [dontShow, setDontShow] = useState(false);

  const close = (proceed) => {
    if (dontShow) {
      try { localStorage.setItem(DISMISS_KEY, '1'); } catch { /* ignore */ }
    }
    if (proceed) onContinue?.();
    onClose();
  };

  return (
    <Modal
      isOpen
      onClose={() => close(false)}
      eyebrow="Free plan"
      title="Upgrade to remove the watermark"
      size="md"
      footer={
        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
          <button type="button" onClick={() => close(true)} className="btn-ghost">
            Download anyway
          </button>
          <button
            type="button"
            onClick={() => { close(false); window.location.hash = '#/pricing'; }}
            className="btn-accent"
          >
            Upgrade
          </button>
        </div>
      }
    >
      <p className="text-ink2 text-sm leading-relaxed mb-5">
        Clips on the free plan carry the Synapse AI mark in the corner, and are
        kept for 7 days. Any paid plan exports them clean and keeps them for good.
      </p>

      {/* A sample clip, on black in a hairline frame */}
      <div className="h-56 flex items-center justify-center bg-black border border-rule2 rounded-input overflow-hidden mb-5">
        <video
          src="/demo/clip-vertical.mp4"
          autoPlay
          muted
          loop
          playsInline
          aria-hidden="true"
          className="h-full w-auto max-w-full object-contain"
        />
      </div>

      <label className="inline-flex items-center gap-2.5 min-h-[32px] [@media(pointer:coarse)]:min-h-[44px] text-sm text-ink2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={dontShow}
          onChange={(e) => setDontShow(e.target.checked)}
          className="w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer"
        />
        Don't show this again
      </label>
    </Modal>
  );
}
