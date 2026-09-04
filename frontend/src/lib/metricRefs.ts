// Mirrors `lexis.resolved_model.ResolvedModel.referenced_datasets`'s regex, so
// the canvas can compute a metric's dataset-reference edges live (as expressions are
// typed, or a metric is just added) instead of only after a save + model refetch.
const QUALIFIED_REF_RE = /\b([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_][A-Za-z0-9_]*\b/g;

/** Dataset names referenced as `dataset.column` qualifiers in `expression`, in
 * first-occurrence order, deduplicated, and filtered to `datasetNames`. */
export function referencedDatasets(expression: string, datasetNames: Set<string>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const match of expression.matchAll(QUALIFIED_REF_RE)) {
    const name = match[1];
    if (datasetNames.has(name) && !seen.has(name)) {
      seen.add(name);
      result.push(name);
    }
  }
  return result;
}
