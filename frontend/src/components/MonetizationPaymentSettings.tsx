import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Save, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { api, DiscordOptions } from "../lib/api";
import { EmptyState, ErrorState, LoadingState, Section, StatusBadge } from "./Ui";

type ChannelValue = {
  id?: string | null;
  name?: string | null;
  missing: boolean;
};

type MonetizationGatewayStatus = {
  payment_mode: string;
  environment: string;
  webhook_enabled: boolean;
  public_base_url_configured: boolean;
  mercadopago_credentials_configured: boolean;
  mercadopago_public_key_configured: boolean;
  mercadopago_webhook_configured: boolean;
  readonly_env: boolean;
};

type ShopPanelStatus = {
  published: boolean;
  channel_id?: string | null;
  message_id?: string | null;
  status: "not_published" | "ok" | "missing_channel" | "missing_message" | "error";
};

type MonetizationSettingsPayload = {
  guild_id: string;
  values: {
    shop_channel_id?: string | null;
    approval_channel_id?: string | null;
    log_channel_id?: string | null;
    dlc_announcement_channel_id?: string | null;
    shop_message_id?: string | null;
    updated_at?: string | null;
  };
  channels: Record<string, ChannelValue>;
  shop_panel: ShopPanelStatus;
  gateway: MonetizationGatewayStatus;
  security_notes: string[];
};

type Draft = {
  shop_channel_id: string;
  approval_channel_id: string;
  log_channel_id: string;
  dlc_announcement_channel_id: string;
};

const EMPTY_DRAFT: Draft = {
  shop_channel_id: "",
  approval_channel_id: "",
  log_channel_id: "",
  dlc_announcement_channel_id: "",
};

const CHANNEL_FIELDS: { key: keyof Draft; label: string; hint: string }[] = [
  { key: "shop_channel_id", label: "Canal da loja", hint: "Onde o painel fixo da loja será publicado." },
  { key: "approval_channel_id", label: "Canal de aprovação manual", hint: "Usado pelo fluxo manual quando precisar de revisão." },
  { key: "log_channel_id", label: "Canal de logs", hint: "Destino dos avisos operacionais de monetização." },
  { key: "dlc_announcement_channel_id", label: "Canal de anúncios de DLC", hint: "Canal usado para novidades e anúncios de DLC." },
];

function seedDraft(data?: MonetizationSettingsPayload): Draft {
  if (!data) return EMPTY_DRAFT;
  return {
    shop_channel_id: data.values.shop_channel_id || "",
    approval_channel_id: data.values.approval_channel_id || "",
    log_channel_id: data.values.log_channel_id || "",
    dlc_announcement_channel_id: data.values.dlc_announcement_channel_id || "",
  };
}

function statusLabel(status: ShopPanelStatus["status"]) {
  return {
    ok: "Publicado",
    not_published: "Não publicado",
    missing_channel: "Canal ausente",
    missing_message: "Mensagem apagada",
    error: "Erro ao verificar",
  }[status];
}

function statusState(status: ShopPanelStatus["status"]) {
  if (status === "ok") return "online";
  if (status === "not_published") return "neutral";
  return "degraded";
}

