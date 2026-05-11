/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Deep liturgical reds + warm neutrals. Avoid pure black/white;
        // bulletins feel paper-like, so we lean into off-whites.
        parish: {
          50: "#fafaf9",
          100: "#f5f5f4",
          200: "#e7e5e4",
          600: "#9a3412",
          700: "#7c2d12",
          800: "#581c0c",
        },
      },
      fontFamily: {
        // System fonts; no web font load on first paint.
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        serif: ["ui-serif", "Georgia", "Cambria", "serif"],
      },
    },
  },
  plugins: [],
};
