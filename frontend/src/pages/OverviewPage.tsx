import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowRight, Database, Server, Settings, Ticket, Trophy, Zap } from "lucide-react";
import { Link } from "react-router-dom";
import { useShell } from "../components/AppShell";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api } from "../lib/api";

type Overview = {
  guild: { id: string; name: string } | null;
  bot: { connected: boolean; user?: string | null; latency_ms: number; uptime_seconds: number };
  metrics: { label: string; value: number | string }[];
  activity: { id: string; title: string; category: string; created_at: string; actor?: string | null; target?: string | null }[];
  health: { name: string; status: "online" | "offline" | "degraded"; detail: string }[];
};

export function OverviewPage() {
  const { guild, readiness, guildsError } = useShell();
  const { data, isLoading, error } = useQuery({
    queryKey: ["overview", guild?.id],
    queryFn: () => api<Overview>(`/overview${guild ? `?guild_id=${guild.id}` : ""}`),
    refetchInterval: 20_000,
  });

  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return <EmptyState message="Sem dados para exibir." />;

  return (
    <>
      <PageHeader
        title="Limerence"
        description="Visão geral do sistema"
        action={<StatusBadge state={data.bot.connected ? "online" : "offline"}>{data.bot.connected ? "Online" : "Offline"} · {data.bot.latency_ms} ms</StatusBadge>}
      />
      <div className="metric-grid">
        {data.metrics.map((metric) => (
          <div className="metric" key={metric.label}>
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
          </div>
        ))}
      </div>
      <div className="two-column">
        <Section title="Atividade" description="Eventos recentes gravados pela auditoria.">
          <div className="activity-list">
            {data.activity.length === 0 && <EmptyState message="Nenhuma atividade recente." />}
            {data.activity.map((item) => (
              <div className="activity-row" key={item.id}>
                <Activity size={16} />
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.category} · {item.actor || "Sistema"}</span>
                </div>
                <time>{new Date(item.created_at).toLocaleString("pt-BR")}</time>
              </div>
            ))}
          </div>
        </Section>
        <Section title="Saúde do sistema" description="Estado local sem expor segredos.">
          <div className="health-list">
            {data.health.map((item) => (
              <div className="health-row" key={item.name}>
                {item.name === "Database" ? <Database size={18} /> : item.name === "API" ? <Server size={18} /> : <Zap size={18} />}
                <div>
                  <strong>{item.name}</strong>
                  <span>{item.detail}</span>
                </div>
                <StatusBadge state={item.status}>{item.status}</StatusBadge>
              </div>
            ))}
          </div>
        </Section>
      </div>
      <Section title="Ações rápidas" description="Atalhos para manutenção diária.">
        <div className="quick-actions">
          <Link to="/tickets"><Ticket size={16} />Ver tickets<ArrowRight size={15} /></Link>
          <Link to="/settings/tickets"><Settings size={16} />Configurar tickets<ArrowRight size={15} /></Link>
          <Link to="/settings/ranking"><Trophy size={16} />Ajustar ranking<ArrowRight size={15} /></Link>
        </div>
      </Section>
    </>
  );
}
