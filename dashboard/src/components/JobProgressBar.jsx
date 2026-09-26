import React, { useEffect } from 'react';

const STAGES = {
    queued: 'waiting for a free slot',
    starting: 'starting',
    downloading: 'downloading the video',
    transcribing: 'transcribing the audio',
    analyzing: 'AI is picking the viral moments',
    rendering: 'rendering clips',
    publishing: 'scheduling the best clips on upload-post',
    done: 'done',
    // Story Channel renders (story.py)
    voice: 'narrating the script',
    images: 'drawing and animating the scenes',
    mixing: 'mixing voice and music',
    captions: 'burning the captions',
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
 */
export default function JobProgressBar({ progress }) {
    const percent = progress?.percent ?? 0;

    useEffect(() => {
        const base = document.title.replace(/^\d+% · /, '');
        document.title = `${percent}% · ${base}`;
        return () => { document.title = document.title.replace(/^\d+% · /, ''); };
    }, [percent]);

    const stage = STAGES[progress?.stage] || progress?.stage || 'starting';
    const eta = progress?.eta_seconds;

    return (
        <div className="mb-4 sm:mb-5">
            <div className="flex items-end justify-between gap-3 mb-2">
                <div className="min-w-0">
                    <p className="text-sm text-ink lowercase truncate">{stage}…</p>
                    <p className="readout mt-0.5 flex flex-wrap gap-x-2">
                        {progress?.clips_total ? <span>clips {progress.clips_done}/{progress.clips_total}</span> : null}
                        {eta ? <span className="text-brass">~{fmt(eta)} left</span> : null}
                        {progress?.elapsed_seconds ? <span className="text-muted">{fmt(progress.elapsed_seconds)} elapsed</span> : null}
                    </p>
                </div>
                <span className="font-display text-3xl text-ink tabular-nums leading-none">{percent}<span className="text-lg text-muted">%</span></span>
            </div>
            <div className="h-2 rounded-full bg-paper3 overflow-hidden">
                <div
                    className="h-full rounded-full bg-brass transition-[width] duration-700 ease-out"
                    style={{ width: `${Math.max(2, percent)}%` }}
                />
            </div>
        </div>
    );
}
