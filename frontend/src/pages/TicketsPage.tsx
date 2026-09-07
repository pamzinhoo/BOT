import { useQuery } from "@tanstack/react-query";
import { Search, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useShell } from "../components/AppShell";
import { Drawer, EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api } from "../lib/api";

type TicketRow = {
  id: string;
  label: string;
  channel_id: string;
  channel_name?: string | null;
  user_id: string;
  user_name?: string | null;
  category: string;
  status: string;
  staff_id?: string | null;
  staff_name?: string | null;
  created_at: string;
  closed_at?: string | null;
  last_activity_at?: string | null;
  has_evaluation: boolean;
};

type TicketList = { items: TicketRow[]; page: number; page_size: number; total: number; pages: number };
type StaffRow = { id: string; display_name: string };
type ClaimItem = { staff_id: string; staff_name?: string | null; claimed_at: string; unclaimed_at?: string | null };
type EvaluationItem = { rating: number; comment?: string | null; rated_by_id: string; rated_by_name?: string | null; created_at: string };
type TicketDetail = TicketRow & {
  first_response_at?: string | null;
  closed_by_id?: string | null;
  closed_by_name?: string | null;
  deleted_before_service: boolean;
  counts_for_stats: boolean;
  voice_channel_id?: string | null;
  voice_channel_name?: string | null;
  panel_id?: string | null;
  approval_status?: string | null;
  approval_reviewed_by?: string | null;
  approval_reviewed_by_name?: string | null;
  approval_reviewed_at?: string | null;
  claims: ClaimItem[];
  evaluation?: EvaluationItem | null;
};

const PAGE_SIZE = 25;

function fmtDate(value?: string | null) {
  return value ? new Date(value).toLocaleString("pt-BR") : "Sem dados";
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
  return name || (id ? `Usuário desconhecido` : "Sem dados");
}

