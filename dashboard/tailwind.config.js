/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Synapse AI · « Synapse · Graphite » — values mirror tokens.css (kept
        // literal so alpha modifiers like bg-brass/10 compile). Old names kept so
        // every page re-themes: brass / vermilion = THE accent (one desaturated
        // cyan), coral / cobalt = the quiet steel second. Colour is rare.
        paper: "oklch(14.5% 0.006 265 / <alpha-value>)",
        paper2: "oklch(18% 0.007 265 / <alpha-value>)",
        paper3: "oklch(22% 0.008 265 / <alpha-value>)",
        ink: "oklch(96.5% 0.003 265 / <alpha-value>)",
        ink2: "oklch(85% 0.005 265 / <alpha-value>)",
        muted: "oklch(66% 0.008 265 / <alpha-value>)",
        brass: "oklch(82% 0.095 212 / <alpha-value>)",
        brassink: "oklch(16% 0.02 240 / <alpha-value>)",
        coral: "oklch(78% 0.04 250 / <alpha-value>)",
        vermilion: "oklch(82% 0.095 212 / <alpha-value>)",
        vermilionsoft: "oklch(30% 0.04 220 / <alpha-value>)",
        cobalt: "oklch(78% 0.04 250 / <alpha-value>)",
        ok: "oklch(78% 0.1 160 / <alpha-value>)",
        warn: "oklch(82% 0.1 82 / <alpha-value>)",
        danger: "oklch(70% 0.15 22 / <alpha-value>)",
        // legacy aliases so untouched files degrade gracefully
        cyan: "oklch(82% 0.095 212 / <alpha-value>)",
        violet: "oklch(78% 0.04 250 / <alpha-value>)",
        background: "oklch(14.5% 0.006 265 / <alpha-value>)",
        surface: "oklch(18% 0.007 265 / <alpha-value>)",
        primary: "oklch(82% 0.095 212 / <alpha-value>)",
        accent: "oklch(78% 0.04 250 / <alpha-value>)",
      },
      fontFamily: {
        display: "var(--font-display)",
        body: "var(--font-body)",
        sans: "var(--font-body)",
        serif: "var(--font-display)",
        quote: "var(--font-quote)",
        mono: "var(--font-mono)",
      },
      borderColor: {
        rule: "var(--color-rule)",
        rule2: "var(--color-rule-2)",
      },
      boxShadow: {
        print: "var(--shadow-print)",
        "print-accent": "var(--shadow-print-accent)",
        sheet: "var(--shadow-sheet)",
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
