import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EyeOff, History, Pencil, Plus, Save } from "lucide-react";
import { useState } from "react";
import { api, DiscordOptions } from "../lib/api";
import { EmptyState, ErrorState, LoadingState, Section, StatusBadge } from "./Ui";

type Code = {
  id: string;
  code: string;
  reward_type: "message" | "role";
  role_id: string | null;
  role_duration_seconds: number | null;
  message: string;
  delivery: "channel" | "dm";
  starts_at: string | null;
  expires_at: string | null;
  max_uses: number | null;
  uses: number;
  active: boolean;
  temporary_role_ack: boolean;
};

type Redemption = {
  id: string;
  user_id: string;
  status: string;
  error: string | null;
  created_at: string;
  delivered_at: string | null;
  role_expires_at: string | null;
  role_status: string | null;
  role_error: string | null;
  notification_status: string | null;
};

type Draft = {
  generate: boolean;
  code: string;
  reward_type: "message" | "role";
  role_id: string;
  duration_hours: string;
  temporary_role_ack: boolean;
  message: string;
  delivery: "channel" | "dm";
  starts_at: string;
  expires_at: string;
  max_uses: string;
  active: boolean;
};

const emptyDraft: Draft = {
  generate: true, code: "", reward_type: "message", role_id: "", duration_hours: "",
  temporary_role_ack: false, message: "", delivery: "channel", starts_at: "", expires_at: "",
  max_uses: "", active: true,
};

