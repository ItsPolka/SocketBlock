import { useCallback, useEffect, useRef, useState } from "react";

export type Block = {
  network_id: string;
  height: number;
  previous_hash: string;
  timestamp: number;
  miner: string;
  miner_name: string;
  reward: number;
  difficulty: number;
  nonce: number;
  hash: string;
};

export type Status = {
  name: string;
  address: string;
  network: string;
  network_id: string;
  difficulty: number;
  reward: number;
  peers: number;
  users: number;
  height: number;
  hash: string;
  balance: number;
  confirmed_balance: number;
  mining: boolean;
  workers: number;
};

export type User = {
  name: string;
  address: string;
  endpoint: string;
  height: number;
  hash: string;
  local: boolean;
};

export type FeedItem = {
  id: string;
  kind: "winner" | "peer_in" | "peer_out" | "chat" | "mining" | "sync" | "fork" | "error" | "classroom";
  title: string;
  detail?: string;
  ts: number;
  local?: boolean;
};

export type WinnerEvent = {
  height: number;
  hash: string;
  name: string;
  address: string;
  reward: number;
  local: boolean;
  ts: number;
};

// biome-ignore lint: payload libre del nodo
type Raw = Record<string, any>;

let seq = 0;
const nid = () => `${Date.now()}-${seq++}`;

function toFeed(e: Raw): FeedItem | null {
  const ts = (e.ts ?? Date.now() / 1000) * 1000;
  switch (e.event) {
    case "winner":
      return { id: nid(), kind: "winner", ts, local: e.local, title: `${e.name} minó el bloque #${e.height}`, detail: `+${e.reward} leonelcoin${e.reorganization ? " · cadena reorganizada" : ""}` };
    case "peer_connected":
      return { id: nid(), kind: "peer_in", ts, title: `${e.name} se conectó`, detail: e.endpoint };
    case "peer_disconnected":
      return { id: nid(), kind: "peer_out", ts, title: `${e.name} se desconectó` };
    case "chat":
      return { id: nid(), kind: "chat", ts, local: e.local, title: e.name, detail: e.text };
    case "mining_started":
      return { id: nid(), kind: "mining", ts, title: `Minando bloque #${e.height}`, detail: `${e.workers} proceso(s)` };
    case "mining_paused":
      return { id: nid(), kind: "mining", ts, title: "Minería pausada" };
    case "classroom_started":
      return { id: nid(), kind: "classroom", ts, title: `${e.name} inició la minería del salón` };
    case "sync":
      return { id: nid(), kind: "sync", ts, title: `Sincronizados ${e.received} bloques`, detail: `desde ${e.name}` };
    case "fork":
      return { id: nid(), kind: "fork", ts, title: `Bloque alterno #${e.height}`, detail: `de ${e.name}` };
    case "error":
    case "peer_error":
      return { id: nid(), kind: "error", ts, title: "Aviso", detail: e.message };
    default:
      return null;
  }
}

export function useNode() {
  const [status, setStatus] = useState<Status | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [blocks, setBlocks] = useState<Map<number, Block>>(new Map());
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [winner, setWinner] = useState<WinnerEvent | null>(null);
  const [online, setOnline] = useState(false);
  const [nodeAlive, setNodeAlive] = useState(true);
  const statusRef = useRef<Status | null>(null);

  const mergeBlocks = useCallback((list: Block[]) => {
    setBlocks((prev) => {
      const next = new Map(prev);
      for (const b of list) next.set(b.height, b);
      return next;
    });
  }, []);

  useEffect(() => {
    let source: EventSource | null = null;
    let retry: number | undefined;

    const handle = (e: Raw) => {
      switch (e.event) {
        case "snapshot": {
          if (e.status) {
            statusRef.current = e.status;
            setStatus(e.status);
          }
          setUsers(e.users ?? []);
          setBlocks(new Map((e.blocks as Block[]).map((b) => [b.height, b])));
          setFeed((e.log as Raw[]).map(toFeed).filter(Boolean).reverse().slice(0, 60) as FeedItem[]);
          return;
        }
        case "ready":
        case "status": {
          const { event: _e, ts: _t, ...s } = e;
          statusRef.current = s as Status;
          setStatus(s as Status);
          return;
        }
        case "users":
          setUsers(e.users);
          return;
        case "chain":
          mergeBlocks(e.blocks);
          return;
        case "node_exit":
          setNodeAlive(false);
          return;
        case "winner": {
          setWinner({ height: e.height, hash: e.hash, name: e.name, address: e.address, reward: e.reward, local: e.local, ts: Date.now() });
          // Mientras llegan los datos completos, mostramos el bloque con lo que ya sabemos.
          setBlocks((prev) => {
            const next = new Map(prev);
            if (e.reorganization) {
              for (const h of [...next.keys()]) if (h >= e.height) next.delete(h);
            }
            const old = next.get(e.height);
            if (!old || old.hash !== e.hash) {
              const s = statusRef.current;
              next.set(e.height, {
                network_id: s?.network_id ?? "", height: e.height, previous_hash: e.previous_hash,
                timestamp: Date.now(), miner: e.address, miner_name: e.name, reward: e.reward,
                difficulty: s?.difficulty ?? 6, nonce: -1, hash: e.hash,
              });
            }
            return next;
          });
          setStatus((s) => (s ? { ...s, height: e.height, hash: e.hash, balance: e.balance, mining: e.mining } : s));
          break;
        }
        case "mining_started":
          setStatus((s) => (s ? { ...s, mining: true } : s));
          break;
        case "mining_paused":
          setStatus((s) => (s ? { ...s, mining: false } : s));
          break;
      }
      const item = toFeed(e);
      if (item) setFeed((f) => [item, ...f].slice(0, 60));
    };

    const connect = () => {
      source = new EventSource("/api/events");
      source.onopen = () => setOnline(true);
      source.onmessage = (m) => {
        try {
          handle(JSON.parse(m.data));
        } catch {
          /* línea ilegible */
        }
      };
      source.onerror = () => {
        setOnline(false);
        source?.close();
        retry = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      source?.close();
      window.clearTimeout(retry);
    };
  }, [mergeBlocks]);

  const send = useCallback(async (cmd: string) => {
    await fetch("/api/cmd", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cmd }) });
  }, []);

  return { status, users, blocks, feed, winner, online, nodeAlive, send };
}
