import { Pause, Pickaxe, Plus, Users } from "lucide-react";
import { useState } from "react";
import type { Offer, Status } from "../useNode";

const action = "inline-flex items-center justify-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40";

export default function OffersPanel({ offers, status, ready, send }: {
  offers: Offer[];
  status: Status | null;
  ready: boolean;
  send: (command: string) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [selection, setSelection] = useState("");
  const selected = offers.find((offer) => offer.id === selection) ?? offers[0];
  const mining = !!status?.mining;
  const classroom = !!status?.classroom;

  return (
    <section className="panel grid gap-5 p-5 sm:p-6 lg:grid-cols-2">
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!text.trim()) return;
          void send("/ofrecer " + text.trim());
          setText("");
        }}
      >
        <label className="label" htmlFor="new-offer">Contenido del bloque</label>
        <div className="flex gap-2">
          <input
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none focus:border-signal/60"
            id="new-offer"
            maxLength={120}
            onChange={(event) => setText(event.target.value)}
            placeholder="Escribe una oferta para el salón"
            required
            value={text}
          />
          <button className={action} disabled={!ready || !text.trim()} type="submit">
            <Plus className="h-4 w-4" /> Crear oferta
          </button>
        </div>
      </form>

      <div className="flex flex-col gap-2">
        <label className="label" htmlFor="pending-offer">Ofertas pendientes ({offers.length})</label>
        <div className="flex flex-wrap gap-2">
          <select
            className="min-w-0 max-w-full flex-1 basis-full rounded-lg border border-white/10 bg-zinc-900 px-3 py-2 text-sm disabled:opacity-50 sm:basis-40"
            disabled={!selected || classroom}
            id="pending-offer"
            onChange={(event) => setSelection(event.target.value)}
            value={selected?.id ?? ""}
          >
            {!selected && <option value="">Sin ofertas pendientes</option>}
            {offers.map((offer) => <option key={offer.id} value={offer.id}>{offer.name} · {offer.text}</option>)}
          </select>
          <button
            className={action}
            disabled={!ready || !selected || classroom}
            onClick={() => selected && send("/iniciar " + selected.id)}
            type="button"
          >
            <Users className="h-4 w-4" /> Iniciar salón
          </button>
          <button
            className={action + " bg-signal/15 text-signal"}
            disabled={!ready || (!selected && !mining && !classroom)}
            onClick={() => send(mining ? "/pausar" : classroom ? "/minar" : "/minar " + selected?.id)}
            type="button"
          >
            {mining ? <Pause className="h-4 w-4" /> : <Pickaxe className="h-4 w-4" />}
            {mining ? "Pausar" : classroom ? "Unirme" : "Minar"}
          </button>
        </div>
      </div>
    </section>
  );
}
