import React from 'react';
import { Sparkles, ArrowRight } from 'lucide-react';

// Slim, non-blocking banner shown above a tool when a hosted user has no
// entitlement. Google-authed users get the free plan automatically, so this
// only fires for signed-out or magic-link-only accounts.
export default function TrialGate({ toolName = 'this' }) {
  return (
    <aside
      aria-label="Preview mode"
      className="card mx-3 sm:mx-6 mt-3 px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-5 shrink-0 animate-fade"
    >
      <div className="flex items-start gap-3 text-sm min-w-0">
        <span aria-hidden="true" className="mt-0.5 h-8 w-8 shrink-0 rounded-input border border-rule2 bg-paper3 flex items-center justify-center text-ink2">
          <Sparkles size={15} />
        </span>
        <div className="min-w-0">
          <p className="readout">Preview mode</p>
          <p className="mt-0.5 text-ink2 leading-relaxed">
            Sign in with <span className="font-medium text-ink">Google</span> to use {toolName} free —
            20 min/month, no credit card. <span className="text-muted">Or run it free by self-hosting.</span>
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={() => { window.location.hash = '#/pricing'; }}
        className="btn-primary shrink-0 text-xs px-4 py-2 w-full sm:w-auto"
      >
        Start free <ArrowRight size={14} aria-hidden="true" />
      </button>
    </aside>
  );
}
