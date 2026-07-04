import type { RunDuckDbOut } from "../api/types";

export function ResultsTable({ result }: { result: RunDuckDbOut }) {
  return (
    <div className="stack">
      <table>
        <thead>
          <tr>
            {result.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>{String(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">{result.row_count} row(s)</p>
    </div>
  );
}
