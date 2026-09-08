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
