import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gift, Plus, RotateCcw, ShieldAlert, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { useShell } from "../components/AppShell";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api, DiscordOptions, GiveawayItem, GiveawayMutationResponse, GiveawaysPayload } from "../lib/api";

type Draft = {
  title: string;
  description: string;
  channel_id: string;
  duration_minutes: number;
  winners_count: number;
  allowed_role_ids: string[];
  prize_type: "CUSTOM" | "ROLE";
  prize_text: string;
  prize_role_id: string;
};

const DEFAULT_DRAFT: Draft = {
  title: "",
  description: "",
  channel_id: "",
  duration_minutes: 60,
  winners_count: 1,
  allowed_role_ids: [],
  prize_type: "CUSTOM",
  prize_text: "",
  prize_role_id: "",
};

export function GiveawaysPage() {
  const { guild, readiness, guildsError } = useShell();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(DEFAULT_DRAFT);
  const [createOpen, setCreateOpen] = useState(false);
  const giveaways = useQuery({
    queryKey: ["giveaways", guild?.id],
    queryFn: () => api<GiveawaysPayload>(`/guild/${guild!.id}/giveaways`),
    enabled: Boolean(guild),
    refetchInterval: 20_000,
  });
  const options = useQuery({
    queryKey: ["discord-options", guild?.id],
    queryFn: () => api<DiscordOptions>(`/guild/${guild!.id}/discord-options`),
    enabled: Boolean(guild),
    refetchInterval: 60_000,
  });
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["giveaways", guild?.id] });
    queryClient.invalidateQueries({ queryKey: ["audit", guild?.id] });
  };
  const createMutation = useMutation({
    mutationFn: () => api<GiveawayMutationResponse>(`/guild/${guild!.id}/giveaways`, { method: "POST", body: JSON.stringify(draft) }),
    onSuccess: () => {
      setDraft(DEFAULT_DRAFT);
      setCreateOpen(false);
      invalidate();
    },
  });
  const actionMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "close" | "cancel" | "reroll" }) => api<GiveawayMutationResponse>(`/guild/${guild!.id}/giveaways/${id}/${action}`, { method: "POST" }),
    onSuccess: invalidate,
  });
  const items = giveaways.data?.items || [];
  const summary = useMemo(() => ({
    open: items.filter((item) => item.status === "OPEN").length,
    closed: items.filter((item) => item.status === "CLOSED").length,
    canceled: items.filter((item) => item.status === "CANCELED").length,
  }), [items]);

  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (giveaways.isLoading) return <LoadingState />;
  if (giveaways.error) return <ErrorState message={(giveaways.error as Error).message} />;

  return (
    <>
      <PageHeader
        title="Sorteios"
        description="Crie, acompanhe, encerre, cancele e rerolle sorteios usando o mesmo serviço real do bot."
        action={<button className="button primary" onClick={() => setCreateOpen((value) => !value)}><Plus size={16} />Novo sorteio</button>}
      />
      <div className="entity-grid compact-grid">
        <Metric title="Abertos" value={summary.open} />
        <Metric title="Encerrados" value={summary.closed} />
        <Metric title="Cancelados" value={summary.canceled} />
      </div>
      {createOpen && (
        <Section title="Criar sorteio" description="O painel vai publicar a mensagem no Discord e registrar auditoria como Dashboard local.">
          <div className="dashboard-form">
            <label>Título<input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} maxLength={256} /></label>
            <label>Descrição<textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={3} maxLength={500} /></label>
            <label>Canal<select value={draft.channel_id} onChange={(event) => setDraft({ ...draft, channel_id: event.target.value })}>
              <option value="">Escolha o canal</option>
              {options.data?.channels.filter((channel) => channel.type.includes("text") || channel.type.includes("news")).map((channel) => (
                <option value={channel.id} key={channel.id}># {channel.name}</option>
              ))}
            </select></label>
            <div className="form-row">
              <label>Duração<input type="number" min="1" value={draft.duration_minutes} onChange={(event) => setDraft({ ...draft, duration_minutes: Number(event.target.value) })} /></label>
              <label>Unidade<select value="minutes" disabled><option value="minutes">minutos</option></select></label>
              <label>Vencedores<input type="number" min="1" max="50" value={draft.winners_count} onChange={(event) => setDraft({ ...draft, winners_count: Number(event.target.value) })} /></label>
            </div>
            <label>Cargos permitidos<select multiple value={draft.allowed_role_ids} onChange={(event) => setDraft({ ...draft, allowed_role_ids: Array.from(event.target.selectedOptions).map((option) => option.value) })}>
              {options.data?.roles.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}
            </select><small>Vazio = todo mundo pode participar.</small></label>
            <label>Tipo de prêmio<select value={draft.prize_type} onChange={(event) => setDraft({ ...draft, prize_type: event.target.value as Draft["prize_type"] })}>
              <option value="CUSTOM">Texto personalizado</option>
              <option value="ROLE">Cargo</option>
            </select></label>
            {draft.prize_type === "ROLE" ? (
              <label>Cargo-prêmio<select value={draft.prize_role_id} onChange={(event) => setDraft({ ...draft, prize_role_id: event.target.value })}>
                <option value="">Escolha o cargo</option>
                {options.data?.roles.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}
              </select></label>
            ) : (
              <label>Prêmio<input value={draft.prize_text} onChange={(event) => setDraft({ ...draft, prize_text: event.target.value })} maxLength={500} placeholder="Ex: 1 mês de VIP" /></label>
            )}
            <div className="form-actions">
              <button className="button ghost" onClick={() => { setDraft(DEFAULT_DRAFT); setCreateOpen(false); }}>Cancelar</button>
              <button className="button primary" disabled={createMutation.isPending} onClick={() => createMutation.mutate()}><Gift size={16} />Criar e publicar</button>
            </div>
            {createMutation.error && <p className="inline-warning">{(createMutation.error as Error).message}</p>}
          </div>
        </Section>
      )}
      <Section title="Sorteios existentes" description="Ações aqui mexem no sorteio real no Discord.">
        {items.length === 0 ? <EmptyState message="Nenhum sorteio criado ainda." /> : (
          <div className="entity-grid giveaway-grid">
            {items.map((item) => <GiveawayCard key={item.id} item={item} busy={actionMutation.isPending} onAction={(action) => actionMutation.mutate({ id: item.id, action })} />)}
          </div>
        )}
        {actionMutation.error && <p className="inline-warning">{(actionMutation.error as Error).message}</p>}
      </Section>
    </>
  );
}

