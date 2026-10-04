import React from 'react';
import { ArrowLeft, ArrowUpRight } from 'lucide-react';

// The canonical legal documents are the static pages emitted at build time by
// vite-plugin-seo from seo/legal.js (/terms, /privacy, /legal-notice + Spanish
// versions). This in-app view is a hub with the plain-language summary and
// links, so the SPA route (#legal) and the crawlable pages never drift: the
// full text lives in exactly one place.
// Design: typography only, 65ch measure (design.md « Pages may differ on »).
const LAST_UPDATED = '2026-09-04';
const SUPPORT_EMAIL = 'info@openshorts.app';

const DOCS = [
    {
        title: 'Terms of Service',
        desc: 'What you can do with the service, your content rights, billing, EU withdrawal, and acceptable use.',
        href: '/terms',
        es: '/terminos',
    },
    {
        title: 'Privacy Policy',
        desc: 'What we store, for how long, which providers touch it, and your GDPR rights. Nothing non-essential loads until you accept it.',
        href: '/privacy',
        es: '/privacidad',
    },
    {
        title: 'Legal Notice',
        desc: 'Who operates openshorts.app: TONVI TECH SL, Málaga, Spain (LSSI-CE art. 10).',
        href: '/legal-notice',
        es: '/aviso-legal',
    },
    {
        title: 'Refund Policy',
        desc: 'Charged in the last 14 days and have not used the service since? We refund it in full, no reason needed.',
        href: '/refunds',
        es: '/reembolsos',
    },
    {
        title: 'Report Illegal Content',
        desc: 'How to report infringing or illegal content, what we do with a notice, and how to challenge a removal (DSA arts. 16-17).',
        href: '/report-content',
        es: '/reportar-contenido',
    },
];

export default function Legal() {
    const handleBack = () => {
        window.location.hash = '';
    };

    return (
        <div className="min-h-screen text-ink2">
            <header className="border-b border-rule sticky top-0 bg-paper z-10">
                <div className="max-w-[65ch] mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-3">
                    <button type="button" onClick={handleBack} className="btn-quiet">
                        <ArrowLeft size={16} aria-hidden="true" /> Back
                    </button>
                    <span className="brand-word text-base">Synapse <span className="brand-ai">AI</span></span>
                </div>
            </header>

            <main id="main-content" className="max-w-[65ch] mx-auto px-4 sm:px-6 py-12 sm:py-16">
                <p className="readout mb-3">Legal</p>
                <h1 className="page-title mb-3">Terms and privacy</h1>
                <p className="readout mb-12">
                    Last updated: <time dateTime={LAST_UPDATED}>{LAST_UPDATED}</time>
                </p>

                <section aria-labelledby="legal-short" className="mb-12">
                    <h2 id="legal-short" className="font-display text-xl text-ink mb-4">The short version</h2>
                    <ul className="list-disc marker:text-muted pl-5 space-y-3 text-[15px] leading-7 text-ink2">
                        <li><strong className="text-ink font-semibold">Your videos and clips are yours.</strong> We never use your content to train AI models.</li>
                        <li><strong className="text-ink font-semibold">You must have the rights</strong> to every video you upload or link, and you are the publisher of what you post.</li>
                        <li><strong className="text-ink font-semibold">No advertising trackers.</strong> Audience measurement is first-party and stays off until you accept it; free-plan clips are deleted after 7 days.</li>
                        <li><strong className="text-ink font-semibold">Cancel anytime</strong> from your account. Charged in the last 14 days and never used it? Full refund. EU consumers keep their 14-day withdrawal right on top of that.</li>
                        <li><strong className="text-ink font-semibold">Delete everything anytime.</strong> Account &rarr; Delete account erases your projects, clips and keys on the spot. No email to us, no waiting.</li>
                    </ul>
                </section>

                <section aria-labelledby="legal-docs" className="mb-12">
                    <h2 id="legal-docs" className="font-display text-xl text-ink mb-2">The full documents</h2>
                    <p className="text-[15px] leading-7 text-ink2 mb-4">
                        The full documents (English, with Spanish versions that prevail for consumers in Spain):
                    </p>
                    <ul className="border-t border-rule">
                        {DOCS.map(({ title, desc, href, es }) => (
                            <li key={href} className="border-b border-rule py-5">
                                <a
                                    href={href}
                                    className="group inline-flex items-center gap-1.5 text-ink font-semibold text-base underline decoration-ink/30 underline-offset-4 hover:decoration-current transition-colors"
                                >
                                    {title}
                                    <ArrowUpRight size={15} className="text-muted group-hover:text-ink transition-colors" aria-hidden="true" />
                                </a>
                                <p className="text-[15px] leading-7 text-muted mt-1">{desc}</p>
                                <p className="text-sm text-muted mt-1">
                                    <a href={es} lang="es" className="underline decoration-ink/30 underline-offset-2 hover:text-ink hover:decoration-current transition-colors">
                                        también en español: {es}
                                    </a>
                                </p>
                            </li>
                        ))}
                    </ul>
                </section>

                <p className="text-sm leading-7 text-muted">
                    openshorts.app is operated by TONVI TECH SL (CIF B-19780394), Calle Puerta del Mar 18,
                    29005 Málaga, Spain. Questions:{' '}
                    <a className="text-ink2 underline decoration-ink/30 underline-offset-2 hover:text-ink hover:decoration-current transition-colors" href={`mailto:${SUPPORT_EMAIL}`}>
                        {SUPPORT_EMAIL}
                    </a>
                    . Self-hosted instances are operated by their administrators under the MIT License; these
                    documents govern the hosted service only.
                </p>
            </main>
        </div>
    );
}
