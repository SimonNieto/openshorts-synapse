import React, { useEffect } from 'react';
import { Check } from 'lucide-react';

const STAGES = {
    queued: 'Waiting for a free slot',
    starting: 'Starting',
    downloading: 'Downloading the video',
    transcribing: 'Transcribing the audio',
    analyzing: 'The AI is picking the viral moments',
    rendering: 'Rendering clips',
    publishing: 'Scheduling the best clips on Upload-Post',
    done: 'Done',
    // Story Channel renders (story.py)
    voice: 'Narrating the script',
    images: 'Drawing and animating the scenes',
    mixing: 'Mixing voice and music',
    captions: 'Burning the captions',
};

// The pathway, one node per stage the pipeline really reports (app.py
// _job_progress for clips, story.py progress() for Story Channel). Nothing
// here is estimated: a node is done once the job has moved past its stage.
const PIPELINES = {
    clips: [
        { label: 'Source', stages: ['downloading'] },
        { label: 'Transcribe', stages: ['transcribing'] },
        { label: 'Find moments', stages: ['analyzing'] },
        { label: 'Render', stages: ['rendering'] },
        // Only exists when the job auto-publishes: shown once it starts.
        { label: 'Publish', stages: ['publishing'], optional: true },
        { label: 'Ready', stages: ['done'] },
    ],
    story: [
        { label: 'Voice', stages: ['voice'] },
        { label: 'Scenes', stages: ['images'] },
        { label: 'Mix', stages: ['mixing'] },
        { label: 'Captions', stages: ['captions'] },
        { label: 'Ready', stages: ['done'] },
    ],
};

const pipelineOf = (stage) => {
    if (PIPELINES.story.some((s) => s.stages.includes(stage) && stage !== 'done')) return 'story';
    if (PIPELINES.clips.some((s) => s.stages.includes(stage) && stage !== 'done')) return 'clips';
    return null;
};

// The pathway runs down the panel on phones and wherever it shares the row with
// another pane (md → xl, where the job panel is ~55% wide), and across it where
// it has the room (sm → md full width, xl up). Classes spelled out in full so
// Tailwind sees them.
const PATH = {
    ol: 'sm:grid-flow-col sm:auto-cols-fr md:grid-flow-row md:auto-cols-auto xl:grid-flow-col xl:auto-cols-fr',
    li: 'sm:flex-col sm:gap-2.5 sm:pb-0 sm:pr-3 md:flex-row md:gap-3 md:pb-5 md:pr-0 xl:flex-col xl:gap-2.5 xl:pb-0 xl:pr-3',
    filament: 'sm:left-[22px] sm:right-1.5 sm:top-[7.5px] sm:bottom-auto sm:h-px sm:w-auto '
        + 'md:left-[7.5px] md:right-auto md:top-5 md:bottom-1 md:h-auto md:w-px '
        + 'xl:left-[22px] xl:right-1.5 xl:top-[7.5px] xl:bottom-auto xl:h-px xl:w-auto',
    fillDown: 'sm:hidden md:block xl:hidden',
    fillAcross: 'sm:block md:hidden xl:block',
    node: 'sm:mt-0 md:mt-0.5 xl:mt-0',
    text: 'sm:block md:flex xl:block',
    detail: 'sm:block sm:mt-1 md:inline md:mt-0 xl:block xl:mt-1',
};

