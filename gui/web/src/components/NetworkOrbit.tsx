import { AnimatePresence, motion } from "motion/react";
import { Radio } from "lucide-react";
import type { User, WinnerEvent } from "../useNode";
import { minerColor } from "./colors";

const W = 560;
const H = 440;
const CX = W / 2;
const CY = H / 2;
const R = 190;

export default function NetworkOrbit({ users, winner, headHash }: { users: User[]; winner: WinnerEvent | null; headHash?: string }) {
  const me = users.find((u) => u.local);
  const peers = users.filter((u) => !u.local);
  const pos = new Map<string, { x: number; y: number }>();
  if (me) pos.set(me.address, { x: CX, y: CY });
  peers.forEach((p, i) => {
    const a = (i / Math.max(peers.length, 1)) * Math.PI * 2 - Math.PI / 2;
    pos.set(p.address, { x: CX + Math.cos(a) * R, y: CY + Math.sin(a) * R * 0.78 });
  });
  const source = winner ? pos.get(winner.address) : undefined;
  const myHeight = me?.height ?? 0;
  const inSync = peers.filter((p) => p.hash === headHash || Math.abs(p.height - myHeight) <= 2).length;

  return (
    <div className="panel flex flex-col p-5 sm:p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Radio className="h-4 w-4 text-zinc-500" />
          <span className="label">Red del salón · P2P</span>
        </div>
        <span className="font-mono text-[11px] text-zinc-500">
          {inSync}/{peers.length} sincronizados
        </span>
      </div>
      <svg className="mt-2 w-full" viewBox={`0 0 ${W} ${H}`}>
        <defs>
          <radialGradient id="core">
            <stop offset="0%" stopColor="#c6ff3d" stopOpacity=".35" />
            <stop offset="100%" stopColor="#c6ff3d" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx={CX} cy={CY} fill="none" rx={R} ry={R * 0.78} stroke="rgba(255,255,255,.05)" strokeDasharray="2 6" />
        <circle cx={CX} cy={CY} fill="url(#core)" r={70} />
        {/* conexiones */}
        {peers.map((p) => {
          const q = pos.get(p.address)!;
          return <line key={`l-${p.address}`} stroke="rgba(255,255,255,.07)" x1={CX} x2={q.x} y1={CY} y2={q.y} />;
        })}
        {/* difusión del bloque ganador */}
        <AnimatePresence>
          {winner && source &&
            [...pos.entries()]
              .filter(([addr]) => addr !== winner.address)
              .map(([addr, q]) => (
                <motion.circle
                  animate={{ cx: q.x, cy: q.y, opacity: [1, 1, 0] }}
                  fill={minerColor(winner.name)}
                  initial={{ cx: source.x, cy: source.y, opacity: 1 }}
                  key={`${winner.hash}-${addr}`}
                  r={3.5}
                  style={{ filter: `drop-shadow(0 0 6px ${minerColor(winner.name)})` }}
                  transition={{ duration: 0.9, ease: "easeOut" }}
                />
              ))}
        </AnimatePresence>
        {winner && source && (
          <motion.circle
            animate={{ r: 60, opacity: 0 }}
            cx={source.x}
            cy={source.y}
            fill="none"
            initial={{ r: 12, opacity: 0.9 }}
            key={`ring-${winner.hash}`}
            stroke={minerColor(winner.name)}
            strokeWidth={2}
            transition={{ duration: 1.4, ease: "easeOut" }}
          />
        )}
        {/* nodos */}
        {users.map((u) => {
          const q = pos.get(u.address);
          if (!q) return null;
          const c = minerColor(u.name);
          const synced = u.local || u.hash === headHash || Math.abs(u.height - (me?.height ?? 0)) <= 2;
          return (
            <motion.g animate={{ opacity: 1, scale: 1 }} initial={{ opacity: 0, scale: 0.4 }} key={u.address} style={{ originX: `${q.x}px`, originY: `${q.y}px` }}>
              <circle cx={q.x} cy={q.y} fill="#0b0d12" r={u.local ? 22 : 16} stroke={synced ? c : "rgba(255,255,255,.15)"} strokeWidth={u.local ? 2 : 1.5} />
              <text dominantBaseline="central" fill={c} fontFamily="Geist" fontSize={u.local ? 14 : 12} fontWeight={600} textAnchor="middle" x={q.x} y={q.y}>
                {u.name.slice(0, 1).toUpperCase()}
              </text>
              <text fill="#a1a6b3" fontFamily="Geist" fontSize={11} textAnchor="middle" x={q.x} y={q.y + (u.local ? 38 : 30)}>
                {u.local ? `${u.name} (tú)` : u.name.length > 11 ? `${u.name.slice(0, 10)}…` : u.name}
              </text>
              <text fill="#5b6070" fontFamily="Geist Mono" fontSize={9} textAnchor="middle" x={q.x} y={q.y + (u.local ? 50 : 42)}>
                #{u.height}
              </text>
            </motion.g>
          );
        })}
      </svg>
    </div>
  );
}
