import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EyeOff, Pencil, Plus, Save } from "lucide-react";
import { useState } from "react";
import { EmptyState, ErrorState, LoadingState, Section, StatusBadge } from "./Ui";
import { api, DiscordOptions, MonetizationCouponListPayload, MonetizationCouponManageRow, MonetizationCouponMutationPayload, MonetizationCouponMutationResponse, MonetizationPlanListPayload } from "../lib/api";

type CouponDraft = {
  code: string;
  description: string;
  emoji: string;
  discount_type: "percentage" | "fixed";
  discount_value: string;
  active: boolean;
  starts_at: string;
  expires_at: string;
  max_global_uses: string;
  max_uses_per_user: string;
  required_role_id: string;
  allow_stack: boolean;
  billing_cycles: string[];
  allowed_plan_ids: string[];
};

const EMPTY_COUPON_DRAFT: CouponDraft = {
  code: "",
  description: "",
  emoji: "",
  discount_type: "percentage",
  discount_value: "10",
  active: true,
  starts_at: "",
  expires_at: "",
  max_global_uses: "",
  max_uses_per_user: "1",
  required_role_id: "",
  allow_stack: false,
  billing_cycles: [],
  allowed_plan_ids: [],
};

const CYCLES = [
  ["monthly", "Mensal"],
  ["yearly", "Anual"],
  ["one_time", "Único"],
] as const;

function inputDate(value?: string | null) {
  return value ? value.slice(0, 16) : "";
}

function optionalNumber(value: string) {
  const clean = value.trim();
  return clean ? Number(clean) : null;
}

function seedCouponDraft(coupon: MonetizationCouponManageRow): CouponDraft {
  return {
    code: coupon.code,
    description: coupon.description || "",
    emoji: coupon.emoji || "",
    discount_type: coupon.discount_type === "fixed" ? "fixed" : "percentage",
    discount_value: coupon.discount_type === "fixed" ? coupon.discount_value_reais || "" : String(coupon.discount_value),
    active: coupon.active,
    starts_at: inputDate(coupon.starts_at),
    expires_at: inputDate(coupon.expires_at),
    max_global_uses: coupon.max_global_uses ? String(coupon.max_global_uses) : "",
    max_uses_per_user: coupon.max_uses_per_user ? String(coupon.max_uses_per_user) : "",
    required_role_id: coupon.required_role_id || "",
    allow_stack: coupon.allow_stack,
    billing_cycles: coupon.billing_cycles,
    allowed_plan_ids: coupon.allowed_plan_ids,
  };
}

function buildCouponPayload(draft: CouponDraft): MonetizationCouponMutationPayload {
  return {
    code: draft.code,
    description: draft.description,
    emoji: draft.emoji,
    discount_type: draft.discount_type,
    discount_value: draft.discount_value,
    active: draft.active,
    starts_at: draft.starts_at,
    expires_at: draft.expires_at,
    max_global_uses: optionalNumber(draft.max_global_uses),
    max_uses_per_user: optionalNumber(draft.max_uses_per_user),
    required_role_id: draft.required_role_id,
    allow_stack: draft.allow_stack,
    billing_cycles: draft.billing_cycles,
    allowed_plan_ids: draft.allowed_plan_ids,
  };
}

