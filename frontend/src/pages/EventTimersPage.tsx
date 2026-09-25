import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Pause, Play, Plus, RefreshCw, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { useShell } from "../components/AppShell";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api, DiscordOptions, EventTimerItem, EventTimersPayload } from "../lib/api";

type EndMode = "duration" | "date";
type DurationUnit = "minutes" | "hours" | "days";

export function EventTimersPage() {
  const { guild, readiness, guildsError } = useShell();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [channelId, setChannelId] = useState("");
  const [repeatSeconds, setRepeatSeconds] = useState(43200);
  const [endMode, setEndMode] = useState<EndMode>("duration");
  const [durationAmount, setDurationAmount] = useState(1);
  const [durationUnit, setDurationUnit] = useState<DurationUnit>("days");
  const [endsAt, setEndsAt] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const timers = useQuery({
    queryKey: ["event-timers", guild?.id],
    queryFn: () => api<EventTimersPayload>(`/guild/${guild!.id}/event-timers`),
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
    queryClient.invalidateQueries({ queryKey: ["event-timers", guild?.id] });
    queryClient.invalidateQueries({ queryKey: ["audit", guild?.id] });
  };

  const createMutation = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.set("title", title);
      form.set("description", description);
      form.set("channel_id", channelId);
      form.set("repeat_interval_seconds", String(repeatSeconds));
      form.set("end_mode", endMode);
      form.set("duration_amount", String(durationAmount));
      form.set("duration_unit", durationUnit);
      if (endsAt) form.set("ends_at", new Date(endsAt).toISOString());
      form.set("mention_everyone", "true");
      if (image) form.set("image", image);
      return api<any>(`/guild/${guild!.id}/event-timers`, { method: "POST", body: form });
    },
    onSuccess: () => {
      setCreateOpen(false);
      setTitle("");
      setDescription("");
      setChannelId("");
      setImage(null);
      invalidate();
    },
  });

  const actionMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "pause" | "resume" | "resend" | "cancel" }) =>
      api(`/guild/${guild!.id}/event-timers/${id}/${action}`, { method: "POST" }),
    onSuccess: invalidate,
  });

  const items = timers.data?.items || [];
  const summary = useMemo(() => ({
    active: items.filter((item) => item.status === "ACTIVE").length,
    paused: items.filter((item) => item.status === "PAUSED").length,
    finished: items.filter((item) => ["FINISHED", "CANCELED"].includes(item.status)).length,
  }), [items]);
  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (!guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (timers.isLoading) return <LoadingState />;
  if (timers.error) return <ErrorState message={(timers.error as Error).message} />;

  return (
    <>
      <PageHeader
        title="Cronômetros de eventos"
        description="Republica avisos com @everyone no intervalo configurado até o evento terminar."
        action={<button className="button primary" onClick={() => setCreateOpen((value) => !value)}><Plus size={16} />Novo cronômetro</button>}
      />
      <div className="entity-grid compact-grid">
        <Metric title="Ativos" value={summary.active} />
        <Metric title="Pausados" value={summary.paused} />
        <Metric title="Finalizados" value={summary.finished} />
      </div>

      {createOpen && (
        <Section title="Criar cronômetro" description="A imagem fica no storage enquanto o cronômetro estiver ativo ou pausado e é removida ao encerrar.">
          <div className="dashboard-form">
            <label>Título<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={256} /></label>
            <label>Descrição<textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} /></label>
            <label>Canal<select value={channelId} onChange={(e) => setChannelId(e.target.value)}>
              <option value="">Escolha o canal</option>
              {options.data?.channels.filter((channel) => channel.type.includes("text") || channel.type.includes("news")).map((channel) => (
                <option key={channel.id} value={channel.id}># {channel.name}</option>
              ))}
            </select></label>
            <div className="form-row">
              <label>Repetir a cada<select value={repeatSeconds} onChange={(e) => setRepeatSeconds(Number(e.target.value))}>
                <option value={1800}>30 minutos</option>
                <option value={3600}>1 hora</option>
                <option value={7200}>2 horas</option>
                <option value={21600}>6 horas</option>
                <option value={43200}>12 horas</option>
                <option value={86400}>24 horas</option>
              </select></label>
              <label>Encerramento<select value={endMode} onChange={(e) => setEndMode(e.target.value as EndMode)}>
                <option value="duration">Por duração</option>
                <option value="date">Por data/hora</option>
              </select></label>
            </div>
            {endMode === "duration" ? (
              <div className="form-row">
                <label>Duração<input type="number" min="1" value={durationAmount} onChange={(e) => setDurationAmount(Number(e.target.value))} /></label>
                <label>Unidade<select value={durationUnit} onChange={(e) => setDurationUnit(e.target.value as DurationUnit)}>
                  <option value="minutes">minutos</option>
                  <option value="hours">horas</option>
                  <option value="days">dias</option>
                </select></label>
              </div>
            ) : (
              <label>Data e hora final<input type="datetime-local" value={endsAt} onChange={(e) => setEndsAt(e.target.value)} /></label>
            )}
            <label>Imagem do evento
              <input type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" onChange={(e) => setImage(e.target.files?.[0] || null)} />
            </label>
            <small>A imagem aparece grande no final do embed. Limite: 8 MB.</small>
            <div className="form-actions">
              <button className="button ghost" onClick={() => setCreateOpen(false)}>Cancelar</button>
              <button className="button primary" disabled={createMutation.isPending || !title || !channelId} onClick={() => createMutation.mutate()}>
                <BellRing size={16} />Criar e publicar
              </button>
            </div>
            {createMutation.error && <p className="inline-warning">{(createMutation.error as Error).message}</p>}
          </div>
        </Section>
      )}

      <Section title="Cronômetros existentes" description="A republicação apaga apenas a mensagem anterior daquele cronômetro.">
        {items.length === 0 ? <EmptyState message="Nenhum cronômetro criado ainda." /> : (
          <div className="entity-grid giveaway-grid">
            {items.map((item) => (
              <EventTimerCard key={item.id} item={item} busy={actionMutation.isPending} onAction={(action) => actionMutation.mutate({ id: item.id, action })} />
            ))}
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

function EventTimerCard({ item, busy, onAction }: { item: EventTimerItem; busy: boolean; onAction: (action: "pause" | "resume" | "resend" | "cancel") => void }) {
  const active = item.status === "ACTIVE";
  const paused = item.status === "PAUSED";
  return (
    <div className="entity giveaway-card">
      <div className="entity-title-row">
        <strong>{item.title}</strong>
        <StatusBadge state={active ? "online" : paused ? "degraded" : "offline"}>{statusLabel(item.status)}</StatusBadge>
      </div>
      {item.description && <p>{item.description}</p>}
      <span>Canal: {item.channel_missing ? "canal removido" : `#${item.channel_name || item.channel_id}`}</span>
      <span>Repetição: {formatInterval(item.repeat_interval_seconds)}</span>
      <span>Encerra: {formatDate(item.ends_at)}</span>
      {item.next_announcement_at && <span>Próximo aviso: {formatDate(item.next_announcement_at)}</span>}
      {item.has_image && <small>Imagem: {item.image_filename || "arquivo anexado"}</small>}
      {item.last_error && <p className="inline-warning">{item.last_error}</p>}
      <div className="card-actions">
        {active && <button className="button ghost" disabled={busy} onClick={() => onAction("pause")}><Pause size={15} />Pausar</button>}
        {paused && <button className="button ghost" disabled={busy} onClick={() => onAction("resume")}><Play size={15} />Retomar</button>}
        {active && <button className="button ghost" disabled={busy} onClick={() => onAction("resend")}><RefreshCw size={15} />Reenviar agora</button>}
        {(active || paused) && <button className="button danger" disabled={busy} onClick={() => onAction("cancel")}><XCircle size={15} />Encerrar</button>}
      </div>
    </div>
  );
}

function statusLabel(status: string) {
  if (status === "ACTIVE") return "Ativo";
  if (status === "PAUSED") return "Pausado";
  if (status === "FINISHED") return "Finalizado";
  if (status === "CANCELED") return "Cancelado";
  if (status === "ERROR") return "Erro";
  return status;
}

function formatDate(value: string) {
  try {
    return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
  } catch {
    return value;
  }
}

function formatInterval(seconds: number) {
  if (seconds % 86400 === 0) return `${seconds / 86400} dia(s)`;
  if (seconds % 3600 === 0) return `${seconds / 3600} hora(s)`;
  return `${Math.round(seconds / 60)} minuto(s)`;
}
