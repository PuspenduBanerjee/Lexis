"""Shared SQL-dialect emitter: builds a metric query from a ResolvedModel.

Per-dialect subclasses only need to set `dialect` and `quote_char` — the join-graph
resolution, dialect-expression fallback, and SELECT/FROM/JOIN/GROUP BY assembly are
identical across warehouses (per Ossie's converters/index.md mapping guidance).
"""

import re

from semantica._vendor.ossie import OssieDialect
from semantica.resolved_model import ResolvedModel

_SIMPLE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SqlDialectEmitter:
    dialect: OssieDialect
    quote_char: str = '"'

    #: Grains supported by `emit_timeseries_query`, coarsest first.
    TIME_GRAINS = ("year", "quarter", "month", "day")

    def quote(self, identifier: str) -> str:
        return f"{self.quote_char}{identifier}{self.quote_char}"

    def _resolve_field_expr(self, model: ResolvedModel, dataset_name: str, field_name: str) -> str:
        dataset = model.datasets[dataset_name]
        matching = [f for f in (dataset.fields or []) if f.name == field_name]
        if not matching:
            raise ValueError(f"Unknown field {dataset_name}.{field_name!r}")
        field_expr = model.resolve_expression(matching[0].expression, self.dialect)
        # Field expressions (unlike metrics) are unqualified column refs/scalar
        # expressions scoped to their own dataset. Qualify the common case (a bare
        # column name) with the dataset alias; multi-column scalar expressions
        # (e.g. `first_name || ' ' || last_name`) are left as-is and rely on SQL's
        # automatic unambiguous-column resolution across the joined tables.
        if _SIMPLE_IDENTIFIER_RE.match(field_expr):
            field_expr = f"{self.quote(dataset_name)}.{field_expr}"
        return field_expr

    def _from_and_joins(self, model: ResolvedModel, all_datasets: list[str]) -> list[str]:
        """FROM + JOIN lines connecting `all_datasets` (first element is the base
        table); shared by `emit_metric_query` and `emit_timeseries_query` so the
        join-path traversal/direction logic only lives in one place."""
        joins = model.join_path(all_datasets)
        base_name = all_datasets[0]
        base_dataset = model.datasets[base_name]
        lines = [f"FROM {base_dataset.source} AS {self.quote(base_name)}"]

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

        return lines

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
            field_expr = self._resolve_field_expr(model, dataset_name, field_name)
            group_exprs.append(f"{field_expr} AS {self.quote(field_name)}")
            group_datasets.append(dataset_name)

        referenced = model.referenced_datasets(metric_expr)
        all_datasets = list(dict.fromkeys(referenced + group_datasets))
        if not all_datasets:
            raise ValueError(
                f"Metric {metric_name!r} expression references no known dataset"
            )

        select_list = [*group_exprs, f"{metric_expr} AS {self.quote(metric.name)}"]
        lines = [
            f"SELECT {', '.join(select_list)}",
            *self._from_and_joins(model, all_datasets),
        ]

        if group_exprs:
            positions = ", ".join(str(i + 1) for i in range(len(group_exprs)))
            lines.append(f"GROUP BY {positions}")

        return "\n".join(lines)

    def emit_timeseries_query(
        self,
        model: ResolvedModel,
        metric_name: str,
        time_dataset: str,
        time_field: str,
        grain: str,
        filter_grain: str | None = None,
        filter_value: str | None = None,
    ) -> str:
        """Render a SELECT grouping `metric_name` by `DATE_TRUNC(grain, time_field)`,
        optionally restricted to one coarser period (`filter_grain`/`filter_value`,
        an ISO `YYYY-MM-DD` date) - the drill-down case, where `filter_value` is the
        period boundary of the row the caller drilled into.

        Only meaningful for dialects that share Postgres-style
        `DATE_TRUNC('unit', expr)` syntax (DuckDB, Postgres, Databricks, Snowflake) -
        not BigQuery, which takes `DATE_TRUNC(expr, UNIT)` with no quoting.
        `grain`/`filter_grain` are validated against `TIME_GRAINS` and `filter_value`
        against a strict date-shaped regex before being embedded, since they're
        interpolated directly into the returned SQL text rather than bound as
        parameters (this method returns a fully-formed, displayable query, matching
        `emit_metric_query`'s contract).
        """
        if grain not in self.TIME_GRAINS:
            raise ValueError(f"Unsupported time grain: {grain!r}")

        metric = model.metrics[metric_name]
        metric_expr = model.resolve_expression(metric.expression, self.dialect)
        time_expr = self._resolve_field_expr(model, time_dataset, time_field)

        all_datasets = list(dict.fromkeys([*model.referenced_datasets(metric_expr), time_dataset]))

        period_expr = f"DATE_TRUNC('{grain}', {time_expr})"
        lines = [
            f"SELECT {period_expr} AS {self.quote('period')}, {metric_expr} AS {self.quote(metric.name)}",
            *self._from_and_joins(model, all_datasets),
        ]

        if filter_grain is not None:
            if filter_grain not in self.TIME_GRAINS:
                raise ValueError(f"Unsupported time grain: {filter_grain!r}")
            if not filter_value or not _ISO_DATE_RE.match(filter_value):
                raise ValueError(f"filter_value must be an ISO date (YYYY-MM-DD): {filter_value!r}")
            lines.append(f"WHERE DATE_TRUNC('{filter_grain}', {time_expr}) = DATE '{filter_value}'")

        lines.append("GROUP BY 1")
        lines.append("ORDER BY 1")
        return "\n".join(lines)