const fmt = (s) => {
    if (s == null) return '';
    const m = Math.floor(s / 60);
    return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}` : `${m}:${String(s % 60).padStart(2, '0')}`;
};

/**
 * The job's real progress (app.py _job_progress), not an animation: weighted
 * by stage and, while rendering, by clips actually finished. Also mirrors the
 * percent in the browser tab title so it can be followed from another tab.
 *
 * Drawn as a synapse pathway: one node per pipeline stage on a hairline
 * filament — done nodes solid, the current one firing in the signal colour,
 * the rest hollow. `pipeline` ('clips' | 'story') pins the pathway; without
 * it the pathway appears once the reported stage tells which pipeline runs.
 */
export default function JobProgressBar({ progress, pipeline }) {
    const percent = progress?.percent ?? 0;

    useEffect(() => {
        const base = document.title.replace(/^\d+% · /, '');
        document.title = `${percent}% · ${base}`;
        return () => { document.title = document.title.replace(/^\d+% · /, ''); };
    }, [percent]);

    const rawStage = progress?.stage;
    const stage = STAGES[rawStage] || rawStage || 'Starting';
    const eta = progress?.eta_seconds;

    const kind = pipeline || pipelineOf(rawStage);
    const steps = kind
        ? PIPELINES[kind].filter((s) => !s.optional || s.stages.includes(rawStage))
        : [];
    const current = steps.findIndex((s) => s.stages.includes(rawStage));
    const clipsRatio = progress?.clips_total
        ? Math.min(1, (progress.clips_done || 0) / progress.clips_total)
        : 0;

    const meta = [
        progress?.clips_total ? `Clips ${progress.clips_done}/${progress.clips_total}` : null,
        eta ? `~${fmt(eta)} left` : null,
        progress?.elapsed_seconds ? `${fmt(progress.elapsed_seconds)} elapsed` : null,
    ].filter(Boolean);

    return (
        <div className="mb-6">
            <div className="flex items-end justify-between gap-4">
                <div className="min-w-0">
                    <p className="readout">Now</p>
                    {/* Announced when the stage changes; the clock below is not. */}
                    <p className="mt-1 text-base sm:text-lg font-medium text-ink leading-snug break-words" aria-live="polite">
                        {stage}…
                    </p>
                    {meta.length > 0 && (
                        <p className="readout mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
                            {meta.map((m) => <span key={m}>{m}</span>)}
                        </p>
                    )}
                </div>
                <p className="font-quote text-5xl sm:text-6xl text-ink leading-none tabular-nums shrink-0" aria-hidden="true">
                    {percent}<span className="text-2xl sm:text-3xl text-muted">%</span>
                </p>
            </div>

            <div
                role="progressbar"
                aria-label="Job progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={percent}
                aria-valuetext={`${percent}% · ${stage}`}
                className="relative mt-4 h-0.5 rounded-full bg-[color:var(--color-rule-2)] overflow-hidden"
            >
                <div
                    className="absolute inset-y-0 left-0 rounded-full bg-ink transition-[width] duration-700 ease-out"
                    style={{ width: `${Math.max(2, percent)}%` }}
                />
            </div>

            {steps.length > 0 && (
                <ol className={`mt-6 grid ${PATH.ol}`} aria-label="Pipeline steps">
                    {steps.map((step, i) => {
                        const done = current >= 0 && i < current;
                        const now = i === current;
                        const last = i === steps.length - 1;
                        // While rendering, the filament to the next node fills with
                        // the clips really finished — the only stage that reports it.
                        const fill = done ? 1 : now && step.stages.includes('rendering') ? clipsRatio : 0;
                        return (
                            <li
                                key={step.label}
                                className={`relative flex gap-3 pb-5 last:pb-0 ${PATH.li}`}
                                aria-current={now ? 'step' : undefined}
                            >
                                {!last && (
                                    <span
                                        aria-hidden="true"
                                        className={`absolute left-[7.5px] top-5 bottom-1 w-px bg-[color:var(--color-rule-2)] ${PATH.filament}`}
                                    >
                                        <span
                                            className={`absolute left-0 top-0 w-full bg-ink transition-[height] duration-700 ease-out ${PATH.fillDown}`}
                                            style={{ height: `${fill * 100}%` }}
                                        />
                                        <span
                                            className={`absolute left-0 top-0 h-full bg-ink transition-[width] duration-700 ease-out hidden ${PATH.fillAcross}`}
                                            style={{ width: `${fill * 100}%` }}
                                        />
                                    </span>
                                )}
                                <span
                                    aria-hidden="true"
                                    className={`relative z-10 mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-colors duration-500 ${PATH.node}
                                        ${done ? 'border-ink bg-ink text-paper'
                                            : now ? 'border-vermilion bg-paper2'
                                                : 'border-muted bg-paper2'}`}
                                >
                                    {done && <Check size={10} strokeWidth={3} />}
                                    {now && <span className="neural-node h-2 w-2 rounded-full bg-vermilion" />}
                                </span>
                                <span className={`min-w-0 flex flex-wrap items-baseline gap-x-2 ${PATH.text}`}>
                                    <span className={`text-sm leading-tight ${now ? 'text-ink font-medium' : done ? 'text-ink2' : 'text-muted'}`}>
                                        {step.label}
                                    </span>
                                    <span className="sr-only">
                                        {done ? ' — done' : now ? ' — in progress' : ' — to come'}
                                    </span>
                                    {now && (
                                        <span className={`readout ${PATH.detail}`} aria-hidden="true">
                                            {step.stages.includes('rendering') && progress?.clips_total
                                                ? `${progress.clips_done}/${progress.clips_total}`
                                                : 'Now'}
                                        </span>
                                    )}
                                </span>
                            </li>
                        );
                    })}
                </ol>
            )}
        </div>
    );
}
