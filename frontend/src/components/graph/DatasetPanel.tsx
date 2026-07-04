import type { GraphDatasetIn, GraphFieldIn } from "../../api/types";

interface Props {
  dataset: GraphDatasetIn;
  onChange: (updated: GraphDatasetIn) => void;
  onDelete: () => void;
}

export function DatasetPanel({ dataset, onChange, onDelete }: Props) {
  const updateField = (index: number, patch: Partial<GraphFieldIn>) => {
    const fields = dataset.fields.map((f, i) => (i === index ? { ...f, ...patch } : f));
    onChange({ ...dataset, fields });
  };

  const removeField = (index: number) => {
    onChange({ ...dataset, fields: dataset.fields.filter((_, i) => i !== index) });
  };

  const addField = () => {
    const name = window.prompt("New field name (must be a unique column/expression name)");
    if (!name) return;
    onChange({ ...dataset, fields: [...dataset.fields, { name, expression: name, description: null }] });
  };

  return (
    <div className="card stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{dataset.name}</strong>
        <button onClick={onDelete}>Delete dataset</button>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        Name can't be changed after creation (it's the join-key other relationships reference).
      </p>

      <div className="field-row">
        <label>Source (database.schema.table)</label>
        <input
          type="text"
          value={dataset.source}
          onChange={(e) => onChange({ ...dataset, source: e.target.value })}
        />
      </div>

      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <label>Fields</label>
          <button onClick={addField}>+ Add field</button>
        </div>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Expression</th>
              <th>Description</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {dataset.fields.map((f, i) => (
              <tr key={i}>
                <td>
                  <input
                    type="text"
                    value={f.name}
                    onChange={(e) => updateField(i, { name: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    value={f.expression}
                    onChange={(e) => updateField(i, { expression: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    value={f.description ?? ""}
                    onChange={(e) => updateField(i, { description: e.target.value || null })}
                  />
                </td>
                <td>
                  <button onClick={() => removeField(i)}>&times;</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
