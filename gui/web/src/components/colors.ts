// Color estable por minero (mismo nombre → mismo color en toda la interfaz).
const PALETTE = ["#c6ff3d", "#ffb547", "#8b7bff", "#46e0d0", "#ff6b8b", "#5aa9ff", "#f7e26b", "#ff8f4f", "#b388ff", "#6bf29b"];

export function minerColor(name: string) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
