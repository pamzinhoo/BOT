import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCcw, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { useShell } from "../components/AppShell";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api, DiscordOptions, FixedPanelItem, PanelsPayload, TicketPanelGroupItem, TicketPanelItem } from "../lib/api";

type PanelAction = {
  path: string;
  body?: Record<string, unknown>;
};

type PublishState = Record<string, string>;

export function PanelsPage() {
  const { guild, readiness, guildsError } = useShell();
  const queryClient = useQueryClient();
  const [publishChannels, setPublishChannels] = useState<PublishState>({});

  const panels = useQuery({
    queryKey: ["panels", guild?.id],
    queryFn: () => api<PanelsPayload>(`/guild/${guild!.id}/panels`),
    enabled: Boolean(guild),
    refetchInterval: 30_000,
  });
  const options = useQuery({
    queryKey: ["discord-options", guild?.id],
    queryFn: () => api<DiscordOptions>(`/guild/${guild!.id}/discord-options`),
    enabled: Boolean(guild),
    refetchInterval: 60_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["panels", guild?.id] });
    queryClient.invalidateQueries({ queryKey: ["audit", guild?.id] });
  };
  const actionMutation = useMutation({
    mutationFn: ({ path, body }: PanelAction) => api<unknown>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
    onSuccess: invalidate,
  });

  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (panels.isLoading) return <LoadingState />;
  if (panels.error) return <ErrorState message={(panels.error as Error).message} />;

  const textChannels = options.data?.channels.filter((channel) => channel.type.includes("text")) || [];
  const setChannel = (key: string, value: string) => setPublishChannels((current) => ({ ...current, [key]: value }));
  const selectedChannel = (key: string, current?: string | null) => publishChannels[key] || current || "";
  const publish = (key: string, path: string, current?: string | null) => {
    const channelId = selectedChannel(key, current);
    if (!channelId) return;
    actionMutation.mutate({ path, body: { channel_id: channelId } });
  };

  return (
    <>
      <PageHeader
        title="Painéis do Discord"
        description="Publique, atualize e remova mensagens fixas usando os serviços reais do bot. Atualizar edita a mensagem existente; publicar troca o canal quando necessário."
      />
      <Section title="Painéis fixos" description="Loja/Compras e Ranking. A loja também mostra planos e DLCs pagas.">
        <div className="entity-grid panel-grid">
          {panels.data?.fixed.map((item) => (
            <FixedPanelCard
              key={item.id}
              item={item}
              channels={textChannels}
              selectedChannel={selectedChannel(`fixed-${item.id}`, item.channel_id)}
              onChannel={(value) => setChannel(`fixed-${item.id}`, value)}
              busy={actionMutation.isPending}
              onPublish={() => publish(`fixed-${item.id}`, `/guild/${guild!.id}/panels/fixed/${item.id}/publish`, item.channel_id)}
              onRefresh={() => actionMutation.mutate({ path: `/guild/${guild!.id}/panels/fixed/${item.id}/refresh` })}
            />
          ))}
        </div>
      </Section>
      <Section title="Painéis de tickets" description="Painéis individuais de abertura de ticket.">
        {panels.data?.ticket_panels.length === 0 ? <EmptyState message="Nenhum painel criado." /> : (
          <div className="entity-grid panel-grid">
            {panels.data?.ticket_panels.map((panel) => (
              <TicketPanelCard
                key={panel.id}
                panel={panel}
                channels={textChannels}
                selectedChannel={selectedChannel(`ticket-${panel.id}`, panel.channel_id)}
                onChannel={(value) => setChannel(`ticket-${panel.id}`, value)}
                busy={actionMutation.isPending}
                onPublish={() => publish(`ticket-${panel.id}`, `/guild/${guild!.id}/panels/ticket/${panel.id}/publish`, panel.channel_id)}
                onRefresh={() => actionMutation.mutate({ path: `/guild/${guild!.id}/panels/ticket/${panel.id}/refresh` })}
                onUnpublish={() => actionMutation.mutate({ path: `/guild/${guild!.id}/panels/ticket/${panel.id}/unpublish` })}
              />
            ))}
          </div>
        )}
      </Section>
      <Section title="Combos de tickets" description="Vários painéis de ticket em uma única mensagem.">
        {panels.data?.groups.length === 0 ? <EmptyState message="Nenhum combo criado." /> : (
          <div className="entity-grid panel-grid">
            {panels.data?.groups.map((group) => (
              <GroupPanelCard
                key={group.id}
                group={group}
                channels={textChannels}
                selectedChannel={selectedChannel(`group-${group.id}`, group.channel_id)}
                onChannel={(value) => setChannel(`group-${group.id}`, value)}
                busy={actionMutation.isPending}
                onPublish={() => publish(`group-${group.id}`, `/guild/${guild!.id}/panels/group/${group.id}/publish`, group.channel_id)}
                onRefresh={() => actionMutation.mutate({ path: `/guild/${guild!.id}/panels/group/${group.id}/refresh` })}
                onUnpublish={() => actionMutation.mutate({ path: `/guild/${guild!.id}/panels/group/${group.id}/unpublish` })}
              />
            ))}
          </div>
        )}
        {actionMutation.error && <p className="inline-warning">{(actionMutation.error as Error).message}</p>}
      </Section>
    </>
  );
}

