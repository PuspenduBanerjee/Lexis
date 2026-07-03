"""Shared SQL-dialect emitter: builds a metric query from a ResolvedModel.

Per-dialect subclasses only need to set `dialect` and `quote_char` — the join-graph
resolution, dialect-expression fallback, and SELECT/FROM/JOIN/GROUP BY assembly are
identical across warehouses (per OSI's converters/index.md mapping guidance).
"""

import re

from semantica._vendor.osi import OSIDialect
from semantica.resolved_model import ResolvedModel

_SIMPLE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SqlDialectEmitter:
    dialect: OSIDialect
    quote_char: str = '"'

    def quote(self, identifier: str) -> str:
        return f"{self.quote_char}{identifier}{self.quote_char}"

    def emit_metric_query(
        self,
        model: ResolvedModel,
        metric_name: str,
        group_by: list[str] | None = None,
    ) -> str:
        """Render a runnable SELECT for `metric_name`, optionally grouped by field refs.

        `group_by` entries are `"dataset.field"` references, e.g. `"item.i_category"`.
        """
        metric = model.metrics[metric_name]
        metric_expr = model.resolve_expression(metric.expression, self.dialect)

        group_exprs: list[str] = []
        group_datasets: list[str] = []
        for ref in group_by or []:
            dataset_name, field_name = ref.split(".", 1)
            dataset = model.datasets[dataset_name]
            matching = [f for f in (dataset.fields or []) if f.name == field_name]
            if not matching:
                raise ValueError(f"Unknown field {ref!r}")
            field_expr = model.resolve_expression(matching[0].expression, self.dialect)
            # Field expressions (unlike metrics) are unqualified column refs/scalar
            # expressions scoped to their own dataset. Qualify the common case (a bare
            # column name) with the dataset alias; multi-column scalar expressions
            # (e.g. `first_name || ' ' || last_name`) are left as-is and rely on SQL's
            # automatic unambiguous-column resolution across the joined tables.
            if _SIMPLE_IDENTIFIER_RE.match(field_expr):
                field_expr = f"{self.quote(dataset_name)}.{field_expr}"
            group_exprs.append(f"{field_expr} AS {self.quote(field_name)}")
            group_datasets.append(dataset_name)

        referenced = model.referenced_datasets(metric_expr)
        all_datasets = list(dict.fromkeys(referenced + group_datasets))
        if not all_datasets:
            raise ValueError(
                f"Metric {metric_name!r} expression references no known dataset"
            )

        joins = model.join_path(all_datasets)
        base_name = all_datasets[0]
        base_dataset = model.datasets[base_name]

        select_list = [*group_exprs, f"{metric_expr} AS {self.quote(metric.name)}"]
        lines = [
            f"SELECT {', '.join(select_list)}",
            f"FROM {base_dataset.source} AS {self.quote(base_name)}",
        ]

        joined = {base_name}
        for rel in joins:
            if rel.from_dataset in joined and rel.to not in joined:
                left, right, left_cols, right_cols = (
                    rel.from_dataset,
                    rel.to,
                    rel.from_columns,
                    rel.to_columns,
                )
            else:
                left, right, left_cols, right_cols = (
                    rel.to,
                    rel.from_dataset,
                    rel.to_columns,
                    rel.from_columns,
                )

            right_dataset = model.datasets[right]
            on_clause = " AND ".join(
                f"{self.quote(left)}.{lc} = {self.quote(right)}.{rc}"
                for lc, rc in zip(left_cols, right_cols)
            )
            lines.append(
                f"JOIN {right_dataset.source} AS {self.quote(right)} ON {on_clause}"
            )
            joined.add(right)

        if group_exprs:
            positions = ", ".join(str(i + 1) for i in range(len(group_exprs)))
            lines.append(f"GROUP BY {positions}")

        return "\n".join(lines)