function toggleList(value: string, list: string[]) {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

export function MonetizationCouponManager({ guildId }: { guildId: string }) {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [newCoupon, setNewCoupon] = useState<CouponDraft>(EMPTY_COUPON_DRAFT);
  const [editing, setEditing] = useState<Record<string, CouponDraft>>({});

  const coupons = useQuery({ queryKey: ["monetization-coupon-manage", guildId], queryFn: () => api<MonetizationCouponListPayload>(`/guild/${guildId}/monetization/coupons/manage`) });
  const plans = useQuery({ queryKey: ["monetization-plan-manage", guildId], queryFn: () => api<MonetizationPlanListPayload>(`/guild/${guildId}/monetization/plans/manage`) });
  const options = useQuery({ queryKey: ["discord-options", guildId], queryFn: () => api<DiscordOptions>(`/guild/${guildId}/discord-options`), refetchInterval: 60_000 });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["monetization", guildId] });
    queryClient.invalidateQueries({ queryKey: ["monetization-coupon-manage", guildId] });
    queryClient.invalidateQueries({ queryKey: ["audit", guildId] });
  };

  const createCoupon = useMutation({
    mutationFn: () => api<MonetizationCouponMutationResponse>(`/guild/${guildId}/monetization/coupons`, { method: "POST", body: JSON.stringify(buildCouponPayload(newCoupon)) }),
    onSuccess: () => { setNewCoupon(EMPTY_COUPON_DRAFT); setCreateOpen(false); invalidate(); },
  });
  const updateCoupon = useMutation({
    mutationFn: ({ id, draft }: { id: string; draft: CouponDraft }) => api<MonetizationCouponMutationResponse>(`/guild/${guildId}/monetization/coupons/${id}`, { method: "PATCH", body: JSON.stringify(buildCouponPayload(draft)) }),
    onSuccess: (response) => { setEditing((current) => { const next = { ...current }; delete next[response.item.id]; return next; }); invalidate(); },
  });
  const toggleCoupon = useMutation({
    mutationFn: (coupon: MonetizationCouponManageRow) => api<MonetizationCouponMutationResponse>(`/guild/${guildId}/monetization/coupons/${coupon.id}/toggle`, { method: "POST", body: JSON.stringify({ active: !coupon.active }) }),
    onSuccess: invalidate,
  });

  const busy = createCoupon.isPending || updateCoupon.isPending || toggleCoupon.isPending;
  const error = createCoupon.error || updateCoupon.error || toggleCoupon.error;

  return (
    <Section title="Gerenciar cupons" description="Fase 3.3: crie, edite, ative ou desative cupons sem alterar pagamentos antigos.">
      <div className="security-note-box"><Save size={18} /><div><strong>Modo seguro de cupons</strong><p>Usa CouponService, valida desconto, datas, limites, ciclos, cargo e planos permitidos. Não deleta cupom e não recalcula compra já feita.</p></div></div>
      <div className="form-actions"><button className="button primary" onClick={() => setCreateOpen((value) => !value)}><Plus size={16} />Novo cupom</button></div>
      {createOpen && <CouponForm draft={newCoupon} roles={options.data?.roles || []} plans={plans.data?.items || []} busy={busy} submitLabel="Criar cupom" onChange={(patch) => setNewCoupon((current) => ({ ...current, ...patch }))} onCancel={() => { setNewCoupon(EMPTY_COUPON_DRAFT); setCreateOpen(false); }} onSubmit={() => createCoupon.mutate()} />}
      {coupons.isLoading ? <LoadingState message="Carregando cupons..." /> : coupons.error ? <ErrorState message={(coupons.error as Error).message} /> : coupons.data?.items.length ? (
        <div className="entity-grid coupon-manage-grid">{coupons.data.items.map((coupon) => {
          const draft = editing[coupon.id];
          return <div className="entity coupon-manage-card" key={coupon.id}><div className="entity-title-row"><strong>{coupon.emoji ? `${coupon.emoji} ${coupon.code}` : coupon.code}</strong><StatusBadge state={coupon.active ? "online" : "neutral"}>{coupon.active ? "Ativo" : "Inativo"}</StatusBadge></div>{!draft ? <><span>{coupon.discount_label}</span><small>{coupon.applies_to_all_plans ? "Todos os planos" : `${coupon.allowed_plan_ids.length} plano(s) permitido(s)`} · {coupon.billing_cycles.length ? `${coupon.billing_cycles.length} ciclo(s)` : "Todos os ciclos"}</small>{coupon.required_role_name && <small>Cargo obrigatório: {coupon.required_role_name}</small>}{coupon.description && <p>{coupon.description}</p>}<div className="card-actions"><button className="button ghost" disabled={busy} onClick={() => setEditing((current) => ({ ...current, [coupon.id]: seedCouponDraft(coupon) }))}><Pencil size={15} />Editar</button><button className="button ghost" disabled={busy} onClick={() => toggleCoupon.mutate(coupon)}><EyeOff size={15} />{coupon.active ? "Desativar" : "Ativar"}</button></div></> : <CouponForm draft={draft} roles={options.data?.roles || []} plans={plans.data?.items || []} busy={busy} compact submitLabel="Salvar" onChange={(patch) => setEditing((current) => ({ ...current, [coupon.id]: { ...current[coupon.id], ...patch } }))} onCancel={() => setEditing((current) => { const next = { ...current }; delete next[coupon.id]; return next; })} onSubmit={() => updateCoupon.mutate({ id: coupon.id, draft })} />}</div>;
        })}</div>
      ) : <EmptyState message="Nenhum cupom cadastrado." />}
      {error && <p className="inline-warning">{(error as Error).message}</p>}
      {coupons.data?.security_notes?.length ? <div className="security-check-grid">{coupons.data.security_notes.map((note) => <span className="role-chip" key={note}>{note}</span>)}</div> : null}
    </Section>
  );
}