function FixedPanelCard({ item, channels, selectedChannel, onChannel, busy, onPublish, onRefresh }: {
  item: FixedPanelItem;
  channels: DiscordOptions["channels"];
  selectedChannel: string;
  onChannel: (value: string) => void;
  busy: boolean;
  onPublish: () => void;
  onRefresh: () => void;
}) {
  return (
    <div className="entity panel-card">
      <PanelHeader title={item.name} status={item.status} published={item.published} />
      <p>{item.description}</p>
      <PanelMeta channelName={item.channel_name} messageId={item.message_id} status={item.status} />
      <PublishControls channels={channels} value={selectedChannel} onChange={onChannel} />
      <div className="card-actions">
        <button className="button primary" disabled={busy || !selectedChannel} onClick={onPublish}><Send size={15} />Publicar</button>
        <button className="button ghost" disabled={busy || !item.published} onClick={onRefresh}><RefreshCcw size={15} />Atualizar</button>
      </div>
    </div>
  );
}

function TicketPanelCard({ panel, channels, selectedChannel, onChannel, busy, onPublish, onRefresh, onUnpublish }: {
  panel: TicketPanelItem;
  channels: DiscordOptions["channels"];
  selectedChannel: string;
  onChannel: (value: string) => void;
  busy: boolean;
  onPublish: () => void;
  onRefresh: () => void;
  onUnpublish: () => void;
}) {
  return (
    <div className="entity panel-card">
      <PanelHeader title={panel.name} status={panel.status} published={panel.published} enabled={panel.enabled} />
      <span className="mono">{panel.key}</span>
      <span>{panel.show_button ? "Com botão de abertura" : "Sem botão clicável"}</span>
      <PanelMeta channelName={panel.channel_name} messageId={panel.message_id} status={panel.status} />
      <PublishControls channels={channels} value={selectedChannel} onChange={onChannel} />
      <div className="card-actions">
        <button className="button primary" disabled={busy || !selectedChannel} onClick={onPublish}><Send size={15} />Publicar</button>
        <button className="button ghost" disabled={busy || !panel.published} onClick={onRefresh}><RefreshCcw size={15} />Atualizar</button>
        <button className="button danger" disabled={busy || !panel.published} onClick={onUnpublish}><Trash2 size={15} />Remover mensagem</button>
      </div>
    </div>
  );
}

function GroupPanelCard({ group, channels, selectedChannel, onChannel, busy, onPublish, onRefresh, onUnpublish }: {
  group: TicketPanelGroupItem;
  channels: DiscordOptions["channels"];
  selectedChannel: string;
  onChannel: (value: string) => void;
  busy: boolean;
  onPublish: () => void;
  onRefresh: () => void;
  onUnpublish: () => void;
}) {
  return (
    <div className="entity panel-card">
      <PanelHeader title={group.name} status={group.status} published={group.published} />
      <span>{group.panel_count} painel(is) no combo</span>
      <PanelMeta channelName={group.channel_name} messageId={group.message_id} status={group.status} />
      <PublishControls channels={channels} value={selectedChannel} onChange={onChannel} />
      <div className="card-actions">
        <button className="button primary" disabled={busy || !selectedChannel} onClick={onPublish}><Send size={15} />Publicar</button>
        <button className="button ghost" disabled={busy || !group.published} onClick={onRefresh}><RefreshCcw size={15} />Atualizar</button>
        <button className="button danger" disabled={busy || !group.published} onClick={onUnpublish}><Trash2 size={15} />Remover mensagem</button>
      </div>
    </div>
  );
}

function PanelHeader({ title, status, published, enabled = true }: { title: string; status: string; published: boolean; enabled?: boolean }) {
  const state = !enabled || status === "missing_channel" || status === "missing_message" ? "offline" : status === "ok" ? "online" : "degraded";
  return (
    <div className="entity-title-row">
      <strong>{title}</strong>
      <StatusBadge state={state}>{statusLabel(status, published, enabled)}</StatusBadge>
    </div>
  );
}

function PanelMeta({ channelName, messageId, status }: { channelName?: string | null; messageId?: string | null; status: string }) {
  return (
    <div className="panel-meta">
      <span>Canal: {channelName ? `#${channelName}` : "não configurado"}</span>
      <span>Mensagem: {messageId || "—"}</span>
      {status === "missing_message" && <small>A mensagem foi apagada no Discord. Publique de novo.</small>}
      {status === "missing_channel" && <small>O canal salvo não existe mais. Escolha outro canal e publique.</small>}
    </div>
  );
}

function PublishControls({ channels, value, onChange }: { channels: DiscordOptions["channels"]; value: string; onChange: (value: string) => void }) {
  return (
    <label className="panel-channel-select">Canal para publicar
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Escolha o canal</option>
        {channels.map((channel) => <option value={channel.id} key={channel.id}># {channel.name}</option>)}
      </select>
    </label>
  );
}

function statusLabel(status: string, published: boolean, enabled: boolean) {
  if (!enabled) return "Inativo";
  if (!published || status === "not_published") return "Não publicado";
  if (status === "ok") return "Publicado";
  if (status === "missing_message") return "Mensagem apagada";
  if (status === "missing_channel") return "Canal apagado";
  return "Erro ao verificar";
}
