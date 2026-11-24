import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, Blocks, GitFork, MessageCircle, Pickaxe, RefreshCw, Send, UserMinus, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { cn } from "../lib/utils";
import type { FeedItem } from "../useNode";

const ICON = {
  winner: Blocks, peer_in: UserPlus, peer_out: UserMinus, chat: MessageCircle, mining: Pickaxe,
  sync: RefreshCw, fork: GitFork, error: AlertTriangle, classroom: Users,
} as const;
const TONE: Record<FeedItem["kind"], string> = {
  winner: "text-amber bg-amber/10", peer_in: "text-signal bg-signal/10", peer_out: "text-zinc-400 bg-white/5",
  chat: "text-violet bg-violet/10", mining: "text-signal bg-signal/10", sync: "text-sky-300 bg-sky-400/10",
  fork: "text-pink-300 bg-pink-400/10", error: "text-red-300 bg-red-400/10", classroom: "text-amber bg-amber/10",
};

export default function Feed({ items, onChat }: { items: FeedItem[]; onChat: (t: string) => void }) {
  const [text, setText] = useState("");
  return (
    <div className="panel flex h-full min-h-[420px] flex-col p-5 sm:p-6">
      <span className="label mb-4">Actividad y chat</span>
      <div className="scroll-y -mr-2 flex-1 space-y-2 overflow-y-auto pr-2" style={{ maxHeight: 420 }}>
        <AnimatePresence initial={false}>
          {items.map((it) => {
            const Icon = ICON[it.kind];
            return (
              <motion.div
                animate={{ opacity: 1, height: "auto", y: 0 }}
                className="overflow-hidden"
                initial={{ opacity: 0, height: 0, y: -8 }}
                key={it.id}
                transition={{ type: "spring", stiffness: 400, damping: 34 }}
              >
                <div className={cn("flex items-start gap-3 rounded-xl border border-white/[.05] bg-white/[.02] px-3 py-2.5", it.local && it.kind === "winner" && "border-signal/30")}>
                  <span className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", TONE[it.kind])}>
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-[13px] text-zinc-100">{it.title}</span>
                      <span className="shrink-0 font-mono text-[10px] text-zinc-600">
                        {new Date(it.ts).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                      </span>
                    </div>
                    {it.detail && <p className="mt-0.5 break-words text-[12px] text-zinc-500">{it.detail}</p>}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
      <form
        className="mt-4 flex items-center gap-2 rounded-xl border border-white/[.07] bg-black/30 p-1.5 pl-3 focus-within:border-white/20"
        onSubmit={(e) => {
          e.preventDefault();
          const t = text.trim();
          if (!t) return;
          onChat(t.startsWith("/") ? ` ${t}` : t);
          setText("");
        }}
      >
        <input
          className="flex-1 bg-transparent text-sm text-zinc-100 outline-none placeholder:text-zinc-600"
          maxLength={280}
          onChange={(e) => setText(e.target.value)}
          placeholder="Escribe al salón…"
          value={text}
        />
        <button className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10 text-zinc-200 transition hover:bg-white/20" type="submit">
          <Send className="h-3.5 w-3.5" />
        </button>
      </form>
    </div>
  );
}
