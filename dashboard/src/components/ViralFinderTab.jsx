import React, { useState } from 'react';
import { Loader2, Flame, ExternalLink, Eye } from 'lucide-react';
import { apiJson } from '../lib/api';

function formatViews(n) {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, '')}K`;
    return String(n);
}

// A ready-made list of the most-viewed Shorts in a niche (YouTube Data API),
// so a repost/clipping channel has source material to watch and pick from
// instead of hunting for it by hand. Links out to watch on YouTube — nothing
// here downloads or embeds the video itself.
export default function ViralFinderTab() {
    const [niche, setNiche] = useState(() => {
        try { return localStorage.getItem('openshorts_niche') || ''; } catch { return ''; }
    });
    const [includeShorts, setIncludeShorts] = useState(true);
    const [includeVideos, setIncludeVideos] = useState(false);
    const [shorts, setShorts] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleSearch = async (e) => {
        e.preventDefault();
        if (!niche.trim() || loading) return;
        setLoading(true);
        setError('');
        setShorts(null);
        try {
            const data = await apiJson('/api/viral-shorts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    niche, max_results: 20,
                    include_shorts: includeShorts, include_videos: includeVideos,
                }),
            });
            setShorts(data.shorts || []);
        } catch (e) {
            setError(e.detail || e.message || 'Search failed');
        } finally {
            setLoading(false);
        }
    };

    // Neither checked would silently search nothing useful — keep one
    // always on by re-checking "Shorts" instead of letting this go empty.
    const toggleShorts = () => {
        setIncludeShorts((v) => {
            const next = !v;
            if (!next && !includeVideos) setIncludeVideos(true);
            return next;
        });
    };
    const toggleVideos = () => {
        setIncludeVideos((v) => {
            const next = !v;
            if (!next && !includeShorts) setIncludeShorts(true);
            return next;
        });
    };

    return (
        <div className="h-full overflow-y-auto p-8 max-w-5xl mx-auto animate-fade">
            <p className="eyebrow mb-1.5">09 · VIRAL FINDER</p>
            <h1 className="font-display lowercase text-2xl text-ink mb-2">Find viral shorts</h1>
            <p className="text-muted text-sm mb-8 lowercase">
                Type a niche and see the most-viewed Shorts for it right now (YouTube Data API) — watch one,
                then feed it into the Viral Clip Reworker if it's worth reposting.
            </p>

            <form onSubmit={handleSearch} className="flex flex-col sm:flex-row gap-2 mb-3">
                <input
                    type="text"
                    value={niche}
                    onChange={(e) => setNiche(e.target.value)}
                    className="input-field flex-1"
                    placeholder="e.g. Joe Rogan podcast clips"
                />
                <button type="submit" disabled={!niche.trim() || loading} className="btn-primary px-4 py-2.5 text-sm flex items-center gap-2 shrink-0">
                    {loading ? <Loader2 size={14} className="animate-spin" /> : <Flame size={14} />}
                    {loading ? 'searching…' : 'find viral shorts'}
                </button>
            </form>

            <div className="flex items-center gap-5 mb-8">
                <label className="flex items-center gap-2 text-sm text-muted cursor-pointer select-none">
                    <input type="checkbox" checked={includeShorts} onChange={toggleShorts} className="accent-[var(--color-accent)]" />
                    Shorts
                </label>
                <label className="flex items-center gap-2 text-sm text-muted cursor-pointer select-none">
                    <input type="checkbox" checked={includeVideos} onChange={toggleVideos} className="accent-[var(--color-accent)]" />
                    Videos
                </label>
            </div>

            {error && <p className="text-danger text-sm mb-6">{error}</p>}

            {shorts && shorts.length === 0 && (
                <p className="text-center text-muted py-20 lowercase">No Shorts found for this niche.</p>
            )}

            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
                {(shorts || []).map((s) => (
                    <a
                        key={s.videoId}
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="card card-hover overflow-hidden group block"
                    >
                        <div className="aspect-video bg-black relative overflow-hidden">
                            {s.thumbnailUrl && (
                                <img src={s.thumbnailUrl} alt="" className="w-full h-full object-cover" loading="lazy" />
                            )}
                            {includeShorts && includeVideos && (
                                <span className="absolute top-1.5 left-1.5 readout px-1.5 py-0.5 rounded bg-black/70 text-white uppercase">
                                    {s.videoType === 'video' ? 'video' : 'short'}
                                </span>
                            )}
                            <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center">
                                <ExternalLink size={20} className="text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                            </div>
                        </div>
                        <div className="p-3">
                            <p className="text-sm text-ink font-medium line-clamp-2 mb-1" title={s.title}>{s.title}</p>
                            <div className="flex items-center justify-between">
                                <span className="readout truncate">{s.channelTitle}</span>
                                <span className="readout flex items-center gap-1 shrink-0 text-brass">
                                    <Eye size={11} /> {formatViews(s.viewCount)}
                                </span>
                            </div>
                        </div>
                    </a>
                ))}
            </div>
        </div>
    );
}
