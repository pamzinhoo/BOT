import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useShell } from "../components/AppShell";
import { Drawer, EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api } from "../lib/api";

type Staff = {
  id: string;
  discord_user_id: string;
  display_name: string;
  tickets: number;
  average_rating: number;
  streak: number;
  last_activity_at?: string | null;
};

type StaffTicket = {
  id: string;
  label: string;
  channel_id: string;
  channel_name?: string | null;
  user_id: string;
  user_name?: string | null;
  category: string;
  status: string;
  created_at: string;
  closed_at?: string | null;
  first_response_at?: string | null;
};

type StaffEvaluation = {
  ticket_id: string;
  rating: number;
  comment?: string | null;
  rated_by_id: string;
  rated_by_name?: string | null;
  created_at: string;
};

type StaffActivity = {
  id: string;
  action: string;
  created_at: string;
  ticket_id?: string | null;
  ticket_label?: string | null;
  detail?: string | null;
};

type StaffDetail = Staff & {
  active: boolean;
  metrics: Record<string, number | string | null>;
  current_tickets: StaffTicket[];
  recent_tickets: StaffTicket[];
  evaluations: StaffEvaluation[];
  history: StaffActivity[];
};

function fmtDate(value?: string | null) {
  return value ? new Date(value).toLocaleString("pt-BR") : "Sem dados";
}

function fmtSeconds(value?: number | string | null) {
  if (value === null || value === undefined || value === "") return "Sem dados";
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "Sem dados";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return rest ? `${minutes}min ${rest}s` : `${minutes}min`;
}

function labelStatus(value: string) {
  return { open: "Aberto", claimed: "Em atendimento", closed: "Fechado", cancelled: "Cancelado" }[value] || value;
}

function badgeState(value: string) {
  if (value === "open" || value === "claimed") return "online";
  if (value === "closed") return "neutral";
  return "degraded";
}

