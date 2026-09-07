import { useQuery } from "@tanstack/react-query";
import { useShell } from "../components/AppShell";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section } from "../components/Ui";
import { api } from "../lib/api";

type Staff = { id: string; discord_user_id: string; display_name: string; tickets: number; average_rating: number; streak: number; last_activity_at?: string | null };

export function StaffPage() {
  const { guild, readiness, guildsError } = useShell();
  const { data = [], isLoading, error } = useQuery({ queryKey: ["staff", guild?.id], queryFn: () => api<Staff[]>(`/guild/${guild!.id}/staff`), enabled: Boolean(guild) });
  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={(error as Error).message} />;
  return (
    <>
      <PageHeader title="Staff" description="Metricas reais de atendimento e avaliacao." />
      <Section title="Equipe">
        {data.length === 0 ? <EmptyState message="Nenhum staff registrado." /> : (
          <table className="data-table">
            <thead><tr><th>Staff</th><th>Tickets</th><th>Nota media</th><th>Streak</th><th>Ultima atividade</th></tr></thead>
            <tbody>{data.map((row) => <tr key={row.id}><td>{row.display_name}</td><td>{row.tickets}</td><td>{row.average_rating.toFixed(2)}</td><td>{row.streak} dias</td><td>{row.last_activity_at ? new Date(row.last_activity_at).toLocaleString("pt-BR") : "Sem dados"}</td></tr>)}</tbody>
          </table>
        )}
      </Section>
    </>
  );
}