export function MonetizationPaymentSettings({ guildId }: { guildId: string }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);

  const settings = useQuery({
    queryKey: ["monetization-payment-settings", guildId],
    queryFn: () => api<MonetizationSettingsPayload>(`/guild/${guildId}/monetization/settings`),
  });
  const options = useQuery({
    queryKey: ["discord-options", guildId],
    queryFn: () => api<DiscordOptions>(`/guild/${guildId}/discord-options`),
    refetchInterval: 60_000,
  });

  useEffect(() => {
    if (settings.data) setDraft(seedDraft(settings.data));
  }, [settings.data]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["monetization-payment-settings", guildId] });
    queryClient.invalidateQueries({ queryKey: ["panels", guildId] });
    queryClient.invalidateQueries({ queryKey: ["audit", guildId] });
  };

  const saveSettings = useMutation({
    mutationFn: () => api<MonetizationSettingsPayload>(`/guild/${guildId}/monetization/settings`, { method: "PATCH", body: JSON.stringify({ values: draft }) }),
    onSuccess: invalidate,
  });
  const publishShop = useMutation({
    mutationFn: () => api<MonetizationSettingsPayload>(`/guild/${guildId}/monetization/settings/shop/publish`, { method: "POST" }),
    onSuccess: invalidate,
  });
  const refreshShop = useMutation({
    mutationFn: () => api<MonetizationSettingsPayload>(`/guild/${guildId}/monetization/settings/shop/refresh`, { method: "POST" }),
    onSuccess: invalidate,
  });

  if (settings.isLoading) return <LoadingState message="Carregando configurações da loja..." />;
  if (settings.error) return <ErrorState message={(settings.error as Error).message} />;
  if (!settings.data) return <EmptyState message="Configurações de monetização indisponíveis." />;

  const data = settings.data;
  const busy = saveSettings.isPending || publishShop.isPending || refreshShop.isPending;
  const error = saveSettings.error || publishShop.error || refreshShop.error;

  return (
    <Section title="Configurações da loja/pagamento" description="Fase 3.4: configure canais da monetização e publique o painel da loja sem editar tokens ou pagamentos antigos.">
      <div className="metric-grid compact-grid monetization-metric-grid">
        <div className="metric-card staff-metric-card"><span>Modo de pagamento</span><strong>{data.gateway.payment_mode}</strong><small>{data.gateway.environment}</small></div>
        <div className="metric-card staff-metric-card"><span>Mercado Pago</span><strong>{data.gateway.mercadopago_credentials_configured ? "Configurado" : "Sem credencial"}</strong><small>Chaves ficam somente no .env</small></div>
        <div className="metric-card staff-metric-card"><span>Webhook</span><strong>{data.gateway.webhook_enabled ? "Ativo" : "Inativo"}</strong><small>{data.gateway.mercadopago_webhook_configured ? "Assinatura configurada" : "Sem assinatura"}</small></div>
      </div>

      <div className="dashboard-form">
        <div className="form-row">
          {CHANNEL_FIELDS.map((field) => (
            <label key={field.key}>{field.label}
              <select value={draft[field.key]} onChange={(event) => setDraft((current) => ({ ...current, [field.key]: event.target.value }))}>
                <option value="">Não definido</option>
                {(options.data?.channels || []).map((channel) => <option value={channel.id} key={channel.id}>#{channel.name}</option>)}
              </select>
              <small>{field.hint}</small>
            </label>
          ))}
        </div>
        <div className="form-actions"><button className="button primary" disabled={busy} onClick={() => saveSettings.mutate()}><Save size={15} />Salvar canais</button></div>
      </div>

      <div className="entity plan-manage-card">
        <div className="entity-title-row"><strong>Painel fixo da loja</strong><StatusBadge state={statusState(data.shop_panel.status)}>{statusLabel(data.shop_panel.status)}</StatusBadge></div>
        <span>{data.shop_panel.channel_id ? `Canal: #${data.channels.shop_channel_id?.name || data.shop_panel.channel_id}` : "Canal da loja não definido"}</span>
        <small>{data.shop_panel.message_id ? `Mensagem: ${data.shop_panel.message_id}` : "Sem mensagem publicada"}</small>
        <div className="card-actions"><button className="button ghost" disabled={busy || !draft.shop_channel_id} onClick={() => publishShop.mutate()}><Send size={15} />Publicar loja</button><button className="button ghost" disabled={busy || !data.shop_panel.published} onClick={() => refreshShop.mutate()}><RefreshCw size={15} />Atualizar loja</button></div>
      </div>

      {error && <p className="inline-warning">{(error as Error).message}</p>}
    </Section>
  );
}
