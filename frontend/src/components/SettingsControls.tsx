import { Search } from "lucide-react";
import { DiscordOptions, SettingDefinition } from "../lib/api";

type Props = {
  field: SettingDefinition;
  value: unknown;
  onChange: (value: unknown) => void;
  options?: DiscordOptions;
};

const UNIT_LABELS = {
  seconds: "segundos",
  minutes: "minutos",
  hours: "horas",
  days: "dias",
} as const;

const UNIT_TO_SECONDS = {
  seconds: 1,
  minutes: 60,
  hours: 3600,
  days: 86400,
} as const;

type DisplayUnit = keyof typeof UNIT_TO_SECONDS;

function storageToSeconds(field: SettingDefinition, value: number) {
  if (field.unit === "minutes") return value * 60;
  return value;
}

function secondsToStorage(field: SettingDefinition, seconds: number) {
  if (field.unit === "minutes") return Math.round(seconds / 60);
  return Math.round(seconds);
}

function bestUnit(seconds: number): DisplayUnit {
  if (seconds > 0 && seconds % UNIT_TO_SECONDS.days === 0) return "days";
  if (seconds > 0 && seconds % UNIT_TO_SECONDS.hours === 0) return "hours";
  if (seconds > 0 && seconds % UNIT_TO_SECONDS.minutes === 0) return "minutes";
  return "seconds";
}

function isEmojiField(field: SettingDefinition) {
  return field.attr?.includes("emoji") || field.key.includes("emoji");
}

function DurationControl({ field, value, onChange }: Props) {
  const raw = value == null || value === "" ? null : Number(value);
  const seconds = raw == null || Number.isNaN(raw) ? 0 : storageToSeconds(field, raw);
  const selectedUnit = bestUnit(seconds);
  const amount = raw == null || Number.isNaN(raw) ? "" : String(seconds / UNIT_TO_SECONDS[selectedUnit]);

  const setDuration = (nextAmount: string, nextUnit: DisplayUnit) => {
    if (nextAmount === "") {
      onChange(null);
      return;
    }
    const parsed = Number(nextAmount);
    if (Number.isNaN(parsed) || parsed < 0) return;
    onChange(secondsToStorage(field, parsed * UNIT_TO_SECONDS[nextUnit]));
  };

  return (
    <div className="duration-control">
      <input
        type="number"
        min="0"
        step="1"
        value={amount}
        onChange={(event) => setDuration(event.target.value, selectedUnit)}
        aria-label={field.label}
      />
      <select value={selectedUnit} onChange={(event) => setDuration(amount, event.target.value as DisplayUnit)} aria-label="Unidade de tempo">
        {(field.display_units?.length ? field.display_units : Object.entries(UNIT_LABELS).map(([unit, label]) => ({ value: unit, label }))).map((unit) => (
          <option value={unit.value} key={unit.value}>{unit.label}</option>
        ))}
      </select>
      <small>Salvo em {field.unit_label || field.unit}</small>
    </div>
  );
}

export function SettingControl({ field, value, onChange, options }: Props) {
  if (isEmojiField(field)) {
    return <input className="emoji-input" value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} placeholder="Ex: ⭐, 🌟 ou <:nome:id>" />;
  }

  if (field.type === "bool") {
    return (
      <button className={`toggle ${value ? "on" : ""}`} onClick={() => onChange(!value)} type="button" aria-pressed={Boolean(value)}>
        <span />
      </button>
    );
  }

  if (field.type === "choice") {
    if (!field.options.length) {
      return <input value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} placeholder="Digite o valor" />;
    }
    return (
      <select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
        {field.options.map((option) => (
          <option value={option.value} key={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }

  if (field.type === "channel" || field.type === "role") {
    const source = field.type === "channel" ? options?.channels : options?.roles;
    return (
      <select className="control" value={String(value ?? "")} onChange={(event) => onChange(event.target.value || null)}>
        <option value="">Nao definido</option>
        {source?.map((item) => (
          <option value={item.id} key={item.id}>
            {field.type === "channel" ? "# " : ""}{item.name} {item.type !== "role" ? `(${item.type})` : ""}
          </option>
        ))}
        {Boolean(value) && !source?.some((item) => item.id === String(value)) && (
          <option value={String(value)}>Nao encontrado: {String(value)}</option>
        )}
      </select>
    );
  }

  if (field.type === "role_multi") {
    const selected = Array.isArray(value) ? value.map(String) : [];
    const selectedRoles = options?.roles.filter((role) => selected.includes(role.id)) || [];
    const toggleRole = (roleId: string) => {
      onChange(selected.includes(roleId) ? selected.filter((id) => id !== roleId) : [...selected, roleId]);
    };
    return (
      <details className="multi-picker">
        <summary>
          {selectedRoles.length === 0 ? (
            <span className="muted-text">Padrao do bot</span>
          ) : (
            <span className="chip-line">
              {selectedRoles.slice(0, 3).map((role) => <span className="role-chip" key={role.id}>{role.name}</span>)}
              {selectedRoles.length > 3 && <span className="role-chip muted">+{selectedRoles.length - 3}</span>}
            </span>
          )}
        </summary>
        <div className="multi-menu">
          {options?.roles.map((role) => (
            <label className="check-row" key={role.id}>
              <input type="checkbox" checked={selected.includes(role.id)} onChange={() => toggleRole(role.id)} />
              <span className="role-dot" style={{ background: role.color || "#777" }} />
              <span>{role.name}</span>
            </label>
          ))}
        </div>
      </details>
    );
  }

  if (field.type === "number") {
    if (field.unit) {
      return <DurationControl field={field} value={value} onChange={onChange} options={options} />;
    }
    return (
      <input
        type="number"
        min="0"
        value={value == null ? "" : String(value)}
        onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))}
      />
    );
  }

  return <textarea value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} rows={3} />;
}

export function SearchInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="search-input">
      <Search size={16} />
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder="Buscar configuracao" />
    </label>
  );
}
