import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
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

  const smlFolderInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    // `webkitdirectory` has no first-class React prop - set the DOM property
    // directly so the native file picker offers "choose a folder" instead of
    // individual files, while still yielding a flat FileList with each file's
    // relative path on `webkitRelativePath`.
    if (smlFolderInputRef.current) smlFolderInputRef.current.webkitdirectory = true;
  }, []);
  const [smlName, setSmlName] = useState("");
  const [smlFiles, setSmlFiles] = useState<FileList | null>(null);
  const importSmlMutation = useMutation({
    mutationFn: () => api.importSml(smlFiles!, smlName || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["models"] });
      setSmlName("");
      setSmlFiles(null);
      if (smlFolderInputRef.current) smlFolderInputRef.current.value = "";
    },
  });

  return (
    <div className="stack">
      <h2>Models</h2>

      {isLoading && <p className="muted">Loading…</p>}
      {error && <p className="error">Failed to load models: {String(error)}</p>}

      {models && models.length === 0 && <p className="muted">No models yet.</p>}
      {models && models.length > 0 && (
        <table className="data-table">
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
            <label>Ossie YAML</label>
            <textarea
              rows={10}
              value={yamlText}
              onChange={(e) => setYamlText(e.target.value)}
              placeholder="Paste an Ossie YAML document here"
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

      {canCreate && (
        <div className="card">
          <h3>Import from SML</h3>
          <p className="muted">
            Choose the root folder of an AtScale SML repo (catalog.yml, connections/,
            datasets/, dimensions/, metrics/, models/) - every *.yml file inside is
            parsed into a new Ossie model.
          </p>
          <div className="field-row">
            <label>Name (optional, defaults to the SML model's own name)</label>
            <input type="text" value={smlName} onChange={(e) => setSmlName(e.target.value)} />
          </div>
          <div className="field-row">
            <label>SML repo folder</label>
            <input
              ref={smlFolderInputRef}
              type="file"
              multiple
              onChange={(e) => setSmlFiles(e.target.files)}
            />
          </div>
          {smlFiles && <p className="muted">{smlFiles.length} file(s) selected.</p>}
          <button
            className="primary"
            disabled={!smlFiles || smlFiles.length === 0 || importSmlMutation.isPending}
            onClick={() => importSmlMutation.mutate()}
          >
            {importSmlMutation.isPending ? "Importing…" : "Import"}
          </button>
          {importSmlMutation.isError && (
            <p className="error">
              {importSmlMutation.error instanceof ApiError
                ? JSON.stringify(importSmlMutation.error.detail)
                : String(importSmlMutation.error)}
            </p>
          )}
          {importSmlMutation.data && (
            <div className="stack">
              <p>
                Imported <Link to={`/models/${importSmlMutation.data.model.id}`}>{importSmlMutation.data.model.name}</Link>.
              </p>
              {importSmlMutation.data.warnings.map((w, i) => (
                <p key={i} className="error">
                  warning: {w}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