function cleanCategory(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function userLabel(name?: string | null, id?: string | null) {
  return name || (id ? "Usuário desconhecido" : "Sem dados");
}

function MetricCard({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="metric-card staff-metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}

function TicketMiniList({ items, empty }: { items: StaffTicket[]; empty: string }) {
  if (!items.length) return <EmptyState message={empty} />;
  return (
    <div className="staff-mini-list">
      {items.map((ticket) => (
        <div className="staff-mini-item" key={ticket.id}>
          <div>
            <strong>{ticket.label}</strong>
            <small>{userLabel(ticket.user_name, ticket.user_id)} · {cleanCategory(ticket.category)}</small>
          </div>
          <StatusBadge state={badgeState(ticket.status)}>{labelStatus(ticket.status)}</StatusBadge>
          <small>{fmtDate(ticket.created_at)}</small>
        </div>
      ))}
    </div>
  );
}

export function StaffPage() {
  const { guild, readiness, guildsError } = useShell();
  const [selected, setSelected] = useState<string | null>(null);
  const { data = [], isLoading, error } = useQuery({
    queryKey: ["staff", guild?.id],
    queryFn: () => api<Staff[]>(`/guild/${guild!.id}/staff`),
    enabled: Boolean(guild),
  });
  const detail = useQuery({
    queryKey: ["staff-detail", guild?.id, selected],
    queryFn: () => api<StaffDetail>(`/guild/${guild!.id}/staff/${selected}`),
    enabled: Boolean(guild && selected),
  });

  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={(error as Error).message} />;

  const profile = detail.data;
  const metrics = profile?.metrics || {};

  return (
    <>
      <PageHeader title="Staff" description="Perfil completo, tickets atuais, histórico, avaliações e métricas reais de atendimento." />
      <Section title="Equipe" description="Clique em um staff para abrir o perfil operacional completo.">
        {data.length === 0 ? <EmptyState message="Nenhum staff registrado." /> : (
          <table className="data-table interactive-table">
            <thead><tr><th>Staff</th><th>Tickets</th><th>Nota média</th><th>Streak</th><th>Última atividade</th></tr></thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.id} onClick={() => setSelected(row.id)}>
                  <td><strong>{row.display_name}</strong><small>{row.discord_user_id}</small></td>
                  <td>{row.tickets}</td>
                  <td>{row.average_rating.toFixed(2)}</td>
                  <td>{row.streak} dias</td>
                  <td>{fmtDate(row.last_activity_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Drawer title={profile?.display_name || "Staff"} subtitle={profile?.active ? "Ativo" : "Inativo"} open={Boolean(selected)} onClose={() => setSelected(null)}>
        {detail.isLoading && <LoadingState />}
        {detail.error && <ErrorState message={(detail.error as Error).message} />}
        {profile && (
          <div className="detail-stack staff-profile-drawer">
            <section>
              <h3>Resumo</h3>
              <div className="metric-grid compact-grid">
                <MetricCard label="Assumidos" value={Number(metrics.tickets_assumidos || 0)} />
                <MetricCard label="Fechados" value={Number(metrics.tickets_fechados || 0)} />
                <MetricCard label="Cancelados" value={Number(metrics.tickets_cancelados || 0)} />
                <MetricCard label="Nota média" value={Number(metrics.avaliacao_media || 0).toFixed(2)} hint={`${Number(metrics.avaliacoes_count || 0)} avaliação(ões)`} />
                <MetricCard label="Streak atual" value={`${Number(metrics.current_streak_days || 0)} dias`} />
                <MetricCard label="Melhor streak" value={`${Number(metrics.best_streak_days || 0)} dias`} />
              </div>
            </section>
            <section>
              <h3>Tempo e produtividade</h3>
              <div className="metric-grid compact-grid">
                <MetricCard label="1ª resposta média" value={fmtSeconds(metrics.tempo_medio_primeira_resposta_s)} />
                <MetricCard label="Fechamento médio" value={fmtSeconds(metrics.tempo_medio_fechamento_s)} />
                <MetricCard label="Dias ativos" value={Number(metrics.total_active_days || 0)} />
                <MetricCard label="Tickets hoje" value={Number(metrics.current_day_ticket_count || 0)} />
                <MetricCard label="Melhor dia" value={Number(metrics.best_day_ticket_count || 0)} />
                <MetricCard label="Sequência perfeita" value={Number(metrics.current_perfect_streak || 0)} />
              </div>
            </section>
            <section>
              <h3>Tickets atuais</h3>
              <TicketMiniList items={profile.current_tickets} empty="Este staff não está com ticket ativo agora." />
            </section>
            <section>
              <h3>Últimos tickets</h3>
              <TicketMiniList items={profile.recent_tickets} empty="Nenhum ticket encontrado para este staff." />
            </section>
            <section>
              <h3>Avaliações recebidas</h3>
              {!profile.evaluations.length ? <EmptyState message="Nenhuma avaliação recebida." /> : (
                <div className="staff-mini-list">
                  {profile.evaluations.map((item) => (
                    <div className="staff-mini-item" key={`${item.ticket_id}-${item.created_at}`}>
                      <div>
                        <strong>{item.rating}/5</strong>
                        <small>{item.comment || "Sem comentário"}</small>
                      </div>
                      <small>{userLabel(item.rated_by_name, item.rated_by_id)}</small>
                      <small>{fmtDate(item.created_at)}</small>
                    </div>
                  ))}
                </div>
              )}
            </section>
            <section>
              <h3>Histórico de atendimento</h3>
              {!profile.history.length ? <EmptyState message="Nenhum histórico registrado." /> : (
                <div className="timeline-list">
                  {profile.history.map((item) => (
                    <div className="timeline-item" key={item.id}>
                      <strong>{item.action}</strong>
                      <span>{item.ticket_label || item.ticket_id} · {fmtDate(item.created_at)}{item.detail ? ` · liberou em ${fmtDate(item.detail)}` : ""}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>
            <details className="technical-details">
              <summary>Metadados</summary>
              <div className="detail-row"><span>Staff ID</span><div><strong>{profile.id}</strong></div></div>
              <div className="detail-row"><span>Discord ID</span><div><strong>{profile.discord_user_id}</strong></div></div>
              <div className="detail-row"><span>Primeiro ticket</span><div><strong>{fmtDate(String(metrics.primeiro_ticket_at || ""))}</strong></div></div>
              <div className="detail-row"><span>Último ticket</span><div><strong>{fmtDate(String(metrics.ultimo_ticket_at || ""))}</strong></div></div>
              <div className="detail-row"><span>Última nota ruim</span><div><strong>{fmtDate(String(metrics.last_bad_rating_at || ""))}</strong></div></div>
            </details>
          </div>
        )}
      </Drawer>
    </>
  );
}