function idHint(id?: string | null) {
  return id ? <small className="muted-text">{id}</small> : null;
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

export function TicketsPage() {
  const { guild, readiness, guildsError } = useShell();
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<string | null>(null);
  const page = Number(params.get("page") || "1");
  const status = params.get("status") || "active";
  const search = params.get("search") || "";
  const category = params.get("category") || "";
  const evaluated = params.get("evaluated") || "";
  const staffId = params.get("staff_id") || "";
  const createdFrom = params.get("created_from") || "";
  const createdTo = params.get("created_to") || "";

  const queryString = useMemo(() => {
    const next = new URLSearchParams();
    next.set("page", String(page));
    next.set("page_size", String(PAGE_SIZE));
    if (status) next.set("status", status);
    if (search.trim()) next.set("search", search.trim());
    if (category) next.set("category", category);
    if (evaluated) next.set("evaluated", evaluated);
    if (staffId) next.set("staff_id", staffId);
    if (createdFrom) next.set("created_from", `${createdFrom}T00:00:00`);
    if (createdTo) next.set("created_to", `${createdTo}T23:59:59`);
    return next.toString();
  }, [category, createdFrom, createdTo, evaluated, page, search, staffId, status]);

  const list = useQuery({
    queryKey: ["tickets", guild?.id, queryString],
    queryFn: () => api<TicketList>(`/guild/${guild!.id}/tickets?${queryString}`),
    enabled: Boolean(guild),
    refetchInterval: 20_000,
  });
  const staff = useQuery({
    queryKey: ["staff-options", guild?.id],
    queryFn: () => api<StaffRow[]>(`/guild/${guild!.id}/staff`),
    enabled: Boolean(guild),
  });
  const detail = useQuery({
    queryKey: ["ticket-detail", guild?.id, selected],
    queryFn: () => api<TicketDetail>(`/guild/${guild!.id}/tickets/${selected}`),
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
      <PageHeader title="Tickets" description="Investigue atendimento, responsáveis e avaliações registradas." />
      <Section title={`Tickets (${data?.total ?? 0})`} description="Filtros e paginação são processados pela API local.">
        <div className="filters-bar">
          <label className="search-input">
            <Search size={15} />
            <input value={search} onChange={(event) => updateParam("search", event.target.value)} placeholder="Buscar usuário, staff ou ID" />
          </label>
          <label>
            <span>Status</span>
            <select value={status} onChange={(event) => updateParam("status", event.target.value)}>
              <option value="active">Abertos</option>
              <option value="all">Todos</option>
              <option value="open">Aberto</option>
              <option value="claimed">Em atendimento</option>
              <option value="closed">Fechado</option>
              <option value="cancelled">Cancelado</option>
            </select>
          </label>
          <label>
            <span>Categoria</span>
            <select value={category} onChange={(event) => updateParam("category", event.target.value)}>
              <option value="">Todas</option>
              <option value="bug">Bug</option>
              <option value="denuncia">Denúncia</option>
              <option value="duvida">Dúvida</option>
              <option value="sugestao">Sugestão</option>
              <option value="parceria">Parceria</option>
              <option value="outro">Outro</option>
            </select>
          </label>
          <label>
            <span>Avaliação</span>
            <select value={evaluated} onChange={(event) => updateParam("evaluated", event.target.value)}>
              <option value="">Todas</option>
              <option value="true">Com avaliação</option>
              <option value="false">Sem avaliação</option>
            </select>
          </label>
          <label>
            <span>Responsável</span>
            <select value={staffId} onChange={(event) => updateParam("staff_id", event.target.value)}>
              <option value="">Todos</option>
              <option value="unassigned">Sem responsável</option>
              {staff.data?.map((row) => <option value={row.id} key={row.id}>{row.display_name}</option>)}
            </select>
          </label>
          <label>
            <span>De</span>
            <input type="date" value={createdFrom} onChange={(event) => updateParam("created_from", event.target.value)} />
          </label>
          <label>
            <span>Até</span>
            <input type="date" value={createdTo} onChange={(event) => updateParam("created_to", event.target.value)} />
          </label>
          <SlidersHorizontal size={16} className="filters-icon" />
        </div>
        {data?.items.length === 0 ? <EmptyState message="Nenhum ticket encontrado para os filtros atuais." /> : (
          <>
            <table className="data-table interactive-table">
              <thead><tr><th>Ticket</th><th>Usuário</th><th>Categoria</th><th>Status</th><th>Responsável</th><th>Criado em</th><th>Última atividade</th></tr></thead>
              <tbody>
                {data?.items.map((ticket) => (
                  <tr key={ticket.id} onClick={() => setSelected(ticket.id)}>
                    <td><strong>{ticket.label}</strong><small>{ticket.id.slice(0, 8)}</small></td>
                    <td>{userLabel(ticket.user_name, ticket.user_id)}{!ticket.user_name && idHint(ticket.user_id)}</td>
                    <td>{cleanCategory(ticket.category)}</td>
                    <td><StatusBadge state={badgeState(ticket.status)}>{labelStatus(ticket.status)}</StatusBadge></td>
                    <td>{ticket.staff_name || "Sem responsável"}</td>
                    <td>{fmtDate(ticket.created_at)}</td>
                    <td>{fmtDate(ticket.last_activity_at)}</td>
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

      <Drawer title={detail.data?.label || "Ticket"} subtitle={detail.data ? labelStatus(detail.data.status) : undefined} open={Boolean(selected)} onClose={() => setSelected(null)}>
        {detail.isLoading && <LoadingState />}
        {detail.error && <ErrorState message={(detail.error as Error).message} />}
        {detail.data && (
          <div className="detail-stack">
            <section>
              <h3>Visão geral</h3>
              <DetailRow label="Usuário" value={userLabel(detail.data.user_name, detail.data.user_id)} hint={idHint(detail.data.user_id)} />
              <DetailRow label="Categoria" value={cleanCategory(detail.data.category)} />
              <DetailRow label="Canal" value={detail.data.channel_name ? `#${detail.data.channel_name}` : "Canal não encontrado"} hint={idHint(detail.data.channel_id)} />
              <DetailRow label="Status" value={<StatusBadge state={badgeState(detail.data.status)}>{labelStatus(detail.data.status)}</StatusBadge>} />
              <DetailRow label="Responsável" value={detail.data.staff_name || "Sem responsável"} hint={idHint(detail.data.staff_id)} />
              <DetailRow label="Criado em" value={fmtDate(detail.data.created_at)} />
              <DetailRow label="Primeira resposta" value={detail.data.first_response_at ? fmtDate(detail.data.first_response_at) : undefined} />
              <DetailRow label="Fechado em" value={detail.data.closed_at ? fmtDate(detail.data.closed_at) : undefined} />
            </section>
            {detail.data.claims.length > 0 && (
              <section>
                <h3>Atendimento</h3>
                <div className="timeline-list">
                  {detail.data.claims.map((claim) => (
                    <div className="timeline-item" key={`${claim.staff_id}-${claim.claimed_at}`}>
                      <strong>{claim.staff_name || "Staff desconhecido"}</strong>
                      <span>Assumiu em {fmtDate(claim.claimed_at)}{claim.unclaimed_at ? ` e liberou em ${fmtDate(claim.unclaimed_at)}` : ""}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
            {detail.data.evaluation && (
              <section>
                <h3>Avaliação</h3>
                <DetailRow label="Nota" value={`${detail.data.evaluation.rating}/5`} />
                <DetailRow label="Comentário" value={detail.data.evaluation.comment || "Sem comentário"} />
                <DetailRow label="Avaliado por" value={userLabel(detail.data.evaluation.rated_by_name, detail.data.evaluation.rated_by_id)} hint={idHint(detail.data.evaluation.rated_by_id)} />
                <DetailRow label="Data" value={fmtDate(detail.data.evaluation.created_at)} />
              </section>
            )}
            {(detail.data.closed_at || detail.data.closed_by_id) && (
              <section>
                <h3>Fechamento</h3>
                <DetailRow label="Quem fechou" value={userLabel(detail.data.closed_by_name, detail.data.closed_by_id)} hint={idHint(detail.data.closed_by_id)} />
                <DetailRow label="Data" value={fmtDate(detail.data.closed_at)} />
              </section>
            )}
            <details className="technical-details">
              <summary>Metadados</summary>
              <DetailRow label="Ticket ID" value={detail.data.id} />
              <DetailRow label="Canal ID" value={detail.data.channel_id} />
              <DetailRow label="Panel ID" value={detail.data.panel_id} />
              <DetailRow label="Status de aprovação" value={detail.data.approval_status} />
              <DetailRow label="Voz" value={detail.data.voice_channel_name || detail.data.voice_channel_id} />
              <DetailRow label="Conta para estatísticas" value={detail.data.counts_for_stats ? "Sim" : "Não"} />
              <DetailRow label="Excluído antes do atendimento" value={detail.data.deleted_before_service ? "Sim" : "Não"} />
            </details>
          </div>
        )}
      </Drawer>
    </>
  );
}
