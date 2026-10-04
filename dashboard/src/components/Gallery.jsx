import React, { useState, useEffect, useRef, useCallback } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { getApiUrl } from '../config';
import GalleryCard from './GalleryCard';

const CLIPS_PER_PAGE = 20;

export default function Gallery() {
    const [clips, setClips] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState(null);
    const [hasMore, setHasMore] = useState(true);
    const [offset, setOffset] = useState(0);

    const loaderRef = useRef(null);

    const fetchClips = useCallback(async (currentOffset = 0, append = false) => {
        try {
            if (currentOffset === 0) setLoading(true);
            else setLoadingMore(true);

            const res = await fetch(
                getApiUrl(`/api/gallery/clips?limit=${CLIPS_PER_PAGE}&offset=${currentOffset}`)
            );
            if (!res.ok) throw new Error('Failed to fetch clips');
            const data = await res.json();

            const newClips = data.clips || [];

            if (append) {
                setClips(prev => [...prev, ...newClips]);
            } else {
                setClips(newClips);
            }

            setHasMore(data.has_more ?? newClips.length === CLIPS_PER_PAGE);
            setOffset(currentOffset + newClips.length);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
            setLoadingMore(false);
        }
    }, []);

    // Initial load
    useEffect(() => {
        fetchClips(0, false);
    }, [fetchClips]);

    // Infinite scroll observer
    useEffect(() => {
        if (!hasMore || loadingMore || loading) return;

        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0].isIntersecting && hasMore && !loadingMore) {
                    fetchClips(offset, true);
                }
            },
            { rootMargin: '200px', threshold: 0.1 }
        );

        const node = loaderRef.current;
        if (node) {
            observer.observe(node);
        }

        return () => {
            if (node) {
                observer.unobserve(node);
            }
        };
    }, [hasMore, loadingMore, loading, offset, fetchClips]);

    if (loading) {
        return (
            <div role="status" className="h-full flex items-center justify-center gap-3 text-muted animate-fade">
                <Loader2 size={18} className="animate-spin" aria-hidden="true" />
                <p className="text-sm">Loading your clips…</p>
            </div>
        );
    }

    if (error) {
        return (
            <div className="h-full flex items-center justify-center p-4 sm:p-8">
                <div role="alert" className="tray max-w-md w-full p-6 text-center">
                    <AlertCircle size={22} className="mx-auto mb-3 text-danger" aria-hidden="true" />
                    <h2 className="font-display text-lg text-ink">The gallery didn't load</h2>
                    <p className="text-sm text-muted mt-1.5 break-words">{error}</p>
                    <button
                        type="button"
                        onClick={() => {
                            setError(null);
                            setOffset(0);
                            fetchClips(0, false);
                        }}
                        className="btn-ghost mt-5"
                    >
                        Try again
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
            <div className="max-w-7xl mx-auto p-4 sm:p-8 space-y-8">
                <header className="flex flex-wrap items-end justify-between gap-4 border-b border-rule pb-6">
                    <div className="min-w-0">
                        <p className="eyebrow">Library</p>
                        <h2 className="page-title mt-2">Clip gallery</h2>
                        <p className="page-lede mt-2">Every clip you generated, with its title and caption ready to copy.</p>
                    </div>
                    <p className="flex items-baseline gap-2 shrink-0">
                        <span className="font-quote text-4xl text-ink leading-none">{clips.length}{hasMore ? '+' : ''}</span>
                        <span className="readout">{clips.length === 1 ? 'Clip' : 'Clips'}</span>
                    </p>
                </header>

                {clips.length === 0 ? (
                    <div className="tray p-5 sm:p-8 grid gap-6 sm:grid-cols-[minmax(0,15rem)_1fr] sm:items-center">
                        <figure className="w-full max-w-[15rem] mx-auto sm:mx-0">
                            <div className="aspect-[16/10] bg-black border border-rule2 rounded-card overflow-hidden">
                                <img src="/landing/dopamine.jpg" alt="" loading="lazy" className="w-full h-full object-cover" />
                            </div>
                            <figcaption className="readout mt-2">Drawn B-roll · dopamine</figcaption>
                        </figure>
                        <div>
                            <h3 className="font-display text-xl text-ink">No clips yet</h3>
                            <p className="text-sm text-muted mt-2 max-w-md leading-relaxed">Process a video and its clips will fill this gallery.</p>
                        </div>
                    </div>
                ) : (
                    <>
                        <ul className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-5 pb-10" aria-label="Clips">
                            {clips.map((clip) => (
                                <li key={`${clip.job_id}-${clip.index}`} className="flex">
                                    <GalleryCard clip={clip} />
                                </li>
                            ))}
                        </ul>

                        {/* Infinite scroll loader trigger */}
                        {hasMore && (
                            <div
                                ref={loaderRef}
                                className="flex justify-center py-8"
                                aria-live="polite"
                            >
                                {loadingMore && (
                                    <div className="flex items-center gap-2 text-muted">
                                        <Loader2 size={18} className="animate-spin" aria-hidden="true" />
                                        <span className="text-sm">Loading more clips…</span>
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
