import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { canonical, leadingZeros, sha256 } from "../hashing";
import { cn } from "../lib/utils";
import type { Status } from "../useNode";
import SplitFlapText from "./kokonutui/split-flap-text";

type Line = { id: number; nonce: number; hash: string; zeros: number };

function HashText({ hash, zeros, target }: { hash: string; zeros: number; target: string }) {
  return (
    <span className="font-mono">
      <span className={cn(hash <= target ? "text-signal" : zeros >= 3 ? "text-amber" : "text-zinc-300")}>
        {hash.slice(0, zeros)}
      </span>
      <span className="text-zinc-500">{hash.slice(zeros, 40)}</span>
      <span className="text-zinc-700">{hash.slice(40)}</span>
    </span>
  );
}

export default function MinerPanel({ status }: { status: Status | null }) {
  const [lines, setLines] = useState<Line[]>([]);
  const [rate, setRate] = useState(0);
  const [tried, setTried] = useState(0);
  const [best, setBest] = useState<Line | null>(null);
  const [now, setNow] = useState(Date.now);
  const counter = useRef(0);

  const mining = !!status?.mining;
  const height = (status?.height ?? 0) + 1;
  const active = status?.template;
  const target = status?.target;
  const expected = status?.difficulty;
  const templateKey = active ? JSON.stringify(active) : null;

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    setBest(null);
    setTried(0);
    setLines([]);
    setRate(0);
  }, [templateKey]);

  useEffect(() => {
    if (!templateKey) return;
    const template = JSON.parse(templateKey) as NonNullable<Status["template"]>;
    let alive = true;
    let nonce = Math.floor(Math.random() * 2 ** 40);
    let done = 0;
    let windowStart = performance.now();
    let timer = 0;

    const tick = async () => {
      const batch = 96;
      const nonces = Array.from({ length: batch }, () => nonce++);
      const timestamp = Math.max(Date.now(), template.started_at);
      const hashes = await Promise.all(nonces.map((n) => sha256(canonical(template, timestamp, n))));
      if (!alive) return;
      done += batch;
      const fresh = hashes.map((h, i) => ({ id: counter.current++, nonce: nonces[i], hash: h, zeros: leadingZeros(h) }));
      const top = fresh.reduce((a, b) => (b.hash < a.hash ? b : a));
      setBest((b) => (!b || top.hash < b.hash ? top : b));
      setTried((t) => t + batch);
      setLines((prev) => [...fresh.slice(-3), ...prev].slice(0, 11));
      const elapsed = performance.now() - windowStart;
      if (elapsed > 700) {
        setRate(Math.round((done / elapsed) * 1000));
        done = 0;
        windowStart = performance.now();
      }
      timer = window.setTimeout(tick, 200);
    };
    timer = window.setTimeout(tick, 200);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [templateKey]);

  const seconds = active ? Math.max(0, (now - active.started_at) / 1000) : 0;

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
            {mining ? "Prueba de trabajo en curso" : "Sin minería activa"}
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
          {active && <p className="mt-2 text-sm text-zinc-400">{active.offer.text}</p>}
        </div>
        <div className="grid grid-cols-3 gap-5 text-right">
          <Stat label="Tiempo" value={`${seconds.toFixed(1)}s`} />
          <Stat label="Muestras/s" value={rate.toLocaleString("es-MX")} />
          <Stat label="Muestras" value={tried.toLocaleString("es-MX")} />
        </div>
      </div>

      {/* objetivo */}
      <div className="relative mt-6">
        <div className="mb-2 flex items-center justify-between">
          <span className="label">El hash debe ser menor o igual al objetivo</span>
          {expected && <span className="font-mono text-[11px] text-zinc-500">≈ {expected.toLocaleString("es-MX")} intentos</span>}
        </div>
        <div className="break-all rounded-md border border-white/10 bg-white/[.03] px-3 py-2 font-mono text-sm text-zinc-300">
          {target ?? "—"}
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
              <span className="truncate"><HashText hash={l.hash} target={target ?? ""} zeros={l.zeros} /></span>
            </motion.div>
          ))}
        </AnimatePresence>
        {!mining && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-zinc-500">
            Selecciona una oferta para iniciar la minería
          </div>
        )}
      </div>
      <p className="mt-3 text-[11px] text-zinc-600">
        Muestras SHA-256 calculadas en el navegador con la oferta activa. Python realiza la minería con {status?.workers ?? 1} proceso(s).
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
