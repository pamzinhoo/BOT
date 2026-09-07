import { useQuery } from "@tanstack/react-query";
import { useShell } from "../components/AppShell";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api } from "../lib/api";

type Panels = { ticket_panels: { id: string; name: string; key: string; enabled: boolean; published: boolean }[]; groups: { id: string; name: string; published: boolean }[] };

export function PanelsPage() {
  const { guild, readiness, guildsError } = useShell();
  const { data, isLoading, error } = useQuery({ queryKey: ["panels", guild?.id], queryFn: () => api<Panels>(`/guild/${guild!.id}/panels`), enabled: Boolean(guild) });
  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={(error as Error).message} />;
  return (
    <>
      <PageHeader title="Paineis" description="Paineis Discord existentes e combos publicados." />
      <Section title="Paineis de tickets">
        {data?.ticket_panels.length === 0 ? <EmptyState message="Nenhum painel criado." /> : (
          <div className="entity-grid">{data?.ticket_panels.map((panel) => <div className="entity" key={panel.id}><strong>{panel.name}</strong><span>{panel.key}</span><StatusBadge state={panel.enabled ? "online" : "offline"}>{panel.enabled ? "Ativo" : "Inativo"}</StatusBadge><small>{panel.published ? "Publicado" : "Nao publicado"}</small></div>)}</div>
        )}
      </Section>
      <Section title="Combos">
        {data?.groups.length === 0 ? <EmptyState message="Nenhum combo criado." /> : (
          <div className="entity-grid">{data?.groups.map((group) => <div className="entity" key={group.id}><strong>{group.name}</strong><span>{group.published ? "Publicado" : "Nao publicado"}</span></div>)}</div>
        )}
      </Section>
    </>
  );
}
