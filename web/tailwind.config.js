/** @type {import('tailwindcss').Config} */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"), surface: v("surface"), fg: v("fg"), fg2: v("fg2"), muted: v("muted"),
        line: v("line"), accent: v("accent"), "accent-ink": v("accent-ink"),
        red: v("red"), orange: v("orange"), green: v("green"), purple: v("purple"), teal: v("teal"),
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Text"', '"Helvetica Neue"', "system-ui", "sans-serif"],
        mono: ['ui-monospace', '"SF Mono"', "Menlo", "monospace"],
      },
      borderRadius: { xl: "14px", "2xl": "18px", "3xl": "24px" },
      boxShadow: {
        card: "0 1px 1px rgba(0,0,0,0.02), 0 2px 10px rgba(0,0,0,0.04)",
        lift: "0 4px 12px rgba(0,0,0,0.04), 0 24px 56px rgba(0,0,0,0.10)",
        pop: "0 2px 8px rgba(0,0,0,0.06), 0 40px 80px rgba(0,0,0,0.22)",
      },
      transitionTimingFunction: { apple: "cubic-bezier(0.32, 0.72, 0, 1)" },
    },
  },
  plugins: [],
};
