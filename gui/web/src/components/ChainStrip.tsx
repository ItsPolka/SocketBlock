import { AnimatePresence, motion } from "motion/react";
import { Box, Link2 } from "lucide-react";
import { useState } from "react";
import { leadingZeros } from "../hashing";
import { cn } from "../lib/utils";
import type { Block } from "../useNode";
import { minerColor } from "./colors";

const time = (ms: number) => new Date(ms).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export default function ChainStrip({ blocks, me, freshHeight }: { blocks: Block[]; me?: string; freshHeight: number | null }) {
  const [open, setOpen] = useState<Block | null>(null);
  const visible = blocks.slice(0, 24);

  return (
    <div className="panel p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Link2 className="h-4 w-4 text-zinc-500" />
          <span className="label">Cadena de bloques · en vivo</span>
        </div>
        <span className="font-mono text-[11px] text-zinc-500">{blocks.length} bloques cargados</span>
      </div>

      <div className="scroll-x -mx-2 flex items-stretch overflow-x-auto px-2 pb-2">
        <AnimatePresence initial={false} mode="popLayout">
          {visible.map((b, i) => {
            const c = minerColor(b.miner_name);
            const zeros = leadingZeros(b.hash);
            const fresh = b.height === freshHeight;
            const mine = b.miner === me;
            return (
              <motion.div
                animate={{ opacity: 1, x: 0, scale: 1 }}
                className="flex shrink-0 items-center"
                exit={{ opacity: 0, scale: 0.9 }}
                initial={{ opacity: 0, x: -60, scale: 0.85 }}
                key={b.hash}
                layout
                transition={{ type: "spring", stiffness: 260, damping: 26 }}
              >
                <button
                  className={cn(
                    "group relative w-[190px] overflow-hidden rounded-2xl border bg-zinc-950/70 p-4 text-left transition-colors hover:border-white/20",
                    mine ? "border-signal/30" : "border-white/[.07]"
                  )}
                  onClick={() => setOpen(b)}
                  type="button"
                >
                  {fresh && (
                    <motion.span
                      animate={{ opacity: [0.9, 0] }}
                      className="pointer-events-none absolute inset-0 rounded-2xl"
                      initial={{ opacity: 0.9 }}
                      style={{ boxShadow: `inset 0 0 0 1px ${c}, 0 0 40px ${c}` }}
                      transition={{ duration: 2.2, ease: "easeOut" }}
                    />
                  )}
                  <div className="absolute inset-x-0 top-0 h-px" style={{ background: `linear-gradient(90deg, transparent, ${c}, transparent)` }} />
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xl text-zinc-50 tabular-nums">#{b.height}</span>
                    <Box className="h-4 w-4 text-zinc-600 transition-colors group-hover:text-zinc-300" />
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full font-semibold text-[11px] text-black" style={{ background: c }}>
                      {b.miner_name.slice(0, 1).toUpperCase()}
                    </span>
                    <span className="truncate text-sm text-zinc-200">{b.miner_name}</span>
                    {mine && <span className="rounded-full bg-signal/15 px-1.5 py-0.5 font-mono text-[9px] text-signal">TÚ</span>}
                  </div>
                  <div className="mt-3 truncate font-mono text-[11px]">
                    <span className="text-signal">{b.hash.slice(0, zeros)}</span>
                    <span className="text-zinc-500">{b.hash.slice(zeros, 22)}…</span>
                  </div>
                  <div className="mt-2 flex items-center justify-between font-mono text-[10.5px] text-zinc-600">
                    <span>{b.nonce >= 0 ? time(b.timestamp) : "recibiendo…"}</span>
                    <span className="text-amber/80">+{b.reward}</span>
                  </div>
                </button>
                {i < visible.length - 1 && <Connector color={c} />}
              </motion.div>
            );
          })}
        </AnimatePresence>
        {visible.length === 0 && <div className="py-10 text-sm text-zinc-500">Esperando bloques…</div>}
      </div>

      <AnimatePresence>
        {open && (
          <motion.div
            animate={{ opacity: 1 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
            exit={{ opacity: 0 }}
            initial={{ opacity: 0 }}
            onClick={() => setOpen(null)}
          >
            <motion.div
              animate={{ scale: 1, y: 0 }}
              className="panel w-full max-w-xl bg-panel p-6"
              exit={{ scale: 0.95, y: 10 }}
              initial={{ scale: 0.95, y: 10 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-baseline justify-between">
                <h3 className="font-semibold text-2xl">Bloque #{open.height}</h3>
                <span className="font-mono text-xs text-zinc-500">{open.nonce >= 0 ? new Date(open.timestamp).toLocaleString("es-MX") : ""}</span>
              </div>
              <dl className="mt-5 space-y-3 font-mono text-[12px]">
                {(
                  [
                    ["Minero", open.miner_name],
                    ["Recompensa", `${open.reward} leonelcoin`],
                    ["Dificultad", `${open.difficulty} ceros`],
                    ["Nonce", open.nonce >= 0 ? String(open.nonce) : "—"],
                    ["Hash", open.hash],
                    ["Padre", open.previous_hash],
                    ["Dirección", open.miner],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k}>
                    <dt className="label">{k}</dt>
                    <dd className="mt-1 break-all text-zinc-200">{v}</dd>
                  </div>
                ))}
              </dl>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Connector({ color }: { color: string }) {
  return (
    <div className="relative mx-1 h-px w-8 bg-white/10">
      <motion.span
        animate={{ x: [32, -6] }}
        className="absolute -top-[2px] h-[5px] w-[5px] rounded-full"
        style={{ background: color, boxShadow: `0 0 8px ${color}` }}
        transition={{ duration: 1.6, repeat: Number.POSITIVE_INFINITY, ease: "linear" }}
      />
    </div>
  );
}
