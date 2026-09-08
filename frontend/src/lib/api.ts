export type Guild = {
  id: string;
  name: string;
  icon_url?: string | null;
  member_count?: number | null;
  selected: boolean;
};

export type Readiness = {
  api: boolean;
  discord_ready: boolean;
  discord_closed: boolean;
  guilds_loaded: boolean;
  guild_count: number;
  ready: boolean;
};

export type SettingOption = { value: string; label: string };

export type SettingDefinition = {
  key: string;
  attr?: string;
  label: string;
  description: string;
  type: "channel" | "role" | "role_multi" | "number" | "bool" | "choice" | "text";
  section: string;
  section_title?: string;
  source_model?: string | null;
  options: SettingOption[];
  required: boolean;
  allow_clear?: boolean;
  unit?: "seconds" | "minutes";
  unit_label?: string;
  display_units?: SettingOption[];
  status?: "ok" | "warning" | "error";
  status_message?: string;
  missing_reference?: boolean;
};

export type SettingsPayload = {
  guild_id: string;
  sections: { key: string; title: string; description: string; fields: SettingDefinition[] }[];
  values: Record<string, unknown>;
};

export type DiscordOptions = {
  channels: { id: string; name: string; type: string; position?: number; color?: string }[];
  roles: { id: string; name: string; type: string; position?: number; color?: string }[];
};

export type GiveawayItem = {
  id: string;
  title: string;
  description?: string | null;
  status: "OPEN" | "CLOSED" | "CANCELED" | string;
  channel_id: string;
  channel_name?: string | null;
  channel_missing?: boolean;
  message_id?: string | null;
  creator_id: string;
  creator_name?: string | null;
  winners_count: number;
  entry_count: number;
  winner_ids: string[];
  winner_names: string[];
  allowed_role_ids: string[];
  missing_allowed_role_ids: string[];
  prize_type: "ROLE" | "CUSTOM" | string;
  prize_role_id?: string | null;
  prize_role_name?: string | null;
  prize_text?: string | null;
  expires_at: string;
  closed_at?: string | null;
  created_at?: string | null;
};

export type GiveawaysPayload = {
  guild_id: string;
  items: GiveawayItem[];
};

export type GiveawayMutationResponse = {
  item: GiveawayItem;
};

export type DlcItem = {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  kind: "free" | "paid" | string;
  is_active: boolean;
  deleted: boolean;
  price_amount?: number | null;
  price_label: string;
  currency: string;
  position: number;
  role_id?: string | null;
  role_name?: string | null;
  role_missing?: boolean;
  guild_id?: string | null;
  plan_id?: string | null;
  plan_active?: boolean | null;
  created_at?: string | null;
  updated_at?: string | null;
  deleted_at?: string | null;
};

export type DlcsPayload = {
  guild_id: string;
  items: DlcItem[];
};

export type DlcMutationResponse = {
  item: DlcItem;
};

export type PanelStatus = "not_published" | "ok" | "missing_channel" | "missing_message" | "error";

export type TicketPanelItem = {
  id: string;
  kind: "ticket_panel";
  name: string;
  key: string;
  enabled: boolean;
  published: boolean;
  channel_id?: string | null;
  channel_name?: string | null;
  message_id?: string | null;
  status: PanelStatus;
  show_button: boolean;
};

export type TicketPanelGroupItem = {
  id: string;
  kind: "ticket_group";
  name: string;
  panel_count: number;
  published: boolean;
  channel_id?: string | null;
  channel_name?: string | null;
  message_id?: string | null;
  status: PanelStatus;
};

export type FixedPanelItem = {
  id: "ranking" | "shop";
  kind: "ranking" | "shop";
  name: string;
  description: string;
  published: boolean;
  channel_id?: string | null;
  channel_name?: string | null;
  message_id?: string | null;
  status: PanelStatus;
};

export type PanelsPayload = {
  guild_id: string;
  ticket_panels: TicketPanelItem[];
  groups: TicketPanelGroupItem[];
  fixed: FixedPanelItem[];
};

export type MonetizationMetric = {
  label: string;
  value: number | string;
  hint?: string | null;
  source?: string | null;
};

export type MonetizationAlert = {
  severity: "info" | "warning" | "error";
  title: string;
  message: string;
};

export type MonetizationRecentPayment = {
  id: string;
  user_id: string;
  plan_id: string;
  plan_name?: string | null;
  provider: string;
  amount_label: string;
  amount_cents: number;
  status: string;
  created_at: string;
  paid_at?: string | null;
  expires_at?: string | null;
};

export type MonetizationPlanRow = {
  id: string;
  name: string;
  active: boolean;
  role_id?: string | null;
  role_name?: string | null;
  role_missing: boolean;
  price_monthly_label?: string | null;
  price_yearly_label?: string | null;
  price_one_time_label?: string | null;
  approved_sales: number;
  approved_revenue_label: string;
  approved_revenue_cents: number;
  pending_payments: number;
  failed_payments: number;
  active_subscriptions: number;
  average_ticket_label: string;
  last_payment_at?: string | null;
  source_note: string;
};

export type MonetizationStatusBreakdown = {
  status: string;
  count: number;
  amount_label: string;
  amount_cents: number;
};

export type MonetizationCouponRow = {
  id: string;
  code: string;
  active: boolean;
  deleted: boolean;
  discount: string;
  starts_at?: string | null;
  expires_at?: string | null;
  source_note: string;
};

export type MonetizationSummary = {
  guild_id: string;
  generated_at: string;
  gateway: { providers_seen?: string[]; mode?: string; read_only?: boolean; provider_breakdown?: { provider: string; count: number; amount_label: string }[] };
  metrics: MonetizationMetric[];
  alerts: MonetizationAlert[];
  recent_payments: MonetizationRecentPayment[];
  plans: MonetizationPlanRow[];
  payment_status_breakdown: MonetizationStatusBreakdown[];
  coupons: MonetizationCouponRow[];
  analytics: Record<string, unknown>;
  source_notes: string[];
  security_notes: string[];
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/admin/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const message = body?.error?.message || body?.detail?.error?.message || "Falha na API.";
    throw new Error(message);
  }
  return body as T;
}
