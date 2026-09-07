import { useQuery } from "@tanstack/react-query";
import { useShell } from "../components/AppShell";
import { ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api } from "../lib/api";

type System = {
  bot: Record<string, unknown>;
  api: Record<string, unknown>;
  database: Record<string, unknown>;
  version: Record<string, unknown>;
};

export function SystemPage() {
  const { readiness } = useShell();
  const { data, isLoading, error } = useQuery({ queryKey: ["system"], queryFn: () => api<System>("/system"), refetchInterval: 20_000 });
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={(error as Error).message} />;
  const groups = data ? [["Bot", data.bot], ["API", data.api], ["Database", data.database], ["Versão", data.version]] as const : [];
  return (
    <>
      <PageHeader
        title="Sistema"
        description={
          readiness?.ready
            ? "Diagnóstico local sem expor credenciais."
            : readiness?.discord_ready
              ? "Discord conectado, carregando servidores."
              : "Conectando ao Discord."
        }
      />
      {groups.map(([title, rows]) => (
        <Section title={title} key={title}>
          <div className="kv-list">
            {Object.entries(rows).map(([key, value]) => (
              <div className="kv-row" key={key}>
                <span>{labelFor(key)}</span>
                {typeof value === "boolean" ? <StatusBadge state={value ? "online" : "offline"}>{value ? "sim" : "não"}</StatusBadge> : <strong>{formatValue(key, value)}</strong>}
              </div>
            ))}
          </div>
        </Section>
      ))}
    </>
  );
}

function labelFor(key: string) {
  return {
    connected: "Conectado",
    discord_ready: "Discord ready",
    guilds_loaded: "Servidores carregados",
    user: "Usuário",
    guilds: "Servidores",
    uptime_seconds: "Uptime",
    host: "Host",
    port: "Porta",
    environment: "Ambiente",
    latency_ms: "Latência",
    commit: "Commit",
    python: "Python",
    discord_py: "discord.py",
    platform: "Plataforma",
  }[key] || key.replace(/_/g, " ");
}

function formatValue(key: string, value: unknown) {
  if (value === null || value === undefined || value === "") return "Não disponível";
  if (key === "latency_ms") return `${value} ms`;
  if (key === "uptime_seconds") return `${value} s`;
  return String(value);
}
