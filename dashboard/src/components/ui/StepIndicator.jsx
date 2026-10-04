import { Check } from 'lucide-react';

/**
 * The single wizard stepper (design.md) — shared by ThumbnailStudio and
 * SaaShortsTab. Mono ordinals, hairline connectors, brass current step.
 *
 * Props:
 *  - steps: string[] (labels)
 *  - current: index of the active step
 *  - onStepClick(index)? — optional, only past steps are clickable
 */
export default function StepIndicator({ steps, current, onStepClick }) {
  return (
    <ol className="flex items-center w-full" aria-label="Progress">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        const clickable = done && typeof onStepClick === 'function';
        return (
          <li key={label} className={`flex items-center ${i < steps.length - 1 ? 'flex-1' : ''}`}>
            <button
              type="button"
              disabled={!clickable}
              onClick={() => clickable && onStepClick(i)}
              className={`flex items-center gap-2 shrink-0 ${clickable ? 'cursor-pointer' : 'cursor-default'}`}
              aria-current={active ? 'step' : undefined}
            >
              <span
                className={`w-7 h-7 rounded-full border-[1.5px] flex items-center justify-center font-mono text-[11px] transition-colors duration-200
                  ${active ? 'border-vermilion bg-vermilion text-paper2' : done ? 'border-ink2 bg-ink text-paper2' : 'border-rule2 bg-paper2 text-muted'}`}
              >
                {done ? <Check size={12} aria-hidden="true" /> : i + 1}
              </span>
              <span className={`hidden sm:block text-sm ${active ? 'text-ink font-semibold' : done ? 'text-ink2' : 'text-muted'}`}>
                {label}
              </span>
            </button>
            {i < steps.length - 1 && (
              <span className={`h-[1.5px] flex-1 mx-1.5 sm:mx-3 ${done ? 'bg-ink' : 'bg-[color:var(--color-rule-2)]'}`} aria-hidden="true" />
            )}
          </li>
        );
      })}
    </ol>
  );
}
