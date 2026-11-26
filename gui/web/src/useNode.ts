import { useCallback, useEffect, useState } from "react";

export type Proposal = { author: string; name: string; text: string; timestamp: number };
export type Offer = Proposal & { id: string };

export type Template = {
  network_id: string;
  height: number;
  previous_hash: string;
  timestamp: number;
  started_at: number;
  miner: string;
  miner_name: string;
  reward: number;
  difficulty: number;
  offer: Proposal;
};

export type Block = Omit<Template, "offer"> & {
  offer: Proposal | null;
  nonce: string;
  hash: string;
};

export type Status = {
  name: string;
  address: string;
  network: string;
  network_id: string;
  difficulty: number;
  target: string;
  fixed_difficulty: number | null;
  round_target_seconds: number;
  reward: number;
  peers: number;
  users: number;
  height: number;
  hash: string;
  balance: number;
  confirmed_balance: number;
  mining: boolean;
  template: Template | null;
  classroom: boolean;
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
      return { id: nid(), kind: "chat", ts, local: e.local, title: e.recipient ? (e.local ? `Directo a ${e.recipient_name}` : `Directo de ${e.name}`) : e.name, detail: e.text };
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
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [winner, setWinner] = useState<WinnerEvent | null>(null);
  const [online, setOnline] = useState(false);
  const [nodeAlive, setNodeAlive] = useState(true);

  useEffect(() => {
    let source: EventSource | null = null;
    let retry: number | undefined;

    const handle = (e: Raw) => {
      switch (e.event) {
        case "snapshot": {
          if (e.status) setStatus(e.status);
          setUsers(e.users ?? []);
          setBlocks(e.blocks ?? []);
          setOffers(e.offers ?? []);
          setFeed((e.log as Raw[]).map(toFeed).filter(Boolean).reverse().slice(0, 60) as FeedItem[]);
          return;
        }
        case "ready":
        case "status": {
          const { event: _e, ts: _t, ...s } = e;
          setStatus(s as Status);
          return;
        }
        case "users":
          setUsers(e.users);
          return;
        case "chain":
          setBlocks(e.blocks);
          return;
        case "offers":
          setOffers(e.offers);
          return;
        case "offer":
          setOffers((previous) => [...previous.filter((offer) => offer.id !== e.id),
            { id: e.id, author: e.author, name: e.name, text: e.text, timestamp: e.timestamp }]);
          return;
        case "node_exit":
          setNodeAlive(false);
          return;
        case "winner": {
          setWinner({ height: e.height, hash: e.hash, name: e.name, address: e.address, reward: e.reward, local: e.local, ts: Date.now() });
          setBlocks((previous) => e.reorganization ? [e.block] :
            [...previous.filter((block) => block.height < e.height), e.block]);
          setOffers((previous) => previous.filter((offer) => offer.id !== e.offer_id));
          setStatus((s) => (s ? { ...s, height: e.height, hash: e.hash, balance: e.balance,
            mining: false, template: null, classroom: false } : s));
          break;
        }
        case "mining_started":
          setStatus((s) => (s ? { ...s, mining: true, template: e.template } : s));
          break;
        case "mining_paused":
          setStatus((s) => (s ? { ...s, mining: false, template: null } : s));
          break;
        case "classroom_started":
          setStatus((s) => (s ? { ...s, classroom: true } : s));
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
  }, []);

  const send = useCallback(async (cmd: string) => {
    try {
      const response = await fetch("/api/cmd", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cmd }),
      });
      if (!response.ok) throw new Error("El puente rechazó el comando");
    } catch {
      const item: FeedItem = { id: nid(), kind: "error", title: "No se pudo enviar el comando", ts: Date.now() };
      setFeed((items) => [item, ...items].slice(0, 60));
    }
  }, []);

  return { status, users, blocks, offers, feed, winner, online, nodeAlive, send };
}
