/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Synapse AI · Nuit synapse — values mirror tokens.css (kept literal so
        // Tailwind alpha modifiers like bg-brass/10 compile). The names are the
        // old theme's (brass = THE accent, now electric cyan; coral = the second,
        // now neon violet) so every page re-themes without touching its classes.
        paper: "oklch(11.5% 0.032 278 / <alpha-value>)",
        paper2: "oklch(15% 0.038 280 / <alpha-value>)",
        paper3: "oklch(19.5% 0.045 282 / <alpha-value>)",
        ink: "oklch(97% 0.012 250 / <alpha-value>)",
        ink2: "oklch(87% 0.022 255 / <alpha-value>)",
        muted: "oklch(67% 0.035 262 / <alpha-value>)",
        brass: "oklch(81% 0.14 212 / <alpha-value>)",
        brassink: "oklch(15% 0.045 255 / <alpha-value>)",
        coral: "oklch(68% 0.22 300 / <alpha-value>)",
        cyan: "oklch(81% 0.14 212 / <alpha-value>)",
        violet: "oklch(68% 0.22 300 / <alpha-value>)",
        ok: "oklch(78% 0.13 160 / <alpha-value>)",
        warn: "oklch(80% 0.14 80 / <alpha-value>)",
        danger: "oklch(66% 0.2 20 / <alpha-value>)",
        // legacy aliases so untouched files degrade gracefully
        background: "oklch(11.5% 0.032 278 / <alpha-value>)",
        surface: "oklch(15% 0.038 280 / <alpha-value>)",
        primary: "oklch(81% 0.14 212 / <alpha-value>)",
        accent: "oklch(68% 0.22 300 / <alpha-value>)",
      },
      fontFamily: {
        display: "var(--font-display)",
        body: "var(--font-body)",
        sans: "var(--font-body)",
        serif: "var(--font-display)",
        mono: "var(--font-mono)",
      },
      borderColor: {
        rule: "var(--color-rule)",
        rule2: "var(--color-rule-2)",
      },
      borderRadius: {
        card: "var(--radius-card)",
        input: "var(--radius-input)",
      },
      fontSize: {
        micro: ["10.5px", { letterSpacing: "0.10em" }],
      },
      transitionTimingFunction: {
        out: "var(--ease-out)",
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade': 'fadeIn 0.4s var(--ease-out)',
        // mobile shell: the nav drawer flies in from the edge, sheets rise
        'slide-in-left': 'slideInLeft 0.24s var(--ease-out)',
        'sheet-up': 'sheetUp 0.26s var(--ease-out)',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        slideInLeft: {
          from: { transform: 'translateX(-100%)' },
          to: { transform: 'translateX(0)' },
        },
        sheetUp: {
          from: { transform: 'translateY(12px)', opacity: '0' },
          to: { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
