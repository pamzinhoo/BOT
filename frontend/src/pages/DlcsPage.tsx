import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, EyeOff, Package, Pencil, Plus, ShieldAlert, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { useShell } from "../components/AppShell";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api, DiscordOptions, DlcAccessPayload, DlcItem, DlcMutationResponse, DlcsPayload } from "../lib/api";

type Draft = {
  kind: "free" | "paid";
  name: string;
  slug: string;
  description: string;
  price_reais: string;
  role_id: string;
};

const DEFAULT_DRAFT: Draft = {
  kind: "free",
  name: "",
  slug: "",
  description: "",
  price_reais: "",
  role_id: "",
};

export function DlcsPage() {
  const { guild, readiness, guildsError } = useShell();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(DEFAULT_DRAFT);
  const [editing, setEditing] = useState<Record<string, Partial<DlcItem & { price_reais: string }>>>({});
  const [selectedAccessId, setSelectedAccessId] = useState<string | null>(null);

  const dlcs = useQuery({
    queryKey: ["dlcs", guild?.id],
    queryFn: () => api<DlcsPayload>(`/guild/${guild!.id}/dlcs`),
    enabled: Boolean(guild),
    refetchInterval: 20_000,
  });
  const access = useQuery({
    queryKey: ["dlc-access", guild?.id, selectedAccessId],
    queryFn: () => api<DlcAccessPayload>(`/guild/${guild!.id}/dlcs/${selectedAccessId}/access`),
    enabled: Boolean(guild && selectedAccessId),
    refetchInterval: 20_000,
  });
  const options = useQuery({
    queryKey: ["discord-options", guild?.id],
    queryFn: () => api<DiscordOptions>(`/guild/${guild!.id}/discord-options`),
    enabled: Boolean(guild),
    refetchInterval: 60_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["dlcs", guild?.id] });
    queryClient.invalidateQueries({ queryKey: ["dlc-access", guild?.id] });
    queryClient.invalidateQueries({ queryKey: ["audit", guild?.id] });
  };

  const toggleAccess = (item: DlcItem) => {
    if (item.deleted) return;
    setSelectedAccessId((current) => current === item.id ? null : item.id);
  };

  const createMutation = useMutation({
    mutationFn: () => api<DlcMutationResponse>(`/guild/${guild!.id}/dlcs`, { method: "POST", body: JSON.stringify(draft) }),
    onSuccess: () => {
      setDraft(DEFAULT_DRAFT);
      setCreateOpen(false);
      invalidate();
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Record<string, unknown> }) => api<DlcMutationResponse>(`/guild/${guild!.id}/dlcs/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: (data) => {
      setEditing((current) => {
        const next = { ...current };
        delete next[data.item.id];
        return next;
      });
      invalidate();
    },
  });

  const disableMutation = useMutation({
    mutationFn: (id: string) => api<DlcMutationResponse>(`/guild/${guild!.id}/dlcs/${id}/disable`, { method: "POST" }),
    onSuccess: invalidate,
  });

  const items = dlcs.data?.items || [];
  const summary = useMemo(() => ({
    total: items.length,
    free: items.filter((item) => item.kind === "free").length,
    paid: items.filter((item) => item.kind === "paid").length,
    active: items.filter((item) => item.is_active && !item.deleted).length,
  }), [items]);

  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (dlcs.isLoading) return <LoadingState />;
  if (dlcs.error) return <ErrorState message={(dlcs.error as Error).message} />;

  return (
    <>
      <PageHeader
        title="DLCs"
        description="Crie e gerencie DLCs usando o DlcService real do bot. DLC grátis usa o cargo Verificado; DLC paga usa cargo exclusivo e plano de compra."
        action={<button className="button primary" onClick={() => setCreateOpen((value) => !value)}><Plus size={16} />Nova DLC</button>}
      />
      <div className="entity-grid compact-grid">
        <Metric title="Total" value={summary.total} />
        <Metric title="Grátis" value={summary.free} />
        <Metric title="Pagas" value={summary.paid} />
        <Metric title="Ativas" value={summary.active} />
      </div>
      {createOpen && (
        <Section title="Criar DLC" description="DLC grátis pode avisar o canal configurado de DLC gratuita. DLC paga atualiza o painel da loja.">
          <div className="dashboard-form">
            <div className="form-row">
              <label>Tipo<select value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value as Draft["kind"] })}>
                <option value="free">Grátis</option>
                <option value="paid">Paga</option>
              </select></label>
              <label>Nome<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} maxLength={150} /></label>
              <label>Slug<input value={draft.slug} onChange={(event) => setDraft({ ...draft, slug: slugify(event.target.value) })} maxLength={80} placeholder="fragmento-i-genesis" /></label>
            </div>
            <label>Descrição<textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={3} maxLength={1000} /></label>
            {draft.kind === "free" ? (
              <p className="inline-warning"><ShieldAlert size={14} /> DLC grátis libera para quem tiver o cargo Verificado configurado no servidor.</p>
            ) : (
              <div className="form-row">
                <label>Preço em reais<input value={draft.price_reais} onChange={(event) => setDraft({ ...draft, price_reais: event.target.value })} placeholder="5,99" /></label>
                <label>Cargo da DLC<select value={draft.role_id} onChange={(event) => setDraft({ ...draft, role_id: event.target.value })}>
                  <option value="">Escolha o cargo</option>
                  {options.data?.roles.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}
                </select></label>
              </div>
            )}
            <div className="form-actions">
              <button className="button ghost" onClick={() => { setDraft(DEFAULT_DRAFT); setCreateOpen(false); }}>Cancelar</button>
              <button className="button primary" disabled={createMutation.isPending} onClick={() => createMutation.mutate()}><Package size={16} />Criar DLC</button>
            </div>
            {createMutation.error && <p className="inline-warning">{(createMutation.error as Error).message}</p>}
          </div>
        </Section>
      )}
      <Section title="DLCs cadastradas" description="Clique em uma DLC paga para ver usuários com acesso. Editar aqui altera o catálogo real; desativar mantém histórico.">
        {items.length === 0 ? <EmptyState message="Nenhuma DLC cadastrada ainda." /> : (
          <div className="entity-grid dlc-grid">
            {items.map((item) => (
              <DlcCard
                key={item.id}
                item={item}
                roles={options.data?.roles || []}
                draft={editing[item.id]}
                busy={updateMutation.isPending || disableMutation.isPending}
                accessSelected={selectedAccessId === item.id}
                onCardAccess={() => item.kind === "paid" && toggleAccess(item)}
                onShowAccess={() => toggleAccess(item)}
                onEdit={(patch) => setEditing((current) => ({ ...current, [item.id]: { ...(current[item.id] || seedEdit(item)), ...patch } }))}
                onCancel={() => setEditing((current) => { const next = { ...current }; delete next[item.id]; return next; })}
                onSave={() => updateMutation.mutate({ id: item.id, payload: buildUpdatePayload(item, editing[item.id]) })}
                onToggle={() => updateMutation.mutate({ id: item.id, payload: { is_active: !item.is_active } })}
                onDisable={() => disableMutation.mutate(item.id)}
              />
            ))}
          </div>
        )}
        {(updateMutation.error || disableMutation.error) && <p className="inline-warning">{((updateMutation.error || disableMutation.error) as Error).message}</p>}
      </Section>

      {selectedAccessId && (
        <Section title="Usuários com acesso à DLC" description="Somente leitura: mostra licença registrada e/ou cargo atual no Discord.">
          {access.isLoading ? <LoadingState message="Carregando usuários da DLC..." /> : access.error ? <ErrorState message={(access.error as Error).message} /> : access.data ? (
            <div className="dlc-access-panel">
              <div className="entity-title-row">
                <div>
                  <strong>{access.data.product.name}</strong>
                  <small>{access.data.total} usuário(s) encontrado(s) · Cargo: {access.data.role_name || access.data.role_id || "sem cargo vinculado"}</small>
                </div>
                {access.data.role_missing && <StatusBadge state="offline">Cargo ausente</StatusBadge>}
              </div>
              {access.data.items.length === 0 ? <EmptyState message="Nenhum usuário com licença ou cargo desta DLC." /> : (
                <table className="data-table">
                  <thead><tr><th>Usuário</th><th>ID Discord</th><th>Origem</th><th>Status</th><th>Cargo agora</th><th>Ativou em</th></tr></thead>
                  <tbody>
                    {access.data.items.map((holder) => (
                      <tr key={holder.discord_id}>
                        <td><strong>{holder.discord_name || "Nome não resolvido"}</strong><small>{holder.player_id ? `Player ${holder.player_id}` : "Sem player vinculado"}</small></td>
                        <td className="mono">{holder.discord_id}</td>
                        <td>{accessSourceLabel(holder.source)}</td>
                        <td><StatusBadge state={holder.active ? "online" : "offline"}>{accessStatusLabel(holder.status)}</StatusBadge></td>
                        <td>{holder.has_role_now ? "Sim" : "Não"}</td>
                        <td>{fmtDate(holder.activated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="security-check-grid">
                {access.data.security_notes.map((note) => <span className="role-chip" key={note}>{note}</span>)}
              </div>
            </div>
          ) : <EmptyState message="Selecione uma DLC para ver os usuários." />}
        </Section>
      )}
    </>
  );
}

function Metric({ title, value }: { title: string; value: number }) {
  return <div className="entity metric-card"><span>{title}</span><strong>{value}</strong></div>;
}

function DlcCard({ item, roles, draft, busy, accessSelected, onCardAccess, onShowAccess, onEdit, onCancel, onSave, onToggle, onDisable }: {
  item: DlcItem;
  roles: DiscordOptions["roles"];
  draft?: Partial<DlcItem & { price_reais: string }>;
  busy: boolean;
  accessSelected: boolean;
  onCardAccess: () => void;
  onShowAccess: () => void;
  onEdit: (patch: Partial<DlcItem & { price_reais: string }>) => void;
  onCancel: () => void;
  onSave: () => void;
  onToggle: () => void;
  onDisable: () => void;
}) {
  const isEditing = Boolean(draft);
  const edit = draft || seedEdit(item);
  const cardClickable = item.kind === "paid" && !item.deleted && !isEditing;
  const stop = (event: React.MouseEvent) => event.stopPropagation();
  return (
    <div
      className={`entity dlc-card ${cardClickable ? "is-clickable" : ""}`}
      onClick={cardClickable ? onCardAccess : undefined}
      role={cardClickable ? "button" : undefined}
      tabIndex={cardClickable ? 0 : undefined}
      title={cardClickable ? "Clique para ver usuários com acesso" : undefined}
      onKeyDown={(event) => {
        if (cardClickable && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onCardAccess();
        }
      }}
    >
      <div className="entity-title-row">
        <strong>{item.name}</strong>
        <StatusBadge state={item.deleted ? "offline" : item.is_active ? "online" : "degraded"}>{item.deleted ? "Removida" : item.is_active ? "Ativa" : "Inativa"}</StatusBadge>
      </div>
      <span className="mono">{item.slug}</span>
      <span>{item.kind === "free" ? "DLC grátis" : "DLC paga"} · {item.price_label}</span>
      <span>Cargo: {item.role_missing ? "cargo removido" : item.role_name || item.role_id || "—"}</span>
      {item.description && !isEditing && <p>{item.description}</p>}
      {item.role_missing && <p className="inline-warning"><ShieldAlert size={14} /> Cargo vinculado não existe mais no servidor.</p>}
      {isEditing && (
        <div className="dashboard-form compact-edit-form" onClick={stop}>
          <label>Nome<input value={String(edit.name ?? "")} onChange={(event) => onEdit({ name: event.target.value })} maxLength={150} /></label>
          <label>Descrição<textarea value={String(edit.description ?? "")} onChange={(event) => onEdit({ description: event.target.value })} rows={3} maxLength={1000} /></label>
          {item.kind === "paid" ? (
            <div className="form-row">
              <label>Preço em reais<input value={String(edit.price_reais ?? "")} onChange={(event) => onEdit({ price_reais: event.target.value })} /></label>
              <label>Cargo<select value={String(edit.role_id ?? "")} onChange={(event) => onEdit({ role_id: event.target.value })}>
                <option value="">Manter/nenhum</option>
                {roles.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}
              </select></label>
            </div>
          ) : (
            <p className="inline-warning"><ShieldAlert size={14} /> DLC grátis só edita nome/descrição/status. Preço e cargo exclusivo são apenas para DLC paga.</p>
          )}
        </div>
      )}
      <div className="card-actions" onClick={stop}>
        {isEditing ? (
          <>
            <button className="button ghost" disabled={busy} onClick={onCancel}>Cancelar</button>
            <button className="button primary" disabled={busy} onClick={onSave}>Salvar</button>
          </>
        ) : (
          <button className="button ghost" disabled={busy || item.deleted} onClick={() => onEdit(seedEdit(item))}><Pencil size={15} />Editar</button>
        )}
        <button className="button ghost" disabled={busy || item.deleted} onClick={onShowAccess}><Users size={15} />{accessSelected ? "Ocultar usuários" : "Ver usuários"}</button>
        <button className="button ghost" disabled={busy || item.deleted} onClick={onToggle}>{item.is_active ? <EyeOff size={15} /> : <Package size={15} />}{item.is_active ? "Desativar" : "Ativar"}</button>
        <button className="button danger" disabled={busy || item.deleted} onClick={onDisable}><Download size={15} />Remover do catálogo</button>
      </div>
    </div>
  );
}

function seedEdit(item: DlcItem): Partial<DlcItem & { price_reais: string }> {
  return {
    name: item.name,
    description: item.description || "",
    role_id: item.role_id || "",
    price_reais: item.price_amount ? String((item.price_amount / 100).toFixed(2)).replace(".", ",") : "",
  };
}

function buildUpdatePayload(item: DlcItem, draft?: Partial<DlcItem & { price_reais: string }>): Record<string, unknown> {
  const edit = draft || seedEdit(item);
  const payload: Record<string, unknown> = {
    name: String(edit.name ?? ""),
    description: String(edit.description ?? ""),
  };
  if (item.kind !== "paid") {
    return payload;
  }
  const price = String(edit.price_reais ?? "").trim();
  if (price) payload.price_reais = price;
  const roleId = String(edit.role_id ?? "").trim();
  if (roleId) payload.role_id = roleId;
  return payload;
}

function fmtDate(value?: string | null) {
  return value ? new Date(value).toLocaleString("pt-BR") : "Sem dados";
}

function accessStatusLabel(value: string) {
  return {
    active: "Ativa",
    pending: "Pendente",
    revoked: "Revogada",
    expired: "Expirada",
    role_only: "Só cargo",
  }[value] || value;
}

function accessSourceLabel(value: string) {
  return value
    .replace("role_grant", "Cargo/licença")
    .replace("discord_role", "Cargo atual")
    .replace("purchase", "Compra")
    .replace("payment", "Pagamento")
    .replace("manual", "Manual");
}

function slugify(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}
