import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useUser } from "../state/UserContext";

export function ModelListPage() {
  const { user } = useUser();
  const canCreate = user.role === "admin" || user.role === "editor";
  const queryClient = useQueryClient();
  const { data: models, isLoading, error } = useQuery({ queryKey: ["models"], queryFn: api.listModels });

  const [name, setName] = useState("");
  const [yamlText, setYamlText] = useState("");
  const createMutation = useMutation({
    mutationFn: () => api.createModel({ name: name || undefined, yaml_text: yamlText }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["models"] });
      setName("");
      setYamlText("");
    },
  });

  return (
    <div className="stack">
      <h2>Models</h2>

      {isLoading && <p className="muted">Loading…</p>}
      {error && <p className="error">Failed to load models: {String(error)}</p>}

      {models && models.length === 0 && <p className="muted">No models yet.</p>}
      {models && models.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Owner</th>
              <th>Datasets</th>
              <th>Metrics</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.id}>
                <td>
                  <Link to={`/models/${m.id}`}>{m.name}</Link>
                </td>
                <td>{m.owner_username}</td>
                <td>{m.dataset_count}</td>
                <td>{m.metric_count}</td>
                <td className="muted">{new Date(m.updated_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {canCreate && (
        <div className="card">
          <h3>New model</h3>
          <div className="field-row">
            <label>Name (optional, defaults to the model's own name)</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field-row">
            <label>OSI YAML</label>
            <textarea
              rows={10}
              value={yamlText}
              onChange={(e) => setYamlText(e.target.value)}
              placeholder="Paste an OSI YAML document here"
            />
          </div>
          <button
            className="primary"
            disabled={!yamlText.trim() || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? "Creating…" : "Create model"}
          </button>
          {createMutation.isError && (
            <p className="error">
              {createMutation.error instanceof ApiError
                ? JSON.stringify(createMutation.error.detail)
                : String(createMutation.error)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