function Metric({ title, value }: { title: string; value: number }) {
  return <div className="entity metric-card"><span>{title}</span><strong>{value}</strong></div>;
}

function GiveawayCard({ item, busy, onAction }: { item: GiveawayItem; busy: boolean; onAction: (action: "close" | "cancel" | "reroll") => void }) {
  const isOpen = item.status === "OPEN";
  const isClosed = item.status === "CLOSED";
  const prize = item.prize_type === "ROLE" ? item.prize_role_name || item.prize_role_id || "Cargo" : item.prize_text || "—";
  return (
    <div className="entity giveaway-card">
      <div className="entity-title-row">
        <strong>{item.title}</strong>
        <StatusBadge state={isOpen ? "online" : item.status === "CANCELED" ? "offline" : "warning"}>{statusLabel(item.status)}</StatusBadge>
      </div>
      {item.description && <p>{item.description}</p>}
      <span>Canal: {item.channel_missing ? "canal removido" : `#${item.channel_name || item.channel_id}`}</span>
      <span>Prêmio: {prize}</span>
      <span>Participantes: {item.entry_count} · Vencedores: {item.winners_count}</span>
      <span>Encerra: {formatDate(item.expires_at)}</span>
      {item.winner_names.length > 0 && <small>Ganhadores: {item.winner_names.join(", ")}</small>}
      {(item.channel_missing || item.missing_allowed_role_ids.length > 0) && <p className="inline-warning"><ShieldAlert size={14} /> Existe canal/cargo apagado nesse sorteio.</p>}
      <div className="card-actions">
        {isOpen && <button className="button danger" disabled={busy} onClick={() => onAction("close")}>Encerrar</button>}
        {isOpen && <button className="button ghost" disabled={busy} onClick={() => onAction("cancel")}><XCircle size={15} />Cancelar</button>}
        {isClosed && <button className="button ghost" disabled={busy} onClick={() => onAction("reroll")}><RotateCcw size={15} />Reroll</button>}
      </div>
    </div>
  );
}

function statusLabel(status: string) {
  if (status === "OPEN") return "Aberto";
  if (status === "CLOSED") return "Encerrado";
  if (status === "CANCELED") return "Cancelado";
  return status;
}

function formatDate(value: string) {
  try {
    return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
  } catch {
    return value;
  }
}
