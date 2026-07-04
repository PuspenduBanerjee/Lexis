import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { DatasetBrowser } from "../components/DatasetBrowser";
import { DuckDbRunPanel } from "../components/DuckDbRunPanel";
import { GraphEditor } from "../components/graph/GraphEditor";
import { YamlEditor } from "../components/graph/YamlEditor";
import { TranspileView } from "../components/TranspileView";
import { useUser } from "../state/UserContext";

type Tab = "browse" | "design" | "transpile" | "run";
type DesignMode = "graph" | "yaml";

export function ModelDetailPage() {
  const { id } = useParams<{ id: string }>();
  const modelId = Number(id);
  const { user } = useUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("browse");
  const [designMode, setDesignMode] = useState<DesignMode>("graph");

  const { data: model, isLoading, error } = useQuery({
    queryKey: ["models", modelId],
    queryFn: () => api.getModel(modelId),
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteModel(modelId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["models"] });
      navigate("/");
    },
  });

  if (isLoading) return <p className="muted">Loading…</p>;
  if (error || !model) return <p className="error">Failed to load model: {String(error)}</p>;

  const canManage = user.role === "admin" || user.id === model.owner_id;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <Link to="/">&larr; Models</Link>
          <h2>{model.name}</h2>
        </div>
        {canManage && (
          <button onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
            {deleteMutation.isPending ? "Deleting…" : "Delete model"}
          </button>
        )}
      </div>

      <div className="tabs">
        <button className={tab === "browse" ? "active" : ""} onClick={() => setTab("browse")}>
          Browse
        </button>
        {canManage && (
          <button className={tab === "design" ? "active" : ""} onClick={() => setTab("design")}>
            Design
          </button>
        )}
        <button className={tab === "transpile" ? "active" : ""} onClick={() => setTab("transpile")}>
          Transpile
        </button>
        <button className={tab === "run" ? "active" : ""} onClick={() => setTab("run")}>
          Run DuckDB
        </button>
      </div>

      {tab === "browse" && <DatasetBrowser model={model} />}
      {tab === "design" && canManage && (
        <div className="stack">
          <div className="row">
            <button className={designMode === "graph" ? "active" : ""} onClick={() => setDesignMode("graph")}>
              Graph
            </button>
            <button className={designMode === "yaml" ? "active" : ""} onClick={() => setDesignMode("yaml")}>
              YAML
            </button>
          </div>
          <p className="muted" style={{ margin: 0 }}>
            Switching between Graph and YAML discards unsaved changes in the view you're
            leaving — save first if you want to keep them.
          </p>
          {/* No `key` prop here on purpose: conditional rendering already unmounts
              the hidden one and mounts a fresh instance of the other on every
              switch, so each always starts from the latest `model` on entry. Adding
              a content-based key in addition would also force a remount right after
              a *self* save (raw_yaml changes -> key changes -> remount), wiping out
              the mutation's own success state before "Saved." is visible. */}
          {designMode === "graph" && <GraphEditor model={model} />}
          {designMode === "yaml" && <YamlEditor model={model} />}
        </div>
      )}
      {tab === "transpile" && <TranspileView model={model} />}
      {tab === "run" && <DuckDbRunPanel model={model} />}
    </div>
  );
}
