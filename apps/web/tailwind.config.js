/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        background: {
          DEFAULT: "#e9ece3",
          secondary: "#f4f5ef",
          tertiary: "#dde3d6",
          elevated: "#ffffff",
        },
        surface: {
          DEFAULT: "#fbfbf6",
          hover: "#f3f4ec",
          active: "#e8ecdf",
        },
        border: {
          DEFAULT: "#d9ddd2",
          light: "#c7cebf",
          focus: "#a7b199",
        },
        text: {
          primary: "#1b1d1a",
          secondary: "#5f665b",
          tertiary: "#90988a",
          disabled: "#b8beb2",
        },
        brand: {
          amber: "#d6ff48",
          gold: "#f2f4df",
          mint: "#6f8a66",
          cyan: "#9cb4a2",
        },
        accent: {
          DEFAULT: "#5e6d51",
          hover: "#4c5a42",
          light: "#edf1e6",
        },
        status: {
          success: "#4c8d62",
          warning: "#b68f32",
          error: "#c56a5d",
          info: "#5d7b6c",
        },
      },
      fontFamily: {
        sans: ["Noto Sans SC", "IBM Plex Sans", "PingFang SC", "Microsoft YaHei", "system-ui", "sans-serif"],
        display: ["Playfair Display", "Noto Serif SC", "serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      backgroundImage: {
        "gradient-brand": "linear-gradient(135deg, #d6ff48 0%, #eef1d5 48%, #bfd0bb 100%)",
        "gradient-subtle":
          "radial-gradient(circle at top left, rgba(214,255,72,0.18) 0%, transparent 34%), radial-gradient(circle at bottom right, rgba(191,208,187,0.18) 0%, transparent 30%)",
      },
      boxShadow: {
        glow: "0 24px 60px rgba(41, 51, 33, 0.08), 0 0 0 1px rgba(255, 255, 255, 0.55)",
        "glow-lg": "0 28px 80px rgba(41, 51, 33, 0.12), 0 0 80px rgba(214, 255, 72, 0.08)",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        shimmer: "shimmer 2s linear infinite",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
    },
  },
  plugins: [],
};
