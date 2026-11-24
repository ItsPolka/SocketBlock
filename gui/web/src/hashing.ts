// Vista del PoW en el navegador: calcula SHA-256 reales sobre la plantilla
// del siguiente bloque (mismo JSON canónico que socketblock/models.py).
// El minero de verdad corre en Python; esto solo hace visible el trabajo.

export type Template = {
  network_id: string;
  height: number;
  previous_hash: string;
  timestamp: number;
  miner: string;
  miner_name: string;
  reward: number;
  difficulty: number;
};

const asciiEscape = (s: string) =>
  s.replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);

/** json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True) */
export function canonical(t: Template, nonce: number): string {
  const obj: Record<string, string | number> = { ...t, nonce };
  const keys = Object.keys(obj).sort();
  return asciiEscape(`{${keys.map((k) => `${JSON.stringify(k)}:${JSON.stringify(obj[k])}`).join(",")}}`);
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
