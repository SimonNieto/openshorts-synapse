import { useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';

/**
 * The single modal shell for the app (design.md).
 * Dark overlay (no backdrop-blur), a raised graphite sheet with a hairline.
 * Escape closes it, Tab stays inside it, and focus goes back to whatever
 * opened it when it closes.
 *
 * Props:
 *  - isOpen / onClose
 *  - title (string, Geist headline, sentence case) — optional
 *  - eyebrow (string, mono UPPERCASE micro label above title) — optional
 *  - size: 'sm' | 'md' | 'lg' | 'xl' (max width; default 'md')
 *  - children: body content
 *  - footer: optional node pinned under the body
 *  - hideClose: hide the X button
 *  - dismissOnOverlay: close on a click outside the panel (default true; editors
 *    holding unsaved adjustments pass false — Escape and the X still close)
 */
const SIZES = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
  xl: 'max-w-5xl',
};

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function Modal({ isOpen, onClose, title, eyebrow, size = 'md', children, footer, hideClose = false, dismissOnOverlay = true }) {
  const panelRef = useRef(null);
  const titleId = useId();
  // Latest onClose without re-running the open/close effect on every render.
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const opener = document.activeElement;
    const panel = panelRef.current;
    // Land on the first field/button inside, else on the panel itself.
    const first = panel?.querySelector(FOCUSABLE);
    (first || panel)?.focus({ preventScroll: true });

    const onKey = (e) => {
      if (e.key === 'Escape' && closeRef.current) {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== 'Tab' || !panel) return;
      const items = [...panel.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null);
      if (!items.length) { e.preventDefault(); return; }
      const head = items[0];
      const tail = items[items.length - 1];
      if (e.shiftKey && document.activeElement === head) { e.preventDefault(); tail.focus(); }
      else if (!e.shiftKey && document.activeElement === tail) { e.preventDefault(); head.focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      if (opener && typeof opener.focus === 'function' && document.contains(opener)) opener.focus({ preventScroll: true });
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    /* Phone: a bottom sheet — anchored to the thumb, edge to edge, and free to
       run taller than a centred dialog whose 4px side margins wasted the only
       width there was. From sm up it is the centred dialog it always was. */
    <div
      className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center bg-black/70 p-0 sm:p-4 animate-fade"
      onMouseDown={(e) => { if (dismissOnOverlay && e.target === e.currentTarget && onClose) onClose(); }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        tabIndex={-1}
        className={`card-print relative w-full ${SIZES[size] || SIZES.md} max-h-[92vh] sm:max-h-[90vh] flex flex-col
          rounded-b-none sm:rounded-card animate-sheet-up sm:animate-none focus:outline-none`}
      >
        {/* Grab handle: the affordance that says "this sheet closes downward". */}
        <div className="sm:hidden pt-2.5 pb-1 flex justify-center shrink-0" aria-hidden="true">
          <span className="w-9 h-1 rounded-full bg-[color:var(--color-rule-2)]" />
        </div>
        {!hideClose && onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="absolute top-2 right-2 sm:top-3 sm:right-3 z-10 w-11 h-11 flex items-center justify-center rounded-input text-muted hover:text-ink hover:bg-paper3 transition-colors"
          >
            <X size={18} aria-hidden="true" />
          </button>
        )}
        {(title || eyebrow) && (
          <div className="px-4 sm:px-6 pt-3 sm:pt-6 pb-4 border-b border-rule shrink-0">
            {eyebrow && <p className="eyebrow mb-1.5">{eyebrow}</p>}
            {title && <h2 id={titleId} className="font-display text-xl sm:text-2xl text-ink leading-tight break-words pr-10">{title}</h2>}
          </div>
        )}
        <div className="px-4 sm:px-6 py-5 overflow-y-auto overscroll-contain custom-scrollbar grow">
          {children}
        </div>
        {footer && (
          <div className="px-4 sm:px-6 py-4 border-t border-rule shrink-0 safe-bottom">
            {footer}
          </div>
        )}
        {!footer && <div className="sm:hidden safe-bottom" />}
      </div>
    </div>
  );
}
