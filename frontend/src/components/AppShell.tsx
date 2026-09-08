import {
  Activity,
  BarChart3,
  Bell,
  Bot,
  ClipboardList,
  FileText,
  Gift,
  Handshake,
  Heart,
  LayoutDashboard,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Shield,
  Star,
  Ticket,
  Trophy,
  UserCheck,
  Users,
} from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { NavLink } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Guild, Readiness } from "../lib/api";

type ShellContextValue = { guild?: Guild; readiness?: Readiness; guildsError?: Error | null };

const ShellContext = createContext<ShellContextValue>({});

export function useShell() {
  return useContext(ShellContext);
}

const nav = [
  {
    label: "Visão geral",
    items: [{ label: "Dashboard", to: "/", icon: LayoutDashboard }],
  },
  {
    label: "Gerenciamento",
    items: [
      { label: "Tickets", to: "/tickets", icon: Ticket },
      { label: "Staff", to: "/staff", icon: Users },
      { label: "Painéis", to: "/panels", icon: FileText },
      { label: "Sorteios", to: "/giveaways", icon: Gift },
      { label: "DLCs", to: "/dlcs", icon: Package },
    ],
  },
  {
    label: "Comunidade",
    items: [
      { label: "Avaliações", to: "/settings/avaliacoes", icon: Star },
      { label: "Ranking", to: "/settings/ranking", icon: BarChart3 },
      { label: "Verificação", to: "/settings/verificacao", icon: UserCheck },
      { label: "Parcerias", to: "/settings/parcerias", icon: Handshake },
      { label: "Boost", to: "/settings/boost", icon: Heart },
    ],
  },
  {
    label: "Servidor",
    items: [
      { label: "Cargos", to: "/settings/cargos", icon: Shield },
      { label: "Permissões", to: "/settings/permissoes", icon: Shield },
      { label: "Anti-Spam", to: "/settings/antispam", icon: Activity },
      { label: "Moderação", to: "/settings/moderacao", icon: Trophy },
      { label: "Alertas", to: "/settings/alertas", icon: Bell },
      { label: "Auditoria", to: "/audit", icon: ClipboardList },
    ],
  },
  {
    label: "Sistema",
    items: [
      { label: "Bot", to: "/system", icon: Bot },
      { label: "Dashboard", to: "/settings/dashboard", icon: Settings },
      { label: "Tickets config", to: "/settings/tickets", icon: Settings },
    ],
  },
];

const EVENT_QUERY_KEYS = [
  "ready",
  "guilds",
  "overview",
  "settings",
  "discord-options",
  "panels",
  "tickets",
  "staff",
  "audit",
  "system",
  "giveaways",
  "dlcs",
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const queryClient = useQueryClient();
  const readyQuery = useQuery({
    queryKey: ["ready"],
    queryFn: () => api<Readiness>("/ready"),
    refetchInterval: (query) => (query.state.data?.ready ? false : 2_000),
  });
  const guildsQuery = useQuery({
    queryKey: ["guilds"],
    queryFn: () => api<Guild[]>("/guilds"),
    refetchInterval: () => (readyQuery.data?.ready ? false : 2_000),
  });
  const guilds = guildsQuery.data || [];
  const guild = useMemo(() => guilds.find((item) => item.selected) || guilds[0], [guilds]);
  const readiness = readyQuery.data;
  const guildLabel = readiness?.discord_ready
    ? guild?.name || "Nenhum servidor disponível"
    : "Conectando ao Discord...";
  const botLabel = readiness?.ready ? "Bot conectado" : "Bot inicializando";

  useEffect(() => {
    if (!readiness?.ready || !guild?.id) return undefined;
    const source = new EventSource(`/admin/api/events?guild_id=${guild.id}`);
    const invalidate = () => {
      EVENT_QUERY_KEYS.forEach((key) => {
        queryClient.invalidateQueries({ queryKey: [key] });
        queryClient.invalidateQueries({ queryKey: [key, guild.id] });
      });
    };
    source.addEventListener("dashboard.invalidate", invalidate);
    source.onerror = () => {
      source.close();
    };
    return () => source.close();
  }, [guild?.id, queryClient, readiness?.ready]);

  return (
    <ShellContext.Provider value={{ guild, readiness, guildsError: guildsQuery.error as Error | null }}>
      <div className={`shell ${collapsed ? "is-collapsed" : ""}`}>
        <aside className="sidebar">
          <div className="brand">
            <div>
              <strong>Limerence</strong>
              {!collapsed && <span>Admin Console</span>}
            </div>
            <button className="icon-button" onClick={() => setCollapsed((value) => !value)} aria-label="Alternar sidebar">
              {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            </button>
          </div>
          {!collapsed && (
            <div className="bot-chip">
              <span className="status-dot" />
              <div>
                <b>{botLabel}</b>
                <small>{guildLabel}</small>
              </div>
            </div>
          )}
          <nav className="nav">
            {nav.map((group) => (
              <div className="nav-group" key={group.label}>
                {!collapsed && <p>{group.label}</p>}
                {group.items.map((item) => (
                  <NavLink className="nav-item" to={item.to} key={item.to} title={item.label}>
                    <item.icon size={18} />
                    {!collapsed && <span>{item.label}</span>}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
        </aside>
        <main className="main">
          <header className="topbar">
            <div>
              <span className="breadcrumb">Admin Console</span>
              <strong>{guildLabel}</strong>
            </div>
            <div className="top-actions">
              <span className="pill">Local</span>
              <span className="pill muted">127.0.0.1</span>
            </div>
          </header>
          <div className="content">{children}</div>
        </main>
      </div>
    </ShellContext.Provider>
  );
}
