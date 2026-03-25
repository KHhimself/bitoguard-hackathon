/**
 * Color constants for use in JS contexts (D3, Recharts, inline styles).
 * For React components, prefer Tailwind classes:
 *   text-primary-500, bg-danger-500, border-border, etc.
 */
export const C = {
  primary: "var(--color-primary-500)",
  primaryLight: "var(--color-primary-100)",
  accent: "var(--color-accent-500)",
  danger: "var(--color-danger-500)",
  warning: "var(--color-warning-500)",
  safe: "var(--color-safe-500)",
  bg: "var(--color-surface)",
  card: "var(--color-card)",
  text: "var(--color-text)",
  muted: "var(--color-text-muted)",
  border: "var(--color-border)",
  gradientA: "var(--color-primary-500)",
  gradientB: "var(--color-violet-500)",
};

/** Raw hex values for libraries that can't resolve CSS variables (D3, Recharts) */
export const HEX = {
  primary: "#0F62FE",
  primaryLight: "#D0E2FF",
  accent: "#00C9A7",
  danger: "#FF3B5C",
  warning: "#FFB020",
  safe: "#24D164",
  text: "#1A1A2E",
  muted: "#64748B",
  border: "#E8ECF2",
  violet: "#7B61FF",
};
