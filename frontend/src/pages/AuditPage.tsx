import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useShell } from "../components/AppShell";
import { Drawer, EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api } from "../lib/api";

type AuditRow = { id: string; title: string; category: string; actor?: string | null; target?: string | null; created_at: string };
type AuditList = { items: AuditRow[]; total: number; page: number; page_size: number; pages: number };
type AuditDetail = {
  id: string;
  action: string;
  category: string;
  created_at: string;
  executor_id?: string | null;
  executor_name?: string | null;
  target_id?: string | null;
  target_name?: string | null;
  reason?: string | null;
  config_category?: string | null;
  config_name?: string | null;
  old_value?: string | null;
  new_value?: string | null;
  details: Record<string, unknown>;
};

const PAGE_SIZE = 50;

function fmtDate(value?: string | null) {
  return value ? new Date(value).toLocaleString("pt-BR") : "Sem dados";
}

function categoryLabel(value: string) {
  return value.replace(/_/g, " ");
}

function DetailRow({ label, value, hint }: { label: string; value?: React.ReactNode; hint?: React.ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="detail-row">
      <span>{label}</span>
      <div>
        <strong>{value}</strong>
        {hint}
      </div>
    </div>
  );
}

function idHint(id?: string | null) {
  return id ? <small className="muted-text">{id}</small> : null;
}

export function AuditPage() {
  const { guild, readiness, guildsError } = useShell();
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<string | null>(null);
  const page = Number(params.get("page") || "1");
  const category = params.get("category") || "";
  const search = params.get("search") || "";
  const action = params.get("action") || "";
  const since = params.get("since") || "";

  const queryString = useMemo(() => {
    const next = new URLSearchParams();
    next.set("page", String(page));
    next.set("page_size", String(PAGE_SIZE));
    if (category) next.set("category", category);
    if (search.trim()) next.set("search", search.trim());
    if (action.trim()) next.set("action", action.trim());
    if (since) next.set("since", `${since}T00:00:00`);
    return next.toString();
  }, [action, category, page, search, since]);

  const list = useQuery({
    queryKey: ["audit", guild?.id, queryString],
    queryFn: () => api<AuditList>(`/guild/${guild!.id}/audit?${queryString}`),
    enabled: Boolean(guild),
    refetchInterval: 30_000,
  });
  const detail = useQuery({
    queryKey: ["audit-detail", guild?.id, selected],
    queryFn: () => api<AuditDetail>(`/guild/${guild!.id}/audit/${selected}`),
    enabled: Boolean(guild && selected),
  });

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.set("page", "1");
    setParams(next);
  };

  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (list.isLoading) return <LoadingState />;
  if (list.error) return <ErrorState message={(list.error as Error).message} />;

  const data = list.data;
  return (
    <>
      <PageHeader title="Auditoria" description="Investigue eventos recentes do servidor selecionado." />
      <Section title={`Eventos (${data?.total ?? 0})`} description="Busca, categoria e ação são filtradas pela API local.">
        <div className="filters-bar">
          <label className="search-input">
            <Search size={15} />
            <input value={search} onChange={(event) => updateParam("search", event.target.value)} placeholder="Buscar ação, ator, alvo ou motivo" />
          </label>
          <label>
            <span>Categoria</span>
            <select value={category} onChange={(event) => updateParam("category", event.target.value)}>
              <option value="">Todas</option>
              <option value="tickets">Tickets</option>
              <option value="server_config">Configurações</option>
              <option value="ban">Ban</option>
              <option value="kick">Kick</option>
              <option value="timeout">Timeout</option>
              <option value="message_delete">Mensagens excluídas</option>
              <option value="message_edit">Mensagens editadas</option>
              <option value="role_update">Cargos</option>
              <option value="channel_update">Canais</option>
              <option value="verification">Verificação</option>
              <option value="payment">Pagamentos</option>
            </select>
          </label>
          <label>
            <span>Ação</span>
            <input value={action} onChange={(event) => updateParam("action", event.target.value)} placeholder="Ex.: Configuração alterada" />
          </label>
          <label>
            <span>Desde</span>
            <input type="date" value={since} onChange={(event) => updateParam("since", event.target.value)} />
          </label>
        </div>
        {data?.items.length === 0 ? <EmptyState message="Nenhum evento encontrado para os filtros atuais." /> : (
          <>
            <table className="data-table interactive-table">
              <thead><tr><th>Evento</th><th>Executor</th><th>Alvo</th><th>Categoria</th><th>Data</th></tr></thead>
              <tbody>
                {data?.items.map((item) => (
                  <tr key={item.id} onClick={() => setSelected(item.id)}>
                    <td><strong>{item.title}</strong><small>{item.id.slice(0, 8)}</small></td>
                    <td>{item.actor || "Sistema"}</td>
                    <td>{item.target || "Sem alvo"}</td>
                    <td><StatusBadge state="neutral">{categoryLabel(item.category)}</StatusBadge></td>
                    <td>{fmtDate(item.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="pagination">
              <span>Página {data?.page ?? 1} de {data?.pages || 1}</span>
              <button className="button ghost" disabled={(data?.page ?? 1) <= 1} onClick={() => updateParam("page", String(page - 1))}>Anterior</button>
              <button className="button ghost" disabled={(data?.page ?? 1) >= (data?.pages || 1)} onClick={() => updateParam("page", String(page + 1))}>Próxima</button>
            </div>
          </>
        )}
      </Section>

      <Drawer title={detail.data?.action || "Evento"} subtitle={detail.data ? categoryLabel(detail.data.category) : undefined} open={Boolean(selected)} onClose={() => setSelected(null)}>
        {detail.isLoading && <LoadingState />}
        {detail.error && <ErrorState message={(detail.error as Error).message} />}
        {detail.data && (
          <div className="detail-stack">
            <section>
              <h3>Evento</h3>
              <DetailRow label="Ação" value={detail.data.action} />
              <DetailRow label="Categoria" value={categoryLabel(detail.data.category)} />
              <DetailRow label="Data" value={fmtDate(detail.data.created_at)} />
            </section>
            <section>
              <h3>Ator</h3>
              <DetailRow label="Usuário" value={detail.data.executor_name || "Desconhecido"} hint={idHint(detail.data.executor_id)} />
            </section>
            {(detail.data.target_name || detail.data.target_id) && (
              <section>
                <h3>Alvo</h3>
                <DetailRow label="Registro" value={detail.data.target_name || "Desconhecido"} hint={idHint(detail.data.target_id)} />
              </section>
            )}
            {(detail.data.reason || detail.data.config_category || detail.data.config_name) && (
              <section>
                <h3>Contexto</h3>
                <DetailRow label="Motivo" value={detail.data.reason} />
                <DetailRow label="Área" value={detail.data.config_category} />
                <DetailRow label="Configuração" value={detail.data.config_name} />
              </section>
            )}
            {(detail.data.old_value || detail.data.new_value) && (
              <section>
                <h3>Alterações</h3>
                <DetailRow label="Antes" value={detail.data.old_value || "Sem valor"} />
                <DetailRow label="Depois" value={detail.data.new_value || "Sem valor"} />
              </section>
            )}
            {Object.keys(detail.data.details || {}).length > 0 && (
              <details className="technical-details">
                <summary>Dados técnicos</summary>
                <pre>{JSON.stringify(detail.data.details, null, 2)}</pre>
              </details>
            )}
          </div>
        )}
      </Drawer>
    </>
  );
}
