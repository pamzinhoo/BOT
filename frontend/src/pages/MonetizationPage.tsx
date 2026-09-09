import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BarChart3, EyeOff, Pencil, Plus, Save, ShieldCheck, Star } from "lucide-react";
import { useState } from "react";
import { useShell } from "../components/AppShell";
import { MonetizationCouponManager } from "../components/MonetizationCouponManager";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section, StatusBadge } from "../components/Ui";
import { api, DiscordOptions, MonetizationPlanAccessPayload, MonetizationPlanListPayload, MonetizationPlanManageRow, MonetizationPlanMutationPayload, MonetizationPlanMutationResponse, MonetizationSummary } from "../lib/api";

type PlanDraft = {
  name: string;
  description: string;
  emoji: string;
  role_id: string;
  price_monthly_reais: string;
  price_yearly_reais: string;
  price_one_time_reais: string;
  position: number;
  is_recommended: boolean;
  is_active: boolean;
};

const EMPTY_PLAN_DRAFT: PlanDraft = {
  name: "",
  description: "",
  emoji: "",
  role_id: "",
  price_monthly_reais: "",
  price_yearly_reais: "",
  price_one_time_reais: "",
  position: 0,
  is_recommended: false,
  is_active: true,
};

function fmtDate(value?: string | null) {
  return value ? new Date(value).toLocaleString("pt-BR") : "Sem dados";
}

function paymentStatusLabel(value: string) {
  return {
    pending: "Pendente",
    processing: "Processando",
    approved: "Aprovado",
    rejected: "Recusado",
    expired: "Expirado",
    canceled: "Cancelado",
    refunded: "Estornado",
    chargeback: "Chargeback",
  }[value] || value;
}

function subscriptionStatusLabel(value?: string | null) {
  if (!value) return "Sem assinatura";
  return { pending: "Pendente", active: "Ativa", canceled: "Cancelada", expired: "Expirada" }[value] || value;
}

function cycleLabel(value?: string | null) {
  if (!value) return "—";
  return { monthly: "Mensal", yearly: "Anual", one_time: "Único" }[value] || value;
}

function accessSourceLabel(value: string) {
  return value.replace("assinatura", "Assinatura").replace("pagamento", "Pagamento").replace("cargo_atual", "Cargo atual").replace("registro", "Registro");
}

function paymentState(value: string) {
  if (value === "approved") return "online";
  if (value === "pending" || value === "processing") return "degraded";
  return "offline";
}

function subState(value?: string | null) {
  if (value === "active") return "online";
  if (value === "pending") return "degraded";
  return "neutral";
}

function alertState(value: string) {
  if (value === "error") return "offline";
  if (value === "warning") return "degraded";
  return "neutral";
}

function planPrice(plan: MonetizationSummary["plans"][number]) {
  return [plan.price_monthly_label ? `Mensal ${plan.price_monthly_label}` : null, plan.price_yearly_label ? `Anual ${plan.price_yearly_label}` : null, plan.price_one_time_label ? `Único ${plan.price_one_time_label}` : null].filter(Boolean).join(" · ") || "Sem preço";
}

function analyticsText(value: unknown) {
  return typeof value === "string" && value ? value : "Sem venda aprovada";
}

function centsToInput(value?: number | null) {
  return value ? String((value / 100).toFixed(2)).replace(".", ",") : "";
}

function seedPlanDraft(plan: MonetizationPlanManageRow): PlanDraft {
  return {
    name: plan.name,
    description: plan.description || "",
    emoji: plan.emoji || "",
    role_id: plan.role_id || "",
    price_monthly_reais: centsToInput(plan.price_monthly_amount),
    price_yearly_reais: centsToInput(plan.price_yearly_amount),
    price_one_time_reais: centsToInput(plan.price_one_time_amount),
    position: plan.position,
    is_recommended: plan.is_recommended,
    is_active: plan.is_active,
  };
}

function buildPlanPayload(draft: PlanDraft): MonetizationPlanMutationPayload {
  return {
    name: draft.name,
    description: draft.description,
    emoji: draft.emoji,
    role_id: draft.role_id,
    price_monthly_reais: draft.price_monthly_reais,
    price_yearly_reais: draft.price_yearly_reais,
    price_one_time_reais: draft.price_one_time_reais,
    position: Number(draft.position || 0),
    is_recommended: draft.is_recommended,
    is_active: draft.is_active,
  };
}

