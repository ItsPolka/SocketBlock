import { motion } from "motion/react";
import { Trophy } from "lucide-react";
import type { Block } from "../useNode";
import { minerColor } from "./colors";

export default function Leaderboard({ blocks, me }: { blocks: Block[]; me?: string }) {
  const tally = new Map<string, { name: string; address: string; count: number; coins: number }>();
  for (const b of blocks) {
    const t = tally.get(b.miner) ?? { name: b.miner_name, address: b.miner, count: 0, coins: 0 };
    t.count++;
    t.coins += b.reward;
    tally.set(b.miner, t);
  }
  const rows = [...tally.values()].sort((a, b) => b.count - a.count);
  const max = rows[0]?.count ?? 1;
  const total = blocks.length || 1;

  return (
    <div className="panel p-5 sm:p-6">
      <div className="mb-4 flex items-center gap-2">
        <Trophy className="h-4 w-4 text-zinc-500" />
        <span className="label">Ranking de mineros</span>
      </div>
      <div className="space-y-2.5">
        {rows.map((r, i) => {
          const c = minerColor(r.name);
          return (
            <motion.div className="relative" key={r.address} layout transition={{ type: "spring", stiffness: 300, damping: 30 }}>
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2.5">
                  <span className="w-4 font-mono text-[11px] text-zinc-600">{i + 1}</span>
                  <span className="h-2 w-2 rounded-full" style={{ background: c, boxShadow: `0 0 10px ${c}` }} />
                  <span className={r.address === me ? "text-signal" : "text-zinc-200"}>
                    {r.name}
                    {r.address === me && " (tú)"}
                  </span>
                </div>
                <span className="font-mono text-[12px] text-zinc-400 tabular-nums">
                  {r.count} <span className="text-zinc-600">· {Math.round((r.count / total) * 100)}%</span>
                </span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[.04]">
                <motion.div
                  animate={{ width: `${(r.count / max) * 100}%` }}
                  className="h-full rounded-full"
                  initial={{ width: 0 }}
                  style={{ background: `linear-gradient(90deg, ${c}55, ${c})` }}
                  transition={{ type: "spring", stiffness: 120, damping: 20 }}
                />
              </div>
            </motion.div>
          );
        })}
        {rows.length === 0 && <p className="text-sm text-zinc-500">Aún no hay bloques.</p>}
      </div>
    </div>
  );
}
