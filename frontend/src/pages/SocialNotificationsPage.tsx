import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCircle2, Eye, ExternalLink, History, Send, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { useShell } from "../components/AppShell";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import {
  api,
  DiscordOptions,
  SocialNotificationMutationResponse,
  SocialNotificationPreview,
  SocialNotificationsPayload,
} from "../lib/api";

const DEFAULT_MESSAGE = "🎬 **NOVO VÍDEO!**\n\nConfira o novo conteúdo:\n{url}";

const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  instagram: "Instagram",
  twitch: "Twitch",
  kick: "Kick",
  other: "Outra plataforma",
};

export function SocialNotificationsPage() {
  const { guild, readiness, guildsError } = useShell();
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [channelId, setChannelId] = useState("");
  const [message, setMessage] = useState(DEFAULT_MESSAGE);
  const [mentionEveryone, setMentionEveryone] = useState(true);

  const notifications = useQuery({
    queryKey: ["social-notifications", guild?.id],
    queryFn: () => api<SocialNotificationsPayload>(`/guild/${guild!.id}/social-notifications`),
    enabled: Boolean(guild),
    refetchInterval: 20_000,
  });

  const options = useQuery({
    queryKey: ["discord-options", guild?.id],
    queryFn: () => api<DiscordOptions>(`/guild/${guild!.id}/discord-options`),
    enabled: Boolean(guild),
    refetchInterval: 60_000,
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      api<SocialNotificationPreview>(`/guild/${guild!.id}/social-notifications/preview`, {
        method: "POST",
        body: JSON.stringify({ url, message }),
      }),
  });

  const sendMutation = useMutation({
    mutationFn: () =>
      api<SocialNotificationMutationResponse>(`/guild/${guild!.id}/social-notifications`, {
        method: "POST",
        body: JSON.stringify({
          url,
          channel_id: channelId,
          message,
          mention_everyone: mentionEveryone,
        }),
      }),
    onSuccess: () => {
      setUrl("");
      setPreview(null);
      queryClient.invalidateQueries({ queryKey: ["social-notifications", guild?.id] });
      queryClient.invalidateQueries({ queryKey: ["audit", guild?.id] });
    },
  });

  const [preview, setPreview] = useState<SocialNotificationPreview | null>(null);

  const channels = useMemo(
    () =>
      options.data?.channels.filter(
        (channel) => channel.type.includes("text") || channel.type.includes("news"),
      ) || [],
    [options.data],
  );

  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (!guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (notifications.isLoading) return <LoadingState />;
  if (notifications.error) return <ErrorState message={(notifications.error as Error).message} />;

  const items = notifications.data?.items || [];

  return (
    <>
      <PageHeader
        title="Redes sociais"
        description="Publique manualmente um aviso de novo vídeo ou conteúdo em um canal do Discord."
      />

      <Section
        title="Nova notificação"
        description="O envio acontece imediatamente. O histórico fica salvo para auditoria e para a futura automação."
        icon={<Bell />}
      >
        <div className="dashboard-form">
          <label>
            Link do conteúdo
            <input
              type="url"
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                setPreview(null);
              }}
              placeholder="https://youtube.com/watch?v=..."
            />
            <small>YouTube, TikTok, Instagram, Twitch e Kick são identificados automaticamente pela URL.</small>
          </label>

          <label>
            Canal do Discord
            <select value={channelId} onChange={(event) => setChannelId(event.target.value)}>
              <option value="">Escolha o canal</option>
              {channels.map((channel) => (
                <option value={channel.id} key={channel.id}>
                  # {channel.name}
                </option>
              ))}
            </select>
          </label>

          <label>
            Mensagem
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              rows={7}
              maxLength={2000}
            />
            <small>
              Use <code>{"{url}"}</code> onde o link deve aparecer. A mensagem final respeita o limite de 2000 caracteres do Discord.
            </small>
          </label>

          <label className="role-checkbox">
            <input
              type="checkbox"
              checked={mentionEveryone}
              onChange={(event) => setMentionEveryone(event.target.checked)}
            />
            <span>Marcar @everyone</span>
          </label>

          <div className="form-actions">
            <button
              className="button ghost"
              disabled={previewMutation.isPending || !url.trim()}
              onClick={() => {
                previewMutation.mutate(undefined, {
                  onSuccess: (result) => setPreview(result),
                });
              }}
            >
              <Eye size={16} />
              Pré-visualizar
            </button>
            <button
              className="button primary"
              disabled={sendMutation.isPending || !url.trim() || !channelId || !message.trim()}
              onClick={() => sendMutation.mutate()}
            >
              <Send size={16} />
              Enviar agora
            </button>
          </div>

          {previewMutation.error && (
            <p className="inline-warning">
              <TriangleAlert size={15} /> {(previewMutation.error as Error).message}
            </p>
          )}
          {sendMutation.error && (
            <p className="inline-warning">
              <TriangleAlert size={15} /> {(sendMutation.error as Error).message}
            </p>
          )}

          {preview && (
            <div className="entity">
              <div className="entity-title-row">
                <strong>Pré-visualização</strong>
                <StatusBadge state="online">{PLATFORM_LABELS[preview.platform] || preview.platform}</StatusBadge>
              </div>
              <p style={{ whiteSpace: "pre-wrap" }}>
                {mentionEveryone ? "@everyone\n" : ""}
                {preview.message}
              </p>
              <a href={preview.url} target="_blank" rel="noreferrer">
                Abrir conteúdo <ExternalLink size={14} />
              </a>
            </div>
          )}
        </div>
      </Section>

      <Section
        title="Histórico"
        description="Últimos avisos enviados pelo painel web."
        icon={<History />}
      >
        {items.length === 0 ? (
          <EmptyState message="Nenhuma notificação enviada ainda." />
        ) : (
          <div className="entity-grid giveaway-grid">
            {items.map((item) => (
              <div className="entity giveaway-card" key={item.id}>
                <div className="entity-title-row">
                  <strong>{PLATFORM_LABELS[item.platform] || item.platform}</strong>
                  <StatusBadge state={item.status === "SENT" ? "online" : "offline"}>
                    {item.status === "SENT" ? "Enviado" : "Falhou"}
                  </StatusBadge>
                </div>
                <span>Canal: {item.channel_name ? `#${item.channel_name}` : item.channel_id}</span>
                <span>{item.mention_everyone ? "@everyone ativado" : "@everyone desativado"}</span>
                <span>{item.created_at ? formatDate(item.created_at) : "—"}</span>
                <a href={item.url} target="_blank" rel="noreferrer">
                  Abrir conteúdo <ExternalLink size={14} />
                </a>
                {item.status === "SENT" ? (
                  <small><CheckCircle2 size={14} /> Mensagem enviada com sucesso.</small>
                ) : (
                  <p className="inline-warning">{item.error_message || "Falha sem detalhes."}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>
    </>
  );
}

function formatDate(value: string) {
  try {
    return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
  } catch {
    return value;
  }
}