export function MonetizationPage() {
  const { guild, readiness, guildsError } = useShell();
  const queryClient = useQueryClient();
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [createPlanOpen, setCreatePlanOpen] = useState(false);
  const [newPlan, setNewPlan] = useState<PlanDraft>(EMPTY_PLAN_DRAFT);
  const [editingPlans, setEditingPlans] = useState<Record<string, PlanDraft>>({});

  const { data, isLoading, error } = useQuery({ queryKey: ["monetization", guild?.id], queryFn: () => api<MonetizationSummary>(`/guild/${guild!.id}/monetization/summary`), enabled: Boolean(guild) });
  const planManage = useQuery({ queryKey: ["monetization-plan-manage", guild?.id], queryFn: () => api<MonetizationPlanListPayload>(`/guild/${guild!.id}/monetization/plans/manage`), enabled: Boolean(guild) });
  const options = useQuery({ queryKey: ["discord-options", guild?.id], queryFn: () => api<DiscordOptions>(`/guild/${guild!.id}/discord-options`), enabled: Boolean(guild), refetchInterval: 60_000 });
  const planAccess = useQuery({ queryKey: ["monetization-plan-access", guild?.id, selectedPlanId], queryFn: () => api<MonetizationPlanAccessPayload>(`/guild/${guild!.id}/monetization/plans/${selectedPlanId}/access`), enabled: Boolean(guild && selectedPlanId), refetchInterval: 20_000 });

  const invalidateMonetization = () => {
    queryClient.invalidateQueries({ queryKey: ["monetization", guild?.id] });
    queryClient.invalidateQueries({ queryKey: ["monetization-plan-manage", guild?.id] });
    queryClient.invalidateQueries({ queryKey: ["monetization-plan-access", guild?.id] });
    queryClient.invalidateQueries({ queryKey: ["panels", guild?.id] });
    queryClient.invalidateQueries({ queryKey: ["audit", guild?.id] });
  };

  const createPlan = useMutation({
    mutationFn: () => api<MonetizationPlanMutationResponse>(`/guild/${guild!.id}/monetization/plans`, { method: "POST", body: JSON.stringify(buildPlanPayload(newPlan)) }),
    onSuccess: () => { setNewPlan(EMPTY_PLAN_DRAFT); setCreatePlanOpen(false); invalidateMonetization(); },
  });
  const updatePlan = useMutation({
    mutationFn: ({ id, draft }: { id: string; draft: PlanDraft }) => api<MonetizationPlanMutationResponse>(`/guild/${guild!.id}/monetization/plans/${id}`, { method: "PATCH", body: JSON.stringify(buildPlanPayload(draft)) }),
    onSuccess: (response) => { setEditingPlans((current) => { const next = { ...current }; delete next[response.item.id]; return next; }); invalidateMonetization(); },
  });
  const togglePlan = useMutation({
    mutationFn: (plan: MonetizationPlanManageRow) => api<MonetizationPlanMutationResponse>(`/guild/${guild!.id}/monetization/plans/${plan.id}/toggle`, { method: "POST", body: JSON.stringify({ is_active: !plan.is_active }) }),
    onSuccess: invalidateMonetization,
  });

  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return <EmptyState message="Resumo de monetização indisponível." />;

  const busy = createPlan.isPending || updatePlan.isPending || togglePlan.isPending;

  return (
    <>
      <PageHeader title="Monetização" description="Fase 3.1 somente leitura + Fase 3.2 + Fase 3.3: analytics e gerenciamento seguro de planos e cupons; não exibe QR Code PIX e não altera pagamentos, assinaturas ou licenças." />

      <Section title="Resumo" description={`Gateway: ${data.gateway.mode || "Sem dados"} · Gerado em ${fmtDate(data.generated_at)}`}>
        <div className="metric-grid compact-grid monetization-metric-grid">{data.metrics.map((metric) => (<div className="metric-card staff-metric-card" key={metric.label} title={metric.source || undefined}><span>{metric.label}</span><strong>{metric.value}</strong>{metric.hint && <small>{metric.hint}</small>}{metric.source && <em>{metric.source}</em>}</div>))}</div>
      </Section>

      <Section title="Analytics de vendas" description="Mostra qual plano vendeu mais, qual faturou mais e o ticket médio com base em registros aprovados no banco.">
        <div className="analytics-grid"><div className="analytics-card"><BarChart3 size={18} /><span>Plano que mais vendeu</span><strong>{analyticsText(data.analytics.top_seller_plan)}</strong></div><div className="analytics-card"><BarChart3 size={18} /><span>Plano que mais faturou</span><strong>{analyticsText(data.analytics.top_revenue_plan)}</strong></div><div className="analytics-card"><BarChart3 size={18} /><span>Vendas aprovadas</span><strong>{String(data.analytics.approved_sales_total ?? 0)}</strong></div></div>
      </Section>

      <Section title="Gerenciar planos" description="Crie, edite, ative ou desative planos usando o PlanService. Não apaga histórico financeiro.">
        <div className="form-actions"><button className="button primary" onClick={() => setCreatePlanOpen((value) => !value)}><Plus size={16} />Novo plano</button></div>
        {createPlanOpen && <PlanForm draft={newPlan} roles={options.data?.roles || []} submitLabel="Criar plano" busy={busy} onChange={(patch) => setNewPlan((current) => ({ ...current, ...patch }))} onCancel={() => { setNewPlan(EMPTY_PLAN_DRAFT); setCreatePlanOpen(false); }} onSubmit={() => createPlan.mutate()} />}
        {planManage.isLoading ? <LoadingState message="Carregando planos..." /> : planManage.error ? <ErrorState message={(planManage.error as Error).message} /> : planManage.data?.items.length ? (
          <div className="entity-grid plan-manage-grid">{planManage.data.items.map((plan) => {
            const draft = editingPlans[plan.id];
            return <div className="entity plan-manage-card" key={plan.id}><div className="entity-title-row"><strong>{plan.emoji ? `${plan.emoji} ${plan.name}` : plan.name}</strong><StatusBadge state={plan.is_active ? "online" : "neutral"}>{plan.is_active ? "Ativo" : "Inativo"}</StatusBadge></div>{!draft ? <><span>{[plan.price_monthly_label && `Mensal ${plan.price_monthly_label}`, plan.price_yearly_label && `Anual ${plan.price_yearly_label}`, plan.price_one_time_label && `Único ${plan.price_one_time_label}`].filter(Boolean).join(" · ") || "Sem preço"}</span><small>{plan.role_name ? `Cargo: ${plan.role_name}` : plan.role_id ? "Cargo ausente" : "Sem cargo vinculado"}</small>{plan.description && <p>{plan.description}</p>}{plan.is_recommended && <span className="role-chip"><Star size={13} /> Recomendado</span>}<div className="card-actions"><button className="button ghost" disabled={busy} onClick={() => setEditingPlans((current) => ({ ...current, [plan.id]: seedPlanDraft(plan) }))}><Pencil size={15} />Editar</button><button className="button ghost" disabled={busy} onClick={() => togglePlan.mutate(plan)}><EyeOff size={15} />{plan.is_active ? "Desativar" : "Ativar"}</button></div></> : <PlanForm draft={draft} roles={options.data?.roles || []} submitLabel="Salvar" busy={busy} compact onChange={(patch) => setEditingPlans((current) => ({ ...current, [plan.id]: { ...current[plan.id], ...patch } }))} onCancel={() => setEditingPlans((current) => { const next = { ...current }; delete next[plan.id]; return next; })} onSubmit={() => updatePlan.mutate({ id: plan.id, draft })} />}</div>;
          })}</div>
        ) : <EmptyState message="Nenhum plano cadastrado." />}
        {(createPlan.error || updatePlan.error || togglePlan.error) && <p className="inline-warning">{((createPlan.error || updatePlan.error || togglePlan.error) as Error).message}</p>}
      </Section>

      <MonetizationCouponManager guildId={guild.id} />

      <Section title="Planos e desempenho" description="Clique em um plano para ver quais usuários têm o VIP/cargo, assinatura ou pagamento registrado.">
        {data.plans.length === 0 ? <EmptyState message="Nenhum plano cadastrado." /> : (<table className="data-table monetization-table"><thead><tr><th>Plano</th><th>Preço</th><th>Status</th><th>Vendas</th><th>Receita</th><th>Ticket médio</th><th>Assinaturas</th><th>Pendentes</th><th>Falhas</th></tr></thead><tbody>{data.plans.map((plan) => (<tr key={plan.id} title="Clique para ver usuários deste plano/VIP" className={`clickable-table-row ${selectedPlanId === plan.id ? "is-selected" : ""}`} onClick={() => setSelectedPlanId((current) => current === plan.id ? null : plan.id)}><td><strong>{plan.name}</strong><small>{plan.role_name ? `Cargo: ${plan.role_name}` : plan.role_id ? "Cargo ausente" : "Sem cargo"}</small></td><td>{planPrice(plan)}</td><td><StatusBadge state={plan.active ? "online" : "neutral"}>{plan.active ? "Ativo" : "Inativo"}</StatusBadge></td><td>{plan.approved_sales}</td><td>{plan.approved_revenue_label}</td><td>{plan.average_ticket_label}</td><td>{plan.active_subscriptions}</td><td>{plan.pending_payments}</td><td>{plan.failed_payments}</td></tr>))}</tbody></table>)}
      </Section>

      {selectedPlanId && <Section title="Usuários do plano/VIP" description="Somente leitura: cruza assinatura, pagamento registrado e cargo atual no Discord.">{planAccess.isLoading ? <LoadingState message="Carregando usuários do plano..." /> : planAccess.error ? <ErrorState message={(planAccess.error as Error).message} /> : planAccess.data ? <div className="plan-access-panel"><div className="entity-title-row"><div><strong>{planAccess.data.plan.name}</strong><small>{planAccess.data.total} usuário(s) encontrado(s) · Cargo: {planAccess.data.role_name || planAccess.data.role_id || "sem cargo vinculado"}</small></div>{planAccess.data.role_missing && <StatusBadge state="offline">Cargo ausente</StatusBadge>}</div>{planAccess.data.items.length === 0 ? <EmptyState message="Nenhum usuário com assinatura, pagamento ou cargo deste plano." /> : <table className="data-table"><thead><tr><th>Usuário</th><th>ID Discord</th><th>Origem</th><th>Assinatura</th><th>Ciclo</th><th>Cargo agora</th><th>Aprovados</th><th>Receita</th><th>Último pagamento</th></tr></thead><tbody>{planAccess.data.items.map((user) => (<tr key={user.discord_id}><td><strong>{user.discord_name || "Nome não resolvido"}</strong><small>{user.provider || "Sem provider"}</small></td><td className="mono">{user.discord_id}</td><td>{accessSourceLabel(user.source)}</td><td><StatusBadge state={subState(user.subscription_status)}>{subscriptionStatusLabel(user.subscription_status)}</StatusBadge></td><td>{cycleLabel(user.billing_cycle)}</td><td>{user.has_role_now ? "Sim" : "Não"}</td><td>{user.approved_payments}</td><td>{user.approved_revenue_label}</td><td>{fmtDate(user.last_payment_at)}</td></tr>))}</tbody></table>}<div className="security-check-grid">{planAccess.data.security_notes.map((note) => <span className="role-chip" key={note}>{note}</span>)}</div></div> : <EmptyState message="Selecione um plano para ver os usuários." />}</Section>}

      <Section title="Pagamentos por status" description="Distribuição dos registros em payment_history.">{data.payment_status_breakdown.length === 0 ? <EmptyState message="Nenhum pagamento registrado." /> : <table className="data-table"><thead><tr><th>Status</th><th>Quantidade</th><th>Valor registrado</th></tr></thead><tbody>{data.payment_status_breakdown.map((row) => (<tr key={row.status}><td><StatusBadge state={paymentState(row.status)}>{paymentStatusLabel(row.status)}</StatusBadge></td><td>{row.count}</td><td>{row.amount_label}</td></tr>))}</tbody></table>}</Section>

      <Section title="Cupons cadastrados" description="Mostra apenas cupons não deletados logicamente.">{data.coupons.length === 0 ? <EmptyState message="Nenhum cupom cadastrado." /> : <table className="data-table"><thead><tr><th>Código</th><th>Desconto</th><th>Status</th><th>Início</th><th>Expira</th></tr></thead><tbody>{data.coupons.map((coupon) => (<tr key={coupon.id} title={coupon.source_note}><td><strong>{coupon.code}</strong></td><td>{coupon.discount}</td><td><StatusBadge state={coupon.deleted ? "offline" : coupon.active ? "online" : "neutral"}>{coupon.deleted ? "Deletado lógico" : coupon.active ? "Ativo" : "Inativo"}</StatusBadge></td><td>{fmtDate(coupon.starts_at)}</td><td>{fmtDate(coupon.expires_at)}</td></tr>))}</tbody></table>}</Section>

      <Section title="Varredura de segurança" description="Alertas de configuração e consistência antes de liberar ações maiores."><div className="security-note-box"><ShieldCheck size={18} /><div><strong>Modo seguro da Fase 3.2/3.3</strong><p>Editar plano ou cupom não altera pagamentos, assinaturas, licenças ou cargos já concedidos. Desativar só tira da oferta ativa e preserva histórico.</p></div></div>{data.alerts.length === 0 ? <EmptyState message="Nenhum alerta crítico encontrado." /> : <div className="alert-list">{data.alerts.map((item) => (<div className="alert-row" key={`${item.severity}-${item.title}-${item.message}`}><AlertTriangle size={16} /><div><strong>{item.title}</strong><span>{item.message}</span></div><StatusBadge state={alertState(item.severity)}>{item.severity}</StatusBadge></div>))}</div>}</Section>

      <Section title="Pagamentos recentes" description="Somente leitura, sem dados sensíveis do PIX ou comprador.">{data.recent_payments.length === 0 ? <EmptyState message="Nenhum pagamento registrado ainda." /> : <table className="data-table"><thead><tr><th>Plano</th><th>Valor</th><th>Status</th><th>Provider</th><th>Criado em</th><th>Pago em</th></tr></thead><tbody>{data.recent_payments.map((payment) => (<tr key={payment.id}><td><strong>{payment.plan_name || "Plano removido"}</strong><small>Usuário: {payment.user_id}</small></td><td>{payment.amount_label}</td><td><StatusBadge state={paymentState(payment.status)}>{paymentStatusLabel(payment.status)}</StatusBadge></td><td>{payment.provider}</td><td>{fmtDate(payment.created_at)}</td><td>{fmtDate(payment.paid_at)}</td></tr>))}</tbody></table>}</Section>

      <Section title="Notas de segurança aplicadas"><div className="security-check-grid">{data.security_notes.map((note) => <span className="role-chip" key={note}>{note}</span>)}</div></Section>
    </>
  );
}

