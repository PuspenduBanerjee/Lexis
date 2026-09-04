import type { ModelDetailOut } from "../api/types";

export function DatasetBrowser({ model }: { model: ModelDetailOut }) {
  return (
    <div className="stack">
      <section>
        <h3>Datasets</h3>
        {model.datasets.map((d) => (
          <div className="card" key={d.name}>
            <strong>{d.name}</strong> <span className="muted">({d.source})</span>
            <table className="data-table">
              <tbody>
                {d.fields.map((f) => (
                  <tr key={f.name}>
                    <td>
                      <code>{f.name}</code>
                    </td>
                    <td className="muted">{f.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </section>

      <section>
        <h3>Relationships</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>From</th>
              <th>To</th>
            </tr>
          </thead>
          <tbody>
            {model.relationships.map((r) => (
              <tr key={r.name}>
                <td>{r.name}</td>
                <td>
                  {r.from_dataset}.{r.from_columns.join(", ")}
                </td>
                <td>
                  {r.to}.{r.to_columns.join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h3>Metrics</h3>
        <table className="data-table">
          <tbody>
            {model.metrics.map((m) => (
              <tr key={m.name}>
                <td>
                  <code>{m.name}</code>
                </td>
                <td className="muted">{m.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
