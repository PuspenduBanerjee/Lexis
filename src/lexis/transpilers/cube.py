"""Ossie -> Cube.js schema (YAML) emitter.

Cube models data as a set of "cubes" (one per table) with dimensions/measures/joins,
so the mapping from Ossie is direct for datasets/fields/relationships. Ossie metrics are
looser (arbitrary multi-dialect aggregate SQL, possibly spanning multiple datasets) than
Cube measures (per-cube, typically `type: sum/avg/...` over a single column), so:

- A metric matching the simple pattern `FUNC(dataset.column)` becomes a properly typed
  Cube measure (`type: sum|avg|count|min|max`) on that dataset's cube.
- Anything else (multi-column expressions, cross-dataset expressions like
  `customer_lifetime_value`) becomes a `type: number` measure carrying the raw SQL
  expression verbatim, attached to the metric's first referenced dataset's cube. Cube
  has no native concept of an ad-hoc cross-cube raw-SQL measure, so this is a
  best-effort placement users should review, not a guaranteed-correct Cube measure.
"""

import re

import yaml

from lexis._vendor.ossie import OssieDialect
from lexis.resolved_model import ResolvedModel

_SIMPLE_AGGREGATE_RE = re.compile(
    r"^(SUM|AVG|COUNT|MIN|MAX)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\)$",
    re.IGNORECASE,
)

_CUBE_MEASURE_TYPE = {
    "SUM": "sum",
    "AVG": "avg",
    "COUNT": "count",
    "MIN": "min",
    "MAX": "max",
}


def _cube_dimensions(model: ResolvedModel, dataset_name: str) -> list[dict]:
    dataset = model.datasets[dataset_name]
    dimensions = []
    for f in dataset.fields or []:
        try:
            expr = model.resolve_expression(f.expression, OssieDialect.ANSI_SQL)
        except Exception:
            continue
        is_time = f.is_time_dimension()
        dimensions.append(
            {
                "name": f.name,
                "sql": expr,
                "type": "time" if is_time else "string",
            }
        )
    return dimensions


def _cube_joins(model: ResolvedModel, dataset_name: str) -> list[dict]:
    joins = []
    for rel in model.relationships:
        if rel.from_dataset != dataset_name:
            continue
        conditions = " AND ".join(
            f"{{{rel.from_dataset}.{lc}}} = {{{rel.to}.{rc}}}"
            for lc, rc in zip(rel.from_columns, rel.to_columns)
        )
        joins.append(
            {"name": rel.to, "relationship": "many_to_one", "sql": conditions}
        )
    return joins


def emit_cube_yaml(model: ResolvedModel) -> str:
    """Render the full model as Cube.js schema YAML (one cube per dataset)."""
    cubes: dict[str, dict] = {}
    for name, dataset in model.datasets.items():
        cubes[name] = {
            "name": name,
            "sql_table": dataset.source,
            "joins": _cube_joins(model, name),
            "dimensions": _cube_dimensions(model, name),
            "measures": [{"name": "count", "type": "count"}],
        }

    for metric in model.metrics.values():
        expr = model.resolve_expression(metric.expression, OssieDialect.ANSI_SQL)
        match = _SIMPLE_AGGREGATE_RE.match(expr.strip())
        if match:
            func, dataset_name, column = match.groups()
            if dataset_name in cubes:
                cubes[dataset_name]["measures"].append(
                    {
                        "name": metric.name,
                        "sql": column,
                        "type": _CUBE_MEASURE_TYPE[func.upper()],
                        "description": metric.description,
                    }
                )
                continue

        referenced = model.referenced_datasets(expr)
        target_dataset = referenced[0] if referenced else next(iter(cubes))
        cubes[target_dataset]["measures"].append(
            {
                "name": metric.name,
                "sql": expr,
                "type": "number",
                "description": metric.description,
            }
        )

    for cube in cubes.values():
        if not cube["joins"]:
            del cube["joins"]
        cube["measures"] = [
            {k: v for k, v in m.items() if v is not None} for m in cube["measures"]
        ]

    doc = {"cubes": list(cubes.values())}
    return yaml.dump(doc, sort_keys=False, default_flow_style=False, allow_unicode=True)
