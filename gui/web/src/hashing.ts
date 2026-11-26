// Vista del PoW en el navegador: calcula SHA-256 reales sobre la plantilla
// del siguiente bloque (mismo JSON canónico que socketblock/models.py).
// El minero de verdad corre en Python; esto solo hace visible el trabajo.

import type { Template } from "./useNode";

export function canonical(template: Template, timestamp: number, nonce: number): string {
  const header = { ...template, timestamp, nonce };
  const keys = [...new Set([...Object.keys(header), ...Object.keys(template.offer)])].sort();
  return JSON.stringify(header, keys).replace(/[\u007f-\uffff]/g, (char) =>
    "\\u" + char.charCodeAt(0).toString(16).padStart(4, "0"));
}

const enc = new TextEncoder();
const hex = (buf: ArrayBuffer) =>
  Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");

export async function sha256(text: string) {
  return hex(await crypto.subtle.digest("SHA-256", enc.encode(text)));
}

export const leadingZeros = (h: string) => {
  let i = 0;
  while (i < h.length && h[i] === "0") i++;
  return i;
};
