import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import type { WinnerEvent } from "../useNode";
import { minerColor } from "./colors";

/** Aviso flotante cada vez que alguien encuentra un bloque; con confeti si fuiste tú. */
export default function WinnerBurst({ winner }: { winner: WinnerEvent | null }) {
  const [shown, setShown] = useState<WinnerEvent | null>(null);

  useEffect(() => {
    if (!winner || Date.now() - winner.ts > 3000) return;
    setShown(winner);
    const id = window.setTimeout(() => setShown(null), winner.local ? 4200 : 2400);
    return () => window.clearTimeout(id);
  }, [winner]);

  const c = shown ? minerColor(shown.name) : "#fff";

  return (
    <AnimatePresence>
      {shown && (
        <motion.div
          animate={{ opacity: 1, y: 0, scale: 1 }}
          className="pointer-events-none fixed top-5 left-1/2 z-40 -translate-x-1/2"
          exit={{ opacity: 0, y: -16, scale: 0.96 }}
          initial={{ opacity: 0, y: -30, scale: 0.9 }}
          key={shown.hash}
          transition={{ type: "spring", stiffness: 380, damping: 26 }}
        >
          <div
            className="relative flex items-center gap-4 overflow-hidden rounded-2xl border bg-zinc-950/90 px-5 py-3 backdrop-blur-xl"
            style={{ borderColor: `${c}55`, boxShadow: `0 20px 60px -20px ${c}88` }}
          >
            <motion.div
              animate={{ x: ["-100%", "220%"] }}
              className="absolute inset-y-0 w-1/3 -skew-x-12"
              style={{ background: `linear-gradient(90deg, transparent, ${c}22, transparent)` }}
              transition={{ duration: 1.1, ease: "easeInOut" }}
            />
            <span className="flex h-10 w-10 items-center justify-center rounded-xl font-bold text-black" style={{ background: c }}>
              {shown.name.slice(0, 1).toUpperCase()}
            </span>
            <div>
              <div className="label" style={{ color: c }}>
                {shown.local ? "¡Encontraste un bloque!" : "Bloque encontrado"}
              </div>
              <div className="font-semibold text-zinc-50">
                {shown.name} · #{shown.height} <span className="ml-1 font-mono text-amber text-sm">+{shown.reward} LC</span>
              </div>
            </div>
          </div>
        </motion.div>
      )}
      {shown?.local && (
        <div className="pointer-events-none fixed inset-0 z-30 overflow-hidden" key={`c-${shown.hash}`}>
          {Array.from({ length: 70 }).map((_, i) => {
            const x = Math.random() * 100;
            const hue = ["#c6ff3d", "#ffb547", "#8b7bff", "#46e0d0"][i % 4];
            return (
              <motion.span
                animate={{ y: "110vh", rotate: Math.random() * 720 - 360, opacity: [1, 1, 0] }}
                className="absolute top-0 h-2.5 w-1.5 rounded-sm"
                initial={{ y: -20, x: 0 }}
                key={i}
                style={{ left: `${x}%`, background: hue }}
                transition={{ duration: 2 + Math.random() * 1.8, delay: Math.random() * 0.4, ease: [0.2, 0.6, 0.4, 1] }}
              />
            );
          })}
        </div>
      )}
    </AnimatePresence>
  );
}
