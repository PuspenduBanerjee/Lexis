import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { ConnectionOut, ConnectionTestOut, ConnectionType } from "../api/types";
import { useUser } from "../state/UserContext";

interface ConfigField {
  key: string;
  label: string;
  required: boolean;
}

// Mirrors semantica_api/connection_runtime.py's _REQUIRED_CONFIG_KEYS/_OPTIONAL_CONFIG_KEYS.
const CONFIG_FIELDS: Record<ConnectionType, ConfigField[]> = {
  duckdb_file: [{ key: "path", label: "Path (resolved on the API server)", required: true }],
  snowflake: [
    { key: "account", label: "Account", required: true },
    { key: "user", label: "User", required: true },
    { key: "password_env", label: "Password env var name", required: true },
    { key: "warehouse", label: "Warehouse", required: false },
    { key: "database", label: "Database", required: false },
    { key: "schema", label: "Schema", required: false },
    { key: "role", label: "Role", required: false },
  ],
};

const emptyConfig = (type: ConnectionType): Record<string, string> =>
  Object.fromEntries(CONFIG_FIELDS[type].map((f) => [f.key, ""]));

export function ConnectionsPage() {
  const { user } = useUser();
  const canCreate = user.role === "admin" || user.role === "editor";
  const queryClient = useQueryClient();
  const { data: connections, isLoading, error } = useQuery({
    queryKey: ["connections"],
    queryFn: api.listConnections,
  });

  const [editing, setEditing] = useState<ConnectionOut | null>(null);
  const [testResults, setTestResults] = useState<Record<number, ConnectionTestOut>>({});
  const [testingId, setTestingId] = useState<number | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["connections"] });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteConnection(id),
    onSuccess: invalidate,
  });

  const runTest = async (id: number) => {
    setTestingId(id);
    try {
      const result = await api.testConnection(id);
      setTestResults((prev) => ({ ...prev, [id]: result }));
    } catch (e) {
      setTestResults((prev) => ({
        ...prev,
        [id]: { ok: false, detail: e instanceof ApiError ? String(e.detail) : String(e) },
      }));
    } finally {
      setTestingId(null);
    }
  };

  return (
    <div className="stack">
      <h2>Connections</h2>
      <p className="muted">
        Named, reusable datasource connections a model's "Run" tab can execute against, alongside the
        built-in demo dataset and one-off <code>.duckdb</code> uploads. Any user can view/test/run
        against any connection; only its owner (or an admin) can edit or delete it.
      </p>

      {isLoading && <p className="muted">Loading…</p>}
      {error && <p className="error">Failed to load connections: {String(error)}</p>}

      {connections && connections.length === 0 && <p className="muted">No connections yet.</p>}
      {connections && connections.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Owner</th>
              <th>Updated</th>
              <th>Test</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {connections.map((c) => {
              const canManage = user.role === "admin" || user.id === c.owner_id;
              const testResult = testResults[c.id];
              return (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td>{c.type}</td>
                  <td>{c.owner_username}</td>
                  <td className="muted">{new Date(c.updated_at).toLocaleString()}</td>
                  <td>
                    <div className="stack" style={{ gap: 4 }}>
                      <button onClick={() => runTest(c.id)} disabled={testingId === c.id}>
                        {testingId === c.id ? "Testing…" : "Test"}
                      </button>
                      {testResult && (
                        <span className={testResult.ok ? "muted" : "error"}>{testResult.detail}</span>
                      )}
                    </div>
                  </td>
                  <td>
                    {canManage && (
                      <div className="row">
                        <button onClick={() => setEditing(c)}>Edit</button>
                        <button
                          onClick={() => deleteMutation.mutate(c.id)}
                          disabled={deleteMutation.isPending}
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {(canCreate || editing) && (
        <ConnectionForm
          key={editing?.id ?? "create"}
          editing={editing}
          onDone={() => {
            setEditing(null);
            invalidate();
          }}
          onCancel={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function ConnectionForm({
  editing,
  onDone,
  onCancel,
}: {
  editing: ConnectionOut | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(editing?.name ?? "");
  const [type, setType] = useState<ConnectionType>(editing?.type ?? "duckdb_file");
  const [config, setConfig] = useState<Record<string, string>>(
    editing ? { ...emptyConfig(editing.type), ...editing.config } : emptyConfig("duckdb_file"),
  );

  const setConfigField = (key: string, value: string) => setConfig((prev) => ({ ...prev, [key]: value }));

  const changeType = (next: ConnectionType) => {
    setType(next);
    setConfig(emptyConfig(next));
  };

  const fields = CONFIG_FIELDS[type];
  const missingRequired = fields.some((f) => f.required && !config[f.key]?.trim());
  // Only send keys this type actually uses, and drop optional-but-blank ones so
  // they don't fail connection_runtime.validate_connection_config's unknown-key check.
  const buildConfig = () =>
    Object.fromEntries(fields.filter((f) => config[f.key]?.trim()).map((f) => [f.key, config[f.key].trim()]));

  const mutation = useMutation({
    mutationFn: () => {
      const body = { name, type, config: buildConfig() };
      return editing ? api.updateConnection(editing.id, body) : api.createConnection(body);
    },
    onSuccess: onDone,
  });

  return (
    <div className="card">
      <h3>{editing ? `Edit connection: ${editing.name}` : "New connection"}</h3>

      <div className="field-row">
        <label>Name</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </div>

      <div className="field-row">
        <label>Type</label>
        <select value={type} onChange={(e) => changeType(e.target.value as ConnectionType)}>
          <option value="duckdb_file">DuckDB file</option>
          <option value="snowflake">Snowflake</option>
        </select>
      </div>

      {fields.map((f) => (
        <div className="field-row" key={f.key}>
          <label>
            {f.label}
            {f.required ? " *" : " (optional)"}
          </label>
          <input
            type={f.key === "password_env" ? "text" : "text"}
            value={config[f.key] ?? ""}
            onChange={(e) => setConfigField(f.key, e.target.value)}
            placeholder={f.key === "password_env" ? "e.g. SNOWFLAKE_PASSWORD" : undefined}
          />
        </div>
      ))}
      {type === "snowflake" && (
        <p className="muted" style={{ marginTop: -8 }}>
          The password itself is never stored here — set the environment variable named above on the API
          server/container, and only its name goes in this form.
        </p>
      )}

      <div className="row">
        <button
          className="primary"
          disabled={!name.trim() || missingRequired || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Saving…" : editing ? "Save changes" : "Create connection"}
        </button>
        {editing && <button onClick={onCancel}>Cancel</button>}
      </div>

      {mutation.isError && (
        <p className="error">
          {mutation.error instanceof ApiError ? JSON.stringify(mutation.error.detail) : String(mutation.error)}
        </p>
      )}
    </div>
  );
}
