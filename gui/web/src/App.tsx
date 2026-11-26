import { animate, motion, useMotionValue, useTransform } from "motion/react";
import { Coins, Gauge, Hexagon, Timer, Users, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ChainStrip from "./components/ChainStrip";
import Feed from "./components/Feed";
import BackgroundPaths from "./components/kokonutui/background-paths";
import Leaderboard from "./components/Leaderboard";
import MinerPanel from "./components/MinerPanel";
import NetworkOrbit from "./components/NetworkOrbit";
import OffersPanel from "./components/OffersPanel";
import WinnerBurst from "./components/WinnerBurst";
import { cn } from "./lib/utils";
import { useNode } from "./useNode";

function CountUp({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const mv = useMotionValue(value);
  const text = useTransform(mv, (v) => v.toLocaleString("es-MX", { maximumFractionDigits: decimals, minimumFractionDigits: decimals }));
  useEffect(() => {
    const c = animate(mv, value, { duration: 0.9, ease: [0.16, 1, 0.3, 1] });
    return c.stop;
  }, [value, mv]);
  return <motion.span>{text}</motion.span>;
}

function Metric({ icon: Icon, label, value, suffix, accent, decimals }: { icon: typeof Coins; label: string; value: number; suffix?: string; accent?: string; decimals?: number }) {
  return (
    <div className="panel group overflow-hidden px-5 py-4">
      <div className="flex items-center justify-between">
        <span className="label">{label}</span>
        <Icon className="h-4 w-4 text-zinc-600 transition-colors group-hover:text-zinc-300" />
      </div>
      <div className={cn("mt-2 font-mono text-2xl tabular-nums sm:text-[28px]", accent ?? "text-zinc-50")}>
        <CountUp decimals={decimals} value={value} />
        {suffix && <span className="ml-1 text-sm text-zinc-500">{suffix}</span>}
      </div>
    </div>
  );
}

export default function App() {
  const { status, users, blocks, offers, feed, winner, online, nodeAlive, send } = useNode();
  const [fresh, setFresh] = useState<number | null>(null);

  const list = useMemo(() => [...blocks].sort((a, b) => b.height - a.height), [blocks]);

  useEffect(() => {
    if (!winner) return;
    setFresh(winner.height);
    const id = window.setTimeout(() => setFresh(null), 2500);
    return () => window.clearTimeout(id);
  }, [winner]);

  const avg = useMemo(() => {
    const rounds = list.filter((b) => b.height > 0).slice(0, 20);
    if (!rounds.length) return 0;
    return rounds.reduce((total, block) => total + block.timestamp - block.started_at, 0) / rounds.length / 1000;
  }, [list]);
  const mining = !!status?.mining;

  return (
    <div className="min-h-full">
      <WinnerBurst winner={winner} />

      {/* Encabezado con el fondo de líneas de kokonutui */}
      <BackgroundPaths className="min-h-0 bg-transparent text-signal dark:bg-transparent" count={36} speed={mining ? 1.4 : 0.4} spread={0.5}>
        <header className="relative z-10 mx-auto flex w-full max-w-[1400px] flex-col gap-6 px-4 pt-8 pb-10 sm:px-8 sm:pt-10 sm:pb-14">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-signal text-black">
                <Hexagon className="h-5 w-5" strokeWidth={2.5} />
              </div>
              <div>
                <div className="font-semibold text-lg tracking-tight text-zinc-50">SocketBlock Live</div>
                <div className="font-mono text-[11px] text-zinc-500">
                  {status?.network ?? "—"} · PoW {status?.fixed_difficulty ? status.fixed_difficulty + " ceros" : "meta 120 s"} · {status?.reward ?? "–"} LC por bloque
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[11px]",
                  online && nodeAlive ? "border-signal/30 text-signal" : "border-red-400/30 text-red-300"
                )}
              >
                <span className={cn("h-1.5 w-1.5 rounded-full", online && nodeAlive ? "bg-signal" : "bg-red-400")} />
                {!nodeAlive ? "nodo detenido" : online ? "conectado" : "reconectando…"}
              </span>
            </div>
          </div>

          <div className="max-w-3xl">
            <motion.h1
              animate={{ opacity: 1, y: 0 }}
              className="font-semibold text-4xl tracking-[-0.03em] text-zinc-50 sm:text-6xl"
              initial={{ opacity: 0, y: 12 }}
            >
              Hola, {status?.name ?? "minero"}.
              <span className="block text-zinc-500">La cadena va en el bloque <span className="text-signal">#{status?.height ?? 0}</span>.</span>
            </motion.h1>
          </div>
        </header>
      </BackgroundPaths>

      <main className="relative z-10 mx-auto -mt-4 flex w-full max-w-[1400px] flex-col gap-4 px-4 pb-16 sm:px-8">
        <section className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <Metric accent="text-signal" icon={Coins} label="Tu saldo" suffix="LC" value={status?.balance ?? 0} />
          <Metric icon={Zap} label="Confirmado (6)" suffix="LC" value={status?.confirmed_balance ?? 0} />
          <Metric icon={Users} label="Usuarios" value={status?.users ?? users.length} />
          <Metric decimals={1} icon={Timer} label="Minería promedio" suffix="s" value={avg} />
          <Metric accent="text-amber" icon={Gauge} label="Altura" value={status?.height ?? 0} />
        </section>

        <OffersPanel offers={offers} ready={online && nodeAlive && !!status} send={send} status={status} />

        <section className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
          <MinerPanel status={status} />
          <NetworkOrbit headHash={status?.hash} users={users} winner={winner} />
        </section>

        <ChainStrip blocks={list} freshHeight={fresh} me={status?.address} />

        <section className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
          <Leaderboard blocks={list.filter((block) => block.height > 0)} me={status?.address} />
          <Feed items={feed} onChat={send} users={users} />
        </section>
      </main>
    </div>
  );
}
