import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../../api/client";
import type { ModelDetailOut } from "../../api/types";

export function YamlEditor({ model }: { model: ModelDetailOut }) {
  const queryClient = useQueryClient();
  const [yamlText, setYamlText] = useState(model.raw_yaml);

  const saveMutation = useMutation({
    mutationFn: () => api.updateModel(model.id, { yaml_text: yamlText }),
    onSuccess: (updated) => {
      setYamlText(updated.raw_yaml);
      queryClient.invalidateQueries({ queryKey: ["models", model.id] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });

  const dirty = yamlText !== model.raw_yaml;

  return (
    <div className="stack">
      <div className="row">
        <button
          className="primary"
          disabled={!dirty || saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          {saveMutation.isPending ? "Saving…" : "Save YAML"}
        </button>
        {!dirty && saveMutation.isSuccess && <span className="muted">Saved.</span>}
        {dirty && <span className="muted">Unsaved changes</span>}
        {saveMutation.isError && (
          <span className="error">
            {saveMutation.error instanceof ApiError
              ? JSON.stringify(saveMutation.error.detail)
              : String(saveMutation.error)}
          </span>
        )}
      </div>
      <textarea
        rows={28}
        value={yamlText}
        onChange={(e) => setYamlText(e.target.value)}
        spellCheck={false}
      />
    </div>
  );
}
