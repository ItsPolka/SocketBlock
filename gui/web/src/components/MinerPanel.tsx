import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { canonical, leadingZeros, sha256, type Template } from "../hashing";
import { cn } from "../lib/utils";
import type { Status } from "../useNode";
import SplitFlapText from "./kokonutui/split-flap-text";

type Line = { id: number; nonce: number; hash: string; zeros: number };

function HashText({ hash, zeros, target }: { hash: string; zeros: number; target: number }) {
  return (
    <span className="font-mono">
      <span className={cn(zeros >= target ? "text-signal" : zeros >= 3 ? "text-amber" : "text-zinc-300")}>
        {hash.slice(0, zeros)}
      </span>
      <span className="text-zinc-500">{hash.slice(zeros, 40)}</span>
      <span className="text-zinc-700">{hash.slice(40)}</span>
    </span>
  );
}

export default function MinerPanel({ status, lastBlockAt }: { status: Status | null; lastBlockAt: number | null }) {
  const [lines, setLines] = useState<Line[]>([]);
  const [rate, setRate] = useState(0);
  const [tried, setTried] = useState(0);
  const [best, setBest] = useState<Line | null>(null);
  const [now, setNow] = useState(Date.now());
  const counter = useRef(0);

  const mining = !!status?.mining;
  const height = (status?.height ?? 0) + 1;
  const target = status?.difficulty ?? 6;

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(id);
  }, []);

  // Nueva punta de cadena → plantilla nueva, contadores en cero.
  useEffect(() => {
    setBest(null);
    setTried(0);
    setLines([]);
  }, [status?.hash]);

  useEffect(() => {
    if (!status || !mining) return;
    const template: Template = {
      network_id: status.network_id, height: status.height + 1, previous_hash: status.hash,
      timestamp: Date.now(), miner: status.address, miner_name: status.name,
      reward: status.reward, difficulty: status.difficulty,
    };
    let alive = true;
    let nonce = Math.floor(Math.random() * 2 ** 40);
    let done = 0;
    let windowStart = performance.now();
    let raf = 0;

    const tick = async () => {
      const batch = 96;
      const nonces = Array.from({ length: batch }, () => nonce++);
      const hashes = await Promise.all(nonces.map((n) => sha256(canonical(template, n))));
      if (!alive) return;
      done += batch;
      const fresh = hashes.map((h, i) => ({ id: counter.current++, nonce: nonces[i], hash: h, zeros: leadingZeros(h) }));
      const top = fresh.reduce((a, b) => (b.zeros > a.zeros ? b : a));
      setBest((b) => (!b || top.zeros > b.zeros ? top : b));
      setTried((t) => t + batch);
      setLines((prev) => [...fresh.slice(-3), ...prev].slice(0, 11));
      const elapsed = performance.now() - windowStart;
      if (elapsed > 700) {
        setRate(Math.round((done / elapsed) * 1000));
        done = 0;
        windowStart = performance.now();
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
    };
  }, [status?.hash, mining, status?.address]); // eslint-disable-line react-hooks/exhaustive-deps

  const seconds = lastBlockAt ? Math.max(0, (now - lastBlockAt) / 1000) : 0;
  const expected = 16 ** target;

  return (
    <div className="panel overflow-hidden p-5 sm:p-6">
      {/* resplandor */}
      <div
        className={cn(
          "pointer-events-none absolute -top-32 -left-24 h-72 w-72 rounded-full blur-3xl transition-opacity duration-700",
          mining ? "bg-signal/20 opacity-100" : "opacity-0"
        )}
      />
      <div className="relative flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              {mining && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-signal opacity-75" />}
              <span className={cn("relative inline-flex h-2 w-2 rounded-full", mining ? "bg-signal" : "bg-zinc-600")} />
            </span>
            {mining ? "Prueba de trabajo en curso" : "Minería pausada"}
          </div>
          <div className="mt-3 flex items-baseline gap-3">
            <span className="text-zinc-500 text-lg">Bloque</span>
            <SplitFlapText
              className="text-4xl sm:text-5xl"
              length={String(height).length}
              text={String(height)}
              tileClassName="bg-zinc-900 text-zinc-50 ring-1 ring-white/5 shadow-[0_8px_20px_-8px_rgba(0,0,0,.8)]"
            />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-5 text-right">
          <Stat label="Tiempo" value={`${seconds.toFixed(1)}s`} />
          <Stat label="Hash/s vista" value={rate.toLocaleString("es-MX")} />
          <Stat label="Intentos" value={tried.toLocaleString("es-MX")} />
        </div>
      </div>

      {/* objetivo */}
      <div className="relative mt-6">
        <div className="mb-2 flex items-center justify-between">
          <span className="label">Objetivo: hash que empiece con {target} ceros</span>
          <span className="font-mono text-[11px] text-zinc-500">≈ {(expected / 1e6).toFixed(1)} M intentos por bloque</span>
        </div>
        <div className="flex gap-1.5">
          {Array.from({ length: 16 }).map((_, i) => {
            const isTarget = i < target;
            const hit = best ? i < best.zeros : false;
            return (
              <motion.div
                animate={{ opacity: isTarget ? 1 : 0.35 }}
                className={cn(
                  "relative flex h-9 flex-1 items-center justify-center overflow-hidden rounded-md border font-mono text-sm",
                  isTarget ? "border-white/10 bg-white/[.03]" : "border-white/5 bg-transparent",
                  hit && (best!.zeros >= target ? "border-signal/50 bg-signal/15 text-signal" : "border-amber/40 bg-amber/10 text-amber")
                )}
                key={i}
              >
                {best ? best.hash[i] : "·"}
              </motion.div>
            );
          })}
        </div>
        <div className="mt-2 font-mono text-[11px] text-zinc-500">
          Mejor intento de esta ronda: {best ? <span className="text-amber">{best.zeros} ceros</span> : "—"}
          {best && <span className="text-zinc-600"> · nonce {best.nonce}</span>}
        </div>
      </div>

      {/* flujo de hashes */}
      <div className="relative mt-5 h-[232px] overflow-hidden rounded-xl border border-white/5 bg-black/40 px-4 py-3">
        {mining && <div className="scanline pointer-events-none absolute inset-x-0 top-0 h-full bg-gradient-to-b from-transparent via-signal/[.04] to-transparent" />}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-16 bg-gradient-to-t from-black/90 to-transparent" />
        <AnimatePresence initial={false}>
          {lines.map((l) => (
            <motion.div
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              className="flex items-center gap-3 py-[3px] text-[12.5px]"
              exit={{ opacity: 0 }}
              initial={{ opacity: 0, y: -12, filter: "blur(4px)" }}
              key={l.id}
              layout
              transition={{ duration: 0.18 }}
            >
              <span className="w-[86px] shrink-0 truncate font-mono text-zinc-600">{l.nonce.toString(16).slice(-8)}</span>
              <span className="truncate"><HashText hash={l.hash} target={target} zeros={l.zeros} /></span>
            </motion.div>
          ))}
        </AnimatePresence>
        {!mining && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-zinc-500">
            Presiona <span className="mx-1 text-zinc-200">Minar</span> para ver los intentos en vivo
          </div>
        )}
      </div>
      <p className="mt-3 text-[11px] text-zinc-600">
        Hashes SHA-256 reales de tu siguiente bloque calculados en el navegador para visualizar el trabajo. El minero real corre en Python con {status?.workers ?? 1} proceso(s).
      </p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className="mt-1 font-mono text-lg text-zinc-100 tabular-nums">{value}</div>
    </div>
  );
}
