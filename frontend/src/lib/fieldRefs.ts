import type { ModelDetailOut } from "../api/types";

/** All "dataset.field" refs across a model, for group-by pickers. */
export function fieldRefs(model: ModelDetailOut): string[] {
  return model.datasets.flatMap((d) => d.fields.map((f) => `${d.name}.${f.name}`));
}
