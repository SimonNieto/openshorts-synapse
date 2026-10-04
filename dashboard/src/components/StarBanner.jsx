import { Github, ArrowUpRight } from 'lucide-react';

export const REPO_URL = 'https://github.com/mutonby/openshorts';

// Small "star us" ask, once per job, while the clips render: that wait is the
// only dead time in the flow. Asking again on the finished clips made it two
// asks for the same job, and the old "free while it renders" wording put the
// word free next to the product name for anyone who missed the pun — the one
// thing our copy must never do. No incentive attached.
export default function StarBanner({ message = 'Synapse AI is built on OpenShorts, open source — give them a star?' }) {
  return (
    <a
      href={REPO_URL}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex items-center gap-3 min-h-[44px] px-3.5 py-2.5 rounded-card border border-rule text-sm text-ink2 hover:text-ink hover:border-rule2 hover:bg-paper3 transition-colors"
    >
      <Github size={16} aria-hidden="true" className="shrink-0 text-muted group-hover:text-ink transition-colors" />
      <span className="min-w-0 flex-1 leading-snug">
        {message}{' '}
        <span className="font-medium text-ink whitespace-nowrap">Star us on GitHub</span>
        <span className="sr-only"> (opens in a new tab)</span>
      </span>
      <ArrowUpRight size={15} aria-hidden="true" className="shrink-0 text-muted group-hover:text-ink transition-colors" />
    </a>
  );
}
