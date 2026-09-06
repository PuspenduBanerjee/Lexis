"""Ossie -> Snowflake `CREATE SEMANTIC VIEW` DDL emitter.

Snowflake's native semantic view (Cortex Analyst) DDL groups a model into five
clauses - TABLES, RELATIONSHIPS, FACTS, DIMENSIONS, METRICS - which line up
closely with Ossie's own datasets/relationships/fields/metrics:

- Each OssieDataset becomes a TABLES entry (`<dataset> AS <source>`), carrying
  over PRIMARY KEY, WITH SYNONYMS (from ai_context), and COMMENT (description).
- Each OssieRelationship becomes a RELATIONSHIPS entry using Snowflake's
  `<alias> AS <from>(<cols>) REFERENCES <to>(<cols>)` shape.
- Ossie fields split into FACTS vs DIMENSIONS the same way the bundled TPC-DS
  fixture models it: a field carrying a `dimension` block is a grouping/
  filtering attribute (DIMENSIONS); a field with no `dimension` block is
  treated as a row-level numeric fact (FACTS), since Snowflake facts are the
  row-level building blocks aggregate METRICS are written against.
- Ossie semantic-model-level metrics become METRICS entries. Snowflake requires
  each metric to be qualified by a single table alias, so - as with the Cube
  emitter - a metric expression is attached to the first dataset it
  references (falling back to an arbitrary dataset if it references none).

Expressions prefer the SNOWFLAKE dialect where the source model provides one,
falling back to ANSI_SQL like every other target (`ResolvedModel.resolve_expression`).
"""

from lexis._vendor.ossie import OssieAIContext, OssieAIContextObject, OssieDialect
from lexis.resolved_model import ResolvedModel


def _quote_literal(text: str) -> str:
    return text.replace("'", "''")


def _synonyms_clause(ai_context: OssieAIContext | None) -> str:
    if isinstance(ai_context, OssieAIContextObject) and ai_context.synonyms:
        rendered = ", ".join(f"'{_quote_literal(s)}'" for s in ai_context.synonyms)
        return f" WITH SYNONYMS ({rendered})"
    return ""


def _comment_clause(text: str | None) -> str:
    return f" COMMENT = '{_quote_literal(text)}'" if text else ""


def _table_entries(model: ResolvedModel) -> list[str]:
    entries = []
    for name, dataset in model.datasets.items():
        entry = f"{name} AS {dataset.source}"
        if dataset.primary_key:
            entry += f" PRIMARY KEY ({', '.join(dataset.primary_key)})"
        entry += _synonyms_clause(dataset.ai_context)
        entry += _comment_clause(dataset.description)
        entries.append(entry)
    return entries


def _relationship_entries(model: ResolvedModel) -> list[str]:
    entries = []
    for rel in model.relationships:
        from_cols = ", ".join(rel.from_columns)
        to_cols = ", ".join(rel.to_columns)
        entries.append(
            f"{rel.name} AS {rel.from_dataset}({from_cols}) REFERENCES {rel.to}({to_cols})"
        )
    return entries


def _field_entries(model: ResolvedModel, *, dimensions: bool) -> list[str]:
    entries = []
    for dataset_name, dataset in model.datasets.items():
        for f in dataset.fields or []:
            if (f.dimension is not None) != dimensions:
                continue
            try:
                expr = model.resolve_expression(f.expression, OssieDialect.SNOWFLAKE)
            except Exception:
                continue
            entry = f"{dataset_name}.{f.name} AS {expr}"
            entry += _synonyms_clause(f.ai_context)
            entry += _comment_clause(f.description)
            entries.append(entry)
    return entries


def _metric_entries(model: ResolvedModel) -> list[str]:
    entries = []
    for metric in model.metrics.values():
        expr = model.resolve_expression(metric.expression, OssieDialect.SNOWFLAKE)
        referenced = model.referenced_datasets(expr)
        dataset_name = referenced[0] if referenced else next(iter(model.datasets))
        entry = f"{dataset_name}.{metric.name} AS {expr}"
        entry += _synonyms_clause(metric.ai_context)
        entry += _comment_clause(metric.description)
        entries.append(entry)
    return entries


def _clause(keyword: str, entries: list[str]) -> str:
    body = ",\n".join(f"    {entry}" for entry in entries)
    return f"  {keyword} (\n{body}\n  )"


def emit_snowflake_semantic_view(model: ResolvedModel) -> str:
    """Render `model` as a Snowflake `CREATE SEMANTIC VIEW` DDL statement."""
    clauses = [_clause("TABLES", _table_entries(model))]

    relationships = _relationship_entries(model)
    if relationships:
        clauses.append(_clause("RELATIONSHIPS", relationships))

    facts = _field_entries(model, dimensions=False)
    if facts:
        clauses.append(_clause("FACTS", facts))

    dims = _field_entries(model, dimensions=True)
    if dims:
        clauses.append(_clause("DIMENSIONS", dims))

    metrics = _metric_entries(model)
    if metrics:
        clauses.append(_clause("METRICS", metrics))

    lines = [f"CREATE OR REPLACE SEMANTIC VIEW {model.semantic_model.name}", *clauses]
    comment = _comment_clause(model.semantic_model.description).strip()
    if comment:
        lines.append(f"  {comment}")
    return "\n".join(lines) + ";\n"
