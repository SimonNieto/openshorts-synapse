import React from 'react';
import { KeyRound, ArrowRight } from 'lucide-react';

// Banner for advanced tools (AI Shorts) that use fal.ai + ElevenLabs.
// These are BYOK: the plan covers the script/orchestration, the user brings their
// own keys for the premium generation. If they have no plan yet, also nudge trial.
export default function AdvancedBanner({ needsPlan, onKeys }) {
  return (
    <aside
      aria-label="Advanced tool"
      className="card mx-3 sm:mx-6 mt-3 px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-5 shrink-0 animate-fade"
    >
      <div className="flex items-start gap-3 text-sm min-w-0">
        <span aria-hidden="true" className="mt-0.5 h-8 w-8 shrink-0 rounded-input border border-rule2 bg-paper3 flex items-center justify-center text-ink2">
          <KeyRound size={15} />
        </span>
        <div className="min-w-0">
          <p className="readout">Advanced tool</p>
          <p className="mt-0.5 text-ink2 leading-relaxed">
            {needsPlan
              ? <>Sign in with <span className="font-medium text-ink">Google</span> to unlock free. This tool also uses your own <span className="font-medium text-ink">fal.ai + ElevenLabs</span> keys (you pay those providers).</>
              : <>AI video &amp; voice generation use your own <span className="font-medium text-ink">fal.ai + ElevenLabs</span> keys — add them in Settings. Script &amp; orchestration are included in your plan.</>}
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={needsPlan ? () => { window.location.hash = '#/pricing'; } : onKeys}
        className="btn-ghost shrink-0 text-xs px-3.5 py-2 w-full sm:w-auto"
      >
        {needsPlan ? <>See plans <ArrowRight size={14} aria-hidden="true" /></> : 'Add keys'}
      </button>
    </aside>
  );
}