function CouponForm({ draft, roles, plans, busy, submitLabel, compact, onChange, onCancel, onSubmit }: { draft: CouponDraft; roles: DiscordOptions["roles"]; plans: MonetizationPlanListPayload["items"]; busy: boolean; submitLabel: string; compact?: boolean; onChange: (patch: Partial<CouponDraft>) => void; onCancel: () => void; onSubmit: () => void; }) {
  return (
    <div className={`dashboard-form ${compact ? "compact-edit-form" : "coupon-create-form"}`}>
      <div className="form-row"><label>Código<input value={draft.code} maxLength={64} onChange={(event) => onChange({ code: event.target.value })} placeholder="GENESIS10" /></label><label>Emoji<input value={draft.emoji} maxLength={64} onChange={(event) => onChange({ emoji: event.target.value })} placeholder="🎟️" /></label><label>Tipo<select value={draft.discount_type} onChange={(event) => onChange({ discount_type: event.target.value as CouponDraft["discount_type"] })}><option value="percentage">Porcentagem</option><option value="fixed">Valor fixo</option></select></label></div>
      <label>Descrição<textarea rows={3} maxLength={1500} value={draft.description} onChange={(event) => onChange({ description: event.target.value })} placeholder="Cupom de lançamento" /></label>
      <div className="form-row"><label>{draft.discount_type === "fixed" ? "Desconto em R$" : "Desconto em %"}<input value={draft.discount_value} onChange={(event) => onChange({ discount_value: event.target.value })} placeholder={draft.discount_type === "fixed" ? "5,00" : "10"} /></label><label>Início<input type="datetime-local" value={draft.starts_at} onChange={(event) => onChange({ starts_at: event.target.value })} /></label><label>Expira<input type="datetime-local" value={draft.expires_at} onChange={(event) => onChange({ expires_at: event.target.value })} /></label></div>
      <div className="form-row"><label>Limite global<input value={draft.max_global_uses} onChange={(event) => onChange({ max_global_uses: event.target.value })} placeholder="Ilimitado" /></label><label>Limite por usuário<input value={draft.max_uses_per_user} onChange={(event) => onChange({ max_uses_per_user: event.target.value })} placeholder="Ilimitado" /></label><label>Cargo obrigatório<select value={draft.required_role_id} onChange={(event) => onChange({ required_role_id: event.target.value })}><option value="">Sem cargo</option>{roles.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}</select></label></div>
      <div className="form-row"><label className="checkbox-label"><input type="checkbox" checked={draft.active} onChange={(event) => onChange({ active: event.target.checked })} /> Ativo</label><label className="checkbox-label"><input type="checkbox" checked={draft.allow_stack} onChange={(event) => onChange({ allow_stack: event.target.checked })} /> Permitir acumular</label></div>
      <div className="role-picker-field"><span className="field-label">Ciclos permitidos</span><div className="role-checkbox-grid">{CYCLES.map(([value, label]) => <label className="role-checkbox" key={value}><input type="checkbox" checked={draft.billing_cycles.includes(value)} onChange={() => onChange({ billing_cycles: toggleList(value, draft.billing_cycles) })} />{label}</label>)}</div><small>Sem marcar nenhum = todos os ciclos.</small></div>
      <div className="role-picker-field"><span className="field-label">Planos permitidos</span><div className="role-checkbox-grid">{plans.map((plan) => <label className="role-checkbox" key={plan.id}><input type="checkbox" checked={draft.allowed_plan_ids.includes(plan.id)} onChange={() => onChange({ allowed_plan_ids: toggleList(plan.id, draft.allowed_plan_ids) })} />{plan.name}</label>)}</div><small>Sem marcar nenhum = todos os planos.</small></div>
      <div className="form-actions"><button className="button ghost" disabled={busy} onClick={onCancel}>Cancelar</button><button className="button primary" disabled={busy} onClick={onSubmit}><Save size={15} />{submitLabel}</button></div>
    </div>
  );
}