function inputDate(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function displayDate(value: string | null) {
  return value ? new Date(value).toLocaleString("pt-BR") : "Sem limite";
}

function statusLabel(value: string) {
  return ({ pending: "Pendente", delivering: "Em entrega", delivered: "Entregue", failed: "Falhou", uncertain: "Em revisão" } as Record<string, string>)[value] || value;
}

function notificationStatusLabel(value: string | null) {
  return ({ pending: "Mensagem pendente", sending: "Mensagem em envio", sent: "Mensagem enviada", uncertain: "Envio não confirmado" } as Record<string, string>)[value || ""] || "";
}

function roleStatusLabel(value: string | null) {
  if (!value) return "—";
  return ({ pending: "Pendente", active: "Ativo", removing: "Removendo", removed: "Removido", suspended: "Remoção suspensa" } as Record<string, string>)[value] || value;
}

function fromCode(item: Code): Draft {
  return {
    generate: false,
    code: item.code,
    reward_type: item.reward_type,
    role_id: item.role_id || "",
    duration_hours: item.role_duration_seconds ? String(item.role_duration_seconds / 3600) : "",
    temporary_role_ack: item.temporary_role_ack,
    message: item.message,
    delivery: item.delivery,
    starts_at: inputDate(item.starts_at),
    expires_at: inputDate(item.expires_at),
    max_uses: item.max_uses ? String(item.max_uses) : "",
    active: item.active,
  };
}

function payload(draft: Draft, creating: boolean) {
  const temporary = draft.reward_type === "role" && draft.duration_hours.trim() !== "";
  return {
    ...(creating ? { code: draft.generate ? null : draft.code.trim().toUpperCase() } : {}),
    reward_type: draft.reward_type,
    role_id: draft.reward_type === "role" && draft.role_id ? draft.role_id : null,
    role_duration_seconds: temporary ? Math.round(Number(draft.duration_hours) * 3600) : null,
    temporary_role_ack: temporary && draft.temporary_role_ack,
    message: draft.message,
    delivery: draft.delivery,
    starts_at: draft.starts_at ? new Date(draft.starts_at).toISOString() : null,
    expires_at: draft.expires_at ? new Date(draft.expires_at).toISOString() : null,
    max_uses: draft.max_uses ? Number(draft.max_uses) : null,
    active: draft.active,
  };
}

export function MonetizationRedemptionManager({ guildId }: { guildId: string }) {
  const client = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [newDraft, setNewDraft] = useState<Draft>(emptyDraft);
  const [editing, setEditing] = useState<Record<string, Draft>>({});
  const [historyId, setHistoryId] = useState<string | null>(null);
  const base = `/guild/${guildId}/monetization/redemption-codes`;
  const codes = useQuery({ queryKey: ["redemption-codes", guildId], queryFn: () => api<{ items: Code[] }>(base) });
  const options = useQuery({ queryKey: ["discord-options", guildId], queryFn: () => api<DiscordOptions>(`/guild/${guildId}/discord-options`), refetchInterval: 60_000 });
  const history = useQuery({ queryKey: ["redemption-history", guildId, historyId], queryFn: () => api<{ items: Redemption[] }>(`${base}/${historyId}/history`), enabled: Boolean(historyId) });
  const invalidate = () => {
    client.invalidateQueries({ queryKey: ["redemption-codes", guildId] });
    client.invalidateQueries({ queryKey: ["redemption-history", guildId] });
  };
  const create = useMutation({
    mutationFn: () => api<{ item: Code }>(base, { method: "POST", body: JSON.stringify(payload(newDraft, true)) }),
    onSuccess: () => { setCreating(false); setNewDraft(emptyDraft); invalidate(); },
  });
  const update = useMutation({
    mutationFn: ({ id, draft }: { id: string; draft: Draft }) => api<{ item: Code }>(`${base}/${id}`, { method: "PATCH", body: JSON.stringify(payload(draft, false)) }),
    onSuccess: (response) => {
      setEditing((current) => { const next = { ...current }; delete next[response.item.id]; return next; });
      invalidate();
    },
  });
  const toggle = useMutation({
    mutationFn: (item: Code) => api<{ item: Code }>(`${base}/${item.id}/toggle`, { method: "POST", body: JSON.stringify({ active: !item.active }) }),
    onSuccess: invalidate,
  });
  const busy = create.isPending || update.isPending || toggle.isPending;
  const error = create.error || update.error || toggle.error;

  return <Section title="Códigos de resgate" description="Um resgate por pessoa e código. Entrega privada pela loja ou por mensagem direta.">
    <div className="form-actions"><button className="button primary" onClick={() => setCreating((value) => !value)}><Plus size={16} />Novo código</button></div>
    {creating && <CodeForm draft={newDraft} roles={options.data?.roles || []} busy={busy} creating onChange={(patch) => setNewDraft((current) => ({ ...current, ...patch }))} onCancel={() => { setCreating(false); setNewDraft(emptyDraft); }} onSubmit={() => create.mutate()} />}
    {codes.isLoading ? <LoadingState message="Carregando códigos..." /> : codes.error ? <ErrorState message={(codes.error as Error).message} /> : codes.data?.items.length ?
      <div className="entity-grid">{codes.data.items.map((item) => {
        const draft = editing[item.id];
        const role = options.data?.roles.find((entry) => entry.id === item.role_id);
        return <div className="entity" key={item.id}>
          <div className="entity-title-row"><strong className="mono">{item.code}</strong><StatusBadge state={item.active ? "online" : "neutral"}>{item.active ? "Ativo" : "Inativo"}</StatusBadge></div>
          {!draft ? <>
            <span>{item.reward_type === "role" ? `Cargo: ${role?.name || item.role_id || "Ausente"}` : "Mensagem"}{item.role_duration_seconds ? ` · ${item.role_duration_seconds / 3600} hora(s)` : item.reward_type === "role" ? " · Permanente" : ""}</span>
            <small>{item.uses} uso(s){item.max_uses ? ` de ${item.max_uses}` : " · sem limite"} · {item.delivery === "dm" ? "DM" : "Resposta privada na loja"}</small>
            <small>Início: {displayDate(item.starts_at)} · Fim: {displayDate(item.expires_at)}</small>
            <div className="card-actions">
              <button className="button ghost" disabled={busy} onClick={() => setEditing((current) => ({ ...current, [item.id]: fromCode(item) }))}><Pencil size={15} />Editar</button>
              <button className="button ghost" disabled={busy} onClick={() => toggle.mutate(item)}><EyeOff size={15} />{item.active ? "Desativar" : "Ativar"}</button>
              <button className="button ghost" onClick={() => setHistoryId((current) => current === item.id ? null : item.id)}><History size={15} />Histórico</button>
            </div>
          </> : <CodeForm draft={draft} roles={options.data?.roles || []} busy={busy} onChange={(patch) => setEditing((current) => ({ ...current, [item.id]: { ...current[item.id], ...patch } }))} onCancel={() => setEditing((current) => { const next = { ...current }; delete next[item.id]; return next; })} onSubmit={() => update.mutate({ id: item.id, draft })} />}
          {historyId === item.id && <div><strong>Últimos resgates</strong>{history.isLoading ? <LoadingState message="Carregando histórico..." /> : history.error ? <ErrorState message={(history.error as Error).message} /> : history.data?.items.length ? <table className="data-table"><thead><tr><th>Usuário</th><th>Entrega</th><th>Cargo</th><th>Resgatado</th><th>Cargo até</th></tr></thead><tbody>{history.data.items.map((entry) => <tr key={entry.id}><td className="mono">{entry.user_id}</td><td>{statusLabel(entry.status)}<small>{notificationStatusLabel(entry.notification_status)}</small>{entry.error && <small>{entry.error}</small>}</td><td>{roleStatusLabel(entry.role_status)}{entry.role_error && <small>{entry.role_error}</small>}</td><td>{displayDate(entry.created_at)}</td><td>{displayDate(entry.role_expires_at)}</td></tr>)}</tbody></table> : <EmptyState message="Nenhum resgate registrado." />}</div>}
        </div>;
      })}</div> : <EmptyState message="Nenhum código cadastrado." />}
    {error && <p className="inline-warning">{(error as Error).message}</p>}
  </Section>;
}

function CodeForm({ draft, roles, busy, creating = false, onChange, onCancel, onSubmit }: {
  draft: Draft; roles: DiscordOptions["roles"]; busy: boolean; creating?: boolean;
  onChange: (patch: Partial<Draft>) => void; onCancel: () => void; onSubmit: () => void;
}) {
  const temporary = draft.reward_type === "role" && draft.duration_hours.trim() !== "";
  const validCode = !creating || draft.generate || /^(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9]{8}$/.test(draft.code);
  const validDuration = !temporary || (Number.isInteger(Number(draft.duration_hours) * 3600) && Number(draft.duration_hours) > 0);
  const validLimit = !draft.max_uses || (Number.isInteger(Number(draft.max_uses)) && Number(draft.max_uses) > 0);
  const validDates = !draft.starts_at || !draft.expires_at || new Date(draft.starts_at) < new Date(draft.expires_at);
  const valid = validCode && validDuration && validLimit && validDates && draft.message.trim() && (draft.reward_type === "message" || draft.role_id) && (!temporary || draft.temporary_role_ack);
  return <div className="dashboard-form compact-edit-form">
    <div className="form-row">
      <label>Código<input value={draft.code} disabled={!creating || draft.generate} maxLength={8} placeholder={draft.generate ? "Gerado ao salvar" : "AB12CD34"} onChange={(event) => onChange({ code: event.target.value.toUpperCase() })} /></label>
      {creating && <label className="checkbox-label"><input type="checkbox" checked={draft.generate} onChange={(event) => onChange({ generate: event.target.checked })} /> Gerar código</label>}
      <label>Recompensa<select value={draft.reward_type} onChange={(event) => onChange({ reward_type: event.target.value as Draft["reward_type"] })}><option value="message">Mensagem</option><option value="role">Cargo + mensagem</option></select></label>
    </div>
    {!draft.generate && creating && <small>Código: exatamente 8 caracteres, com pelo menos uma letra e um número.</small>}
    {draft.reward_type === "role" && <div className="form-row"><label>Cargo<select value={draft.role_id} onChange={(event) => onChange({ role_id: event.target.value, temporary_role_ack: false })}><option value="">Selecione</option>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label><label>Duração em horas<input type="number" min="0.5" step="0.5" value={draft.duration_hours} placeholder="Vazio = permanente" onChange={(event) => onChange({ duration_hours: event.target.value, temporary_role_ack: false })} /></label></div>}
    {temporary && <label className="checkbox-label"><input type="checkbox" checked={draft.temporary_role_ack} onChange={(event) => onChange({ temporary_role_ack: event.target.checked })} /> Entendo que, ao expirar, o cargo só será removido se não estiver protegido por outro recurso ou atribuição manual.</label>}
    {temporary && <small>O bot precisa das permissões Gerenciar cargos e Ver registro de auditoria para remover o cargo com segurança.</small>}
    {temporary && <small>Se não houver prova da atribuição ou o cargo mudar, a remoção automática será suspensa. O histórico mostrará o motivo. O bot não força a remoção.</small>}
    {draft.reward_type === "role" && <small>Cargos usados na loja ou em outros recursos também podem ser recompensas. Enquanto forem compartilhados, a expiração do resgate preserva o cargo.</small>}
    <label>Mensagem entregue<textarea rows={3} maxLength={1800} value={draft.message} onChange={(event) => onChange({ message: event.target.value })} placeholder="Sua recompensa foi liberada." /></label>
    <small>Campos disponíveis: {"{usuario}"}, {"{cargo}"} e {"{duracao}"}.</small>
    <div className="form-row"><label>Entrega<select value={draft.delivery} onChange={(event) => onChange({ delivery: event.target.value as Draft["delivery"] })}><option value="channel">Resposta privada na loja</option><option value="dm">Mensagem direta (DM)</option></select></label><label>Início<input type="datetime-local" value={draft.starts_at} onChange={(event) => onChange({ starts_at: event.target.value })} /></label><label>Fim<input type="datetime-local" value={draft.expires_at} onChange={(event) => onChange({ expires_at: event.target.value })} /></label></div>
    <div className="form-row"><label>Máximo de usos<input type="number" min="1" step="1" value={draft.max_uses} placeholder="Vazio = ilimitado" onChange={(event) => onChange({ max_uses: event.target.value })} /></label><label className="checkbox-label"><input type="checkbox" checked={draft.active} onChange={(event) => onChange({ active: event.target.checked })} /> Ativo</label></div>
    {!validDates && <p className="inline-warning">Fim precisa ser posterior ao início.</p>}
    <div className="form-actions"><button className="button ghost" disabled={busy} onClick={onCancel}>Cancelar</button><button className="button primary" disabled={busy || !valid} onClick={onSubmit}><Save size={15} />{creating ? "Criar código" : "Salvar alterações"}</button></div>
  </div>;
}
