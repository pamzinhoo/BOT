import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Save } from "lucide-react";
import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useShell } from "../components/AppShell";
import { SearchInput, SettingControl } from "../components/SettingsControls";
import { EmptyState, ErrorState, LoadingState, PageHeader, Section } from "../components/Ui";
import { api, DiscordOptions, SettingsPayload } from "../lib/api";

export function SettingsPage() {
  const { section = "tickets" } = useParams();
  const { guild, readiness, guildsError } = useShell();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [search, setSearch] = useState("");
  const settings = useQuery({
    queryKey: ["settings", guild?.id],
    queryFn: () => api<SettingsPayload>(`/guild/${guild!.id}/settings`),
    enabled: Boolean(guild),
  });
  const options = useQuery({
    queryKey: ["discord-options", guild?.id],
    queryFn: () => api<DiscordOptions>(`/guild/${guild!.id}/discord-options`),
    enabled: Boolean(guild),
  });
  const mutation = useMutation({
    mutationFn: (values: Record<string, unknown>) => api<SettingsPayload>(`/guild/${guild!.id}/settings`, { method: "PATCH", body: JSON.stringify({ values }) }),
    onSuccess: () => {
      setDraft({});
      queryClient.invalidateQueries({ queryKey: ["settings", guild?.id] });
      queryClient.invalidateQueries({ queryKey: ["overview", guild?.id] });
    },
  });

  const active = useMemo(() => settings.data?.sections.find((item) => item.key === section), [settings.data, section]);
  const values = { ...(settings.data?.values || {}), ...draft };
  const changed = Object.keys(draft).length;
  const fields = active?.fields.filter((field) => {
    const haystack = `${displayLabel(field.label)} ${field.description} ${active.title}`.toLowerCase();
    return haystack.includes(search.toLowerCase());
  });
  const grouped = groupFields(section, fields || []);

  if (guildsError) return <ErrorState message={guildsError.message} />;
  if (!readiness?.discord_ready) return <LoadingState message="Conectando ao Discord..." />;
  if (readiness.discord_ready && !readiness.guilds_loaded) return <LoadingState message="Discord conectado, carregando servidores..." />;
  if (readiness.ready && !guild) return <EmptyState message="Nenhum servidor disponível para este bot." />;
  if (settings.isLoading) return <LoadingState />;
  if (settings.error) return <ErrorState message={(settings.error as Error).message} />;
  if (!active) return <EmptyState message="Seção não encontrada." />;

  return (
    <>
      <PageHeader title={active.title} description={active.description} action={<SearchInput value={search} onChange={setSearch} />} />
      {grouped.map((group) => (
        <Section title={group.title} description={group.description} key={group.title}>
          <div className="settings-list">
            {group.fields.map((field) => (
              <div className="setting-row" key={field.key}>
                <div>
                  <strong>{displayLabel(field.label)}</strong>
                  <p>{field.description || fallbackDescription(field.type)}</p>
                </div>
                <SettingControl field={field} value={values[field.key]} options={options.data} onChange={(value) => setDraft((current) => ({ ...current, [field.key]: value }))} />
              </div>
            ))}
          </div>
        </Section>
      ))}
      {changed > 0 && (
        <div className="save-bar">
          <span>{changed} alteração{changed === 1 ? "" : "es"} não salva{changed === 1 ? "" : "s"}</span>
          <button className="button ghost" onClick={() => setDraft({})}><RotateCcw size={16} />Descartar</button>
          <button className="button primary" onClick={() => mutation.mutate(draft)} disabled={mutation.isPending}><Save size={16} />Salvar alterações</button>
          {mutation.error && <b>{(mutation.error as Error).message}</b>}
        </div>
      )}
    </>
  );
}

function fallbackDescription(type: string) {
  if (type === "role_multi") return "Lista vazia usa permissão padrão.";
  if (type === "channel") return "Canal usado pelo bot neste fluxo.";
  if (type === "role") return "Cargo usado pelas permissões do bot.";
  if (type === "text") return "Vazio usa a mensagem padrão.";
  return "Valor salvo nas configurações existentes.";
}

function displayLabel(label: string) {
  return {
    "Auto-Close Ativado": "Auto fechamento",
    "Máximo de Tickets por Usuário": "Máximo por usuário",
    "Permitir Múltiplos Tickets": "Múltiplos tickets",
    "Delay de Exclusão (segundos)": "Delay de exclusão",
    "Tempo de Inatividade (min)": "Tempo de inatividade",
    "Avaliação Ativada": "Avaliações",
    "Nota Mínima p/ Comentário Obrigatório": "Comentário obrigatório até",
    "Método de Avaliação": "Método",
    "Quem pode usar Config": "Quem pode alterar configurações",
    "Quem pode aceitar/negar recurso de banimento": "Quem pode revisar recurso",
  }[label] || label;
}

function groupFields(section: string, fields: NonNullable<SettingsPayload["sections"][number]["fields"]>) {
  const groups = [
    { title: "Geral", description: "Comportamento principal.", match: ["enabled", "allow_multiple_tickets", "max_tickets_per_user", "criteria", "default_period", "min_comment_rating", "star_emoji", "evaluation_method", "window_seconds", "cross_channel_threshold", "flood_threshold", "ignore_staff", "default_action"] },
    { title: "Canais", description: "Destinos e categorias do Discord.", match: ["channel", "category"] },
    { title: "Cargos", description: "Cargos associados a permissões e operação.", match: ["role"] },
    { title: "Auto fechamento", description: "Fecha tickets inativos após o período definido.", match: ["auto_close", "inactive_after", "delete_delay"] },
    { title: "Mensagem por DM", description: "Textos enviados ao usuário após atendimento.", match: ["dm_"] },
    { title: "Ações", description: "Quem pode executar cada ação.", match: ["claim", "unclaim", "fechar", "reabrir", "excluir", "auditoria", "ranking", "config", "recurso_banimento", "analises", "convite"] },
  ];
  if (section === "permissoes") return [{ title: "Ações", description: "Defina cargos por ação. Vazio usa o padrão do bot.", fields }];
  const used = new Set<string>();
  const result = [];
  for (const group of groups) {
    const groupFields = fields.filter((field) => {
      if (used.has(field.key)) return false;
      const key = field.key.toLowerCase();
      const hit = group.match.some((needle) => key.includes(needle));
      if (hit) used.add(field.key);
      return hit;
    });
    if (groupFields.length) {
      result.push({ title: group.title, description: group.description, fields: groupFields });
    }
  }
  const other = fields.filter((field) => !used.has(field.key));
  if (other.length) result.push({ title: "Outros", description: "Ajustes específicos deste módulo.", fields: other });
  return result;
}