function PlanForm({ draft, roles, submitLabel, busy, compact, onChange, onCancel, onSubmit }: { draft: PlanDraft; roles: DiscordOptions["roles"]; submitLabel: string; busy: boolean; compact?: boolean; onChange: (patch: Partial<PlanDraft>) => void; onCancel: () => void; onSubmit: () => void; }) {
  return (
    <div className={`dashboard-form ${compact ? "compact-edit-form" : "plan-create-form"}`}>
      <div className="form-row"><label>Nome<input value={draft.name} maxLength={100} onChange={(event) => onChange({ name: event.target.value })} placeholder="Apoiador" /></label><label>Emoji<input value={draft.emoji} maxLength={64} onChange={(event) => onChange({ emoji: event.target.value })} placeholder="🌙" /></label><label>Posição<input type="number" min={0} max={500} value={draft.position} onChange={(event) => onChange({ position: Number(event.target.value || 0) })} /></label></div>
      <label>Descrição<textarea rows={3} maxLength={1500} value={draft.description} onChange={(event) => onChange({ description: event.target.value })} placeholder="Benefícios principais do plano" /></label>
      <div className="form-row"><label>Preço mensal<input value={draft.price_monthly_reais} onChange={(event) => onChange({ price_monthly_reais: event.target.value })} placeholder="5,99" /></label><label>Preço anual<input value={draft.price_yearly_reais} onChange={(event) => onChange({ price_yearly_reais: event.target.value })} placeholder="59,90" /></label><label>Preço único<input value={draft.price_one_time_reais} onChange={(event) => onChange({ price_one_time_reais: event.target.value })} placeholder="99,90" /></label></div>
      <div className="form-row"><label>Cargo<select value={draft.role_id} onChange={(event) => onChange({ role_id: event.target.value })}><option value="">Sem cargo</option>{roles.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}</select></label><label className="checkbox-label"><input type="checkbox" checked={draft.is_recommended} onChange={(event) => onChange({ is_recommended: event.target.checked })} /> Recomendado</label><label className="checkbox-label"><input type="checkbox" checked={draft.is_active} onChange={(event) => onChange({ is_active: event.target.checked })} /> Ativo na loja</label></div>
      <div className="form-actions"><button className="button ghost" disabled={busy} onClick={onCancel}>Cancelar</button><button className="button primary" disabled={busy} onClick={onSubmit}><Save size={15} />{submitLabel}</button></div>
    </div>
  );
}
