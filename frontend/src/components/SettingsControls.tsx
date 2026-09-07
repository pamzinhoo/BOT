import { Search } from "lucide-react";
import { DiscordOptions, SettingDefinition } from "../lib/api";

type Props = {
  field: SettingDefinition;
  value: unknown;
  onChange: (value: unknown) => void;
  options?: DiscordOptions;
};

export function SettingControl({ field, value, onChange, options }: Props) {
  if (field.type === "bool") {
    return (
      <button className={`toggle ${value ? "on" : ""}`} onClick={() => onChange(!value)} type="button" aria-pressed={Boolean(value)}>
        <span />
      </button>
    );
  }

  if (field.type === "choice") {
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
