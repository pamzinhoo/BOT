import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { useShell } from "../components/AppShell";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api, MonetizationSummary } from "../lib/api";

function fmtDate(value?: string | null) {
  return value ? new Date(value).toLocaleString("pt-BR") : "Sem dados";
}

function paymentStatusLabel(value: string) {
  return {
    pending: "Pendente",
    processing: "Processando",
    approved: "Aprovado",
    rejected: "Recusado",
    expired: "Expirado",
    canceled: "Cancelado",
    refunded: "Estornado",
    chargeback: "Chargeback",
  }[value] || value;
}

function paymentState(value: string) {
  if (value === "approved") return "online";
  if (value === "pending" || value === "processing") return "degraded";
  return "offline";
}

function alertState(value: string) {
  if (value === "error") return "offline";
  if (value === "warning") return "degraded";
  return "neutral";
}

export function MonetizationPage() {
  const { guild, readiness, guildsError } = useShell();
  const { data, isLoading, error } = useQuery({
    queryKey: ["monetization", guild?.id],
    queryFn: () => api<MonetizationSummary>(`/guild/${guild!.id}/monetization/summary`),
    enabled: Boolean(guild),
  });

  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return <EmptyState message="Resumo de monetização indisponível." />;

  return (
    <>
      <PageHeader
        title="Monetização"
        description="Fase 3.1: visão geral financeira e varredura de segurança somente leitura."
      />

      <Section title="Resumo" description={`Gateway: ${data.gateway.mode || "Sem dados"} · Gerado em ${fmtDate(data.generated_at)}`}>
        <div className="metric-grid compact-grid monetization-metric-grid">
          {data.metrics.map((metric) => (
            <div className="metric-card staff-metric-card" key={metric.label}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
              {metric.hint && <small>{metric.hint}</small>}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Varredura de segurança" description="Alertas de configuração e consistência antes de liberar ações de escrita.">
        <div className="security-note-box">
          <ShieldCheck size={18} />
          <div>
            <strong>Modo seguro da Fase 3.1</strong>
            <p>Esta tela não altera pagamentos, planos, cupons, licenças ou cargos. Ela também não exibe QR Code PIX, link de checkout, dados do pagador ou secrets.</p>
          </div>
        </div>
        {data.alerts.length === 0 ? <EmptyState message="Nenhum alerta crítico encontrado." /> : (
          <div className="alert-list">
            {data.alerts.map((item) => (
              <div className="alert-row" key={`${item.severity}-${item.title}-${item.message}`}>
                <AlertTriangle size={16} />
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.message}</span>
                </div>
                <StatusBadge state={alertState(item.severity)}>{item.severity}</StatusBadge>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Pagamentos recentes" description="Somente leitura, sem dados sensíveis do PIX ou comprador.">
        {data.recent_payments.length === 0 ? <EmptyState message="Nenhum pagamento registrado ainda." /> : (
          <table className="data-table">
            <thead><tr><th>Plano</th><th>Valor</th><th>Status</th><th>Provider</th><th>Criado em</th><th>Pago em</th></tr></thead>
            <tbody>
              {data.recent_payments.map((payment) => (
                <tr key={payment.id}>
                  <td><strong>{payment.plan_name || "Plano removido"}</strong><small>{payment.user_id}</small></td>
                  <td>{payment.amount_label}</td>
                  <td><StatusBadge state={paymentState(payment.status)}>{paymentStatusLabel(payment.status)}</StatusBadge></td>
                  <td>{payment.provider}</td>
                  <td>{fmtDate(payment.created_at)}</td>
                  <td>{fmtDate(payment.paid_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Notas de segurança aplicadas">
        <div className="security-check-grid">
          {data.security_notes.map((note) => <span className="role-chip" key={note}>{note}</span>)}
        </div>
      </Section>
    </>
  );
}
