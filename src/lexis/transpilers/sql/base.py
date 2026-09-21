"""Shared SQL-dialect emitter: builds a metric query from a ResolvedModel.

Per-dialect subclasses only need to set `dialect` and `quote_char` — the join-graph
resolution, dialect-expression fallback, and SELECT/FROM/JOIN/GROUP BY assembly are
identical across warehouses (per Ossie's converters/index.md mapping guidance).
"""

import re

from lexis._vendor.ossie import OssieDialect
from lexis.resolved_model import ResolvedModel

_SIMPLE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DATASET_COLUMN_SUM_RE = re.compile(
    r"^SUM\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\)$", re.IGNORECASE
)
_NULLIF_ZERO_RE = re.compile(r"^NULLIF\s*\(\s*(.+?)\s*,\s*0\s*\)$", re.IGNORECASE)
_SCALE_PREFIX_RE = re.compile(r"^[0-9.]+\s*\*\s*")


def _strip_scale_prefix(expr: str) -> str:
    """Remove a leading numeric-literal scale factor (`100.0 * `), if present -
    `return_rate_pct`-shaped metrics multiply a bare `SUM(fact.col)` by a percent
    scale, which `_DATASET_COLUMN_SUM_RE`'s anchored match otherwise can't see
    past. See `_decompose_cross_fact_ratio`."""
    return _SCALE_PREFIX_RE.sub("", expr, count=1)


def _split_top_level_slash(expr: str) -> tuple[str, str] | None:
    """Split `expr` on the first `/` that isn't nested inside parentheses."""
    depth = 0
    for i, ch in enumerate(expr):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "/" and depth == 0:
            return expr[:i], expr[i + 1 :]
    return None


def _decompose_cross_dataset_sum_ratio(
    expr: str,
) -> tuple[tuple[str, str, str], tuple[str, str]] | None:
    """Match `SUM(dsA.colA) / [NULLIF(]SUM(dsB.colB)[, 0)]` with `dsA != dsB` - the
    shape of a ratio whose denominator sums a *different* dataset's column, which
    is only correct once per row of that dataset (see
    `SqlDialectEmitter._try_emit_grain_safe_ratio_query`). A same-dataset ratio
    (e.g. `avg_selling_price`'s `SUM(fct.a) / NULLIF(SUM(fct.b), 0)`) isn't this
    shape and returns None, since both sides already aggregate at the same grain.

    Returns `((numerator_dataset, numerator_column, numerator_text), (denominator_dataset,
    denominator_column))` - `numerator_text` is the exact matched substring (not
    reconstructed), so callers can find-and-replace it verbatim regardless of the
    original expression's whitespace/casing.
    """
    split = _split_top_level_slash(expr.strip())
    if split is None:
        return None
    left, right = split[0].strip(), split[1].strip()

    left_match = _DATASET_COLUMN_SUM_RE.match(left)
    if not left_match:
        return None

    nullif_match = _NULLIF_ZERO_RE.match(right)
    right_inner = nullif_match.group(1).strip() if nullif_match else right
    right_match = _DATASET_COLUMN_SUM_RE.match(right_inner)
    if not right_match:
        return None

    numerator_dataset, numerator_column = left_match.group(1), left_match.group(2)
    denominator_dataset, denominator_column = right_match.group(1), right_match.group(2)
    if numerator_dataset == denominator_dataset:
        return None
    return (numerator_dataset, numerator_column, left), (denominator_dataset, denominator_column)


def _decompose_cross_fact_ratio(
    expr: str, facts: set[str]
) -> tuple[tuple[str, str, str], tuple[str, str, str]] | None:
    """Match `[K *] SUM(factA.colA) / [NULLIF(]SUM(factB.colB)[, 0)]` where
    `factA != factB` are both in `facts` (see `ResolvedModel.fact_datasets`) -
    the drill-across ratio shape `return_rate_pct` uses. Generalizes
    `_decompose_cross_dataset_sum_ratio` two ways: a leading numeric scale factor
    (`100.0 *`) is allowed on either side, and *both* sides must be fact tables
    (not one fact and one dimension - that's the other function's shape).

    Returns `((numerator_fact, numerator_column, numerator_text),
    (denominator_fact, denominator_column, denominator_text))` - each `_text` is
    the exact matched `SUM(...)` substring, scale factor and NULLIF wrapper
    excluded, so callers can find-and-replace just the aggregate call and leave
    the scale/NULLIF shell intact. None if `expr` isn't this shape."""
    split = _split_top_level_slash(expr.strip())
    if split is None:
        return None
    left, right = split[0].strip(), split[1].strip()

    left_stripped = _strip_scale_prefix(left)
    left_match = _DATASET_COLUMN_SUM_RE.match(left_stripped)
    if not left_match:
        return None

    nullif_match = _NULLIF_ZERO_RE.match(right)
    right_inner = nullif_match.group(1).strip() if nullif_match else right
    right_stripped = _strip_scale_prefix(right_inner)
    right_match = _DATASET_COLUMN_SUM_RE.match(right_stripped)
    if not right_match:
        return None

    num_dataset, num_column = left_match.group(1), left_match.group(2)
    den_dataset, den_column = right_match.group(1), right_match.group(2)
    if num_dataset == den_dataset or num_dataset not in facts or den_dataset not in facts:
        return None
    return (num_dataset, num_column, left_stripped), (den_dataset, den_column, right_stripped)


class SqlDialectEmitter:
    dialect: OssieDialect
    quote_char: str = '"'

    #: Grains supported by `emit_timeseries_query`, coarsest first. `week` is an
    #: ISO 8601 week (Monday start) - what `DATE_TRUNC('week', ...)` returns natively
    #: on DuckDB / Postgres / Snowflake (default `WEEK_START`) / Spark. A model whose
    #: business calendar uses a different week (e.g. US retail Sunday-Saturday) should
    #: say so in its `ai_context` so consumers interpret weekly rows accordingly.
    TIME_GRAINS = ("year", "quarter", "month", "week", "day")

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

    def _one_side_fk(self, model: ResolvedModel, many_dataset: str, one_dataset: str) -> str | None:
        """The single column on `many_dataset` that's a foreign key to `one_dataset`,
        *if* `one_dataset`'s own primary key is exactly the relationship's far-side
        column - i.e. `one_dataset` provably has one row per key value, so it's safe
        to join after collapsing `many_dataset` to that key's grain (see
        `_grain_safe_inner_query`). None if no such direct, single-column,
        provably-one-row-per-key relationship connects the two datasets."""
        one = model.datasets[one_dataset]
        if not one.primary_key or len(one.primary_key) != 1:
            return None
        for rel in model.relationships:
            if rel.from_dataset == many_dataset and rel.to == one_dataset:
                fk_cols, one_cols = rel.from_columns, rel.to_columns
            elif rel.from_dataset == one_dataset and rel.to == many_dataset:
                fk_cols, one_cols = rel.to_columns, rel.from_columns
            else:
                continue
            if len(fk_cols) == 1 and list(one_cols) == list(one.primary_key):
                return fk_cols[0]
        return None

    def _grain_safe_inner_query(
        self,
        model: ResolvedModel,
        fact_dataset: str,
        fact_col: str,
        dim_dataset: str,
        extra_specs: list[tuple[str, str, str]],
        where_clause: str | None = None,
    ) -> tuple[str, str, str]:
        """Pre-aggregation subquery for `_emit_grain_safe_ratio_query`/
        `_emit_grain_safe_ratio_timeseries_query`: `fact_dataset` collapsed to grain
        (its FK to `dim_dataset`, plus each `extra_specs` grouping expression),
        joining - *inside this subquery* - whatever dataset each `extra_specs` entry
        needs to compute its expression (e.g. `dim_item` for an `i_category`
        group-by, or a time dataset for a `DATE_TRUNC` period). Doing this here,
        before `dim_dataset` is joined at the final output grain, is what keeps that
        later join from re-introducing fan-out: grouping by the *raw foreign key*
        instead (e.g. `ss_item_sk`) would still let a store selling many items in the
        same category count its headcount once per item instead of once per category.

        `extra_specs` entries are `(dataset_to_join, select_expr, alias)` -
        `select_expr` must already be a dialect-quoted qualified reference (e.g. from
        `_resolve_field_expr`), and `dataset_to_join` is skipped if it's
        `fact_dataset` itself (already in scope, no join needed) or repeats an
        earlier entry's dataset (joined once, referenced by every column that needs
        it).

        Returns `(inner_sql, fact_fk_col, dim_key_col)`. Raises `ValueError` if
        `dim_dataset`, or any `extra_specs` dataset, doesn't join directly to
        `fact_dataset` via a single column that's provably one-row-per-key on that
        dataset's side (the only shape this rewrite knows how to keep safe) - a
        clear error instead of silently falling back to the fan-out-prone flat join.
        """
        fact_fk_col = self._one_side_fk(model, fact_dataset, dim_dataset)
        if fact_fk_col is None:
            raise ValueError(
                f"{dim_dataset!r} doesn't join directly to {fact_dataset!r} via a single column "
                f"matching {dim_dataset!r}'s own primary key, so this metric can't be computed "
                f"(it would double-count {dim_dataset}'s summed column)"
            )
        dim_key_col = model.datasets[dim_dataset].primary_key[0]

        fact_alias = self.quote(fact_dataset)
        joined: set[str] = set()
        extra_joins: list[str] = []
        for ds_name, _expr, _alias in extra_specs:
            if ds_name == fact_dataset or ds_name in joined:
                continue
            fk = self._one_side_fk(model, fact_dataset, ds_name)
            if fk is None:
                raise ValueError(
                    f"{ds_name!r} doesn't join directly to {fact_dataset!r} via a single column "
                    f"matching {ds_name!r}'s own primary key, so this metric can't be grouped by "
                    f"it (it would double-count {dim_dataset}'s summed column)"
                )
            ds_alias = self.quote(ds_name)
            ds_key_col = model.datasets[ds_name].primary_key[0]
            extra_joins.append(
                f"JOIN {model.datasets[ds_name].source} AS {ds_alias} "
                f"ON {fact_alias}.{fk} = {ds_alias}.{ds_key_col}"
            )
            joined.add(ds_name)

        numerator_alias = self.quote("__numerator")
        select_cols = [f"{fact_alias}.{fact_fk_col}", *[f"{expr} AS {alias}" for _, expr, alias in extra_specs]]
        positions = ", ".join(str(i + 1) for i in range(len(select_cols)))
        lines = [
            f"SELECT {', '.join(select_cols)}, SUM({fact_alias}.{fact_col}) AS {numerator_alias}",
            f"FROM {model.datasets[fact_dataset].source} AS {fact_alias}",
            *extra_joins,
        ]
        if where_clause is not None:
            lines.append(f"WHERE {where_clause}")
        lines.append(f"GROUP BY {positions}")
        return "\n".join(lines), fact_fk_col, dim_key_col

    def _emit_grain_safe_ratio_query(
        self,
        model: ResolvedModel,
        metric_name: str,
        metric_expr: str,
        ratio: tuple[tuple[str, str, str], tuple[str, str]],
        group_by: list[str],
    ) -> str:
        """Two-level query for a `SUM(fact.col) / [NULLIF(]SUM(dim.col)[, 0)]` metric
        (see `_decompose_cross_dataset_sum_ratio`/`_grain_safe_inner_query`), used by
        `emit_metric_query` instead of its usual flat join whenever `metric_expr`
        matches that shape. `group_by` entries on `dim` itself are resolved against
        the outer join to `dim` (already grain-safe: `dim` is joined once per
        distinct row); every other `group_by` dataset is resolved *inside* the inner
        pre-aggregation instead, so `dim`'s column is summed once per distinct value
        of that grouping - not once per row of whatever finer-grained dataset the
        grouping attribute happens to live on."""
        (fact_dataset, fact_col, numerator_text), (dim_dataset, _dim_col) = ratio

        extra_specs: list[tuple[str, str, str]] = []
        outer_group_cols: list[tuple[str | None, str]] = []  # (inner alias, field_name)
        for ref in group_by:
            ds_name, field_name = ref.split(".", 1)
            if ds_name == dim_dataset:
                outer_group_cols.append((None, field_name))
            else:
                field_expr = self._resolve_field_expr(model, ds_name, field_name)
                alias = self.quote(f"__group_{len(extra_specs)}")
                extra_specs.append((ds_name, field_expr, alias))
                outer_group_cols.append((alias, field_name))

        inner_sql, fact_fk_col, dim_key_col = self._grain_safe_inner_query(
            model, fact_dataset, fact_col, dim_dataset, extra_specs
        )

        base_alias = self.quote("__base")
        numerator_alias = self.quote("__numerator")
        dim_alias = self.quote(dim_dataset)
        from_lines = [
            f"FROM ({inner_sql}) AS {base_alias}",
            f"JOIN {model.datasets[dim_dataset].source} AS {dim_alias} "
            f"ON {base_alias}.{fact_fk_col} = {dim_alias}.{dim_key_col}",
        ]

        group_exprs: list[str] = []
        for inner_alias, field_name in outer_group_cols:
            if inner_alias is None:
                field_expr = self._resolve_field_expr(model, dim_dataset, field_name)
                group_exprs.append(f"{field_expr} AS {self.quote(field_name)}")
            else:
                group_exprs.append(f"{base_alias}.{inner_alias} AS {self.quote(field_name)}")

        outer_metric_expr = metric_expr.replace(numerator_text, f"SUM({base_alias}.{numerator_alias})", 1)
        select_list = [*group_exprs, f"{outer_metric_expr} AS {self.quote(metric_name)}"]
        lines = [f"SELECT {', '.join(select_list)}", *from_lines]
        if group_exprs:
            positions = ", ".join(str(i + 1) for i in range(len(group_exprs)))
            lines.append(f"GROUP BY {positions}")
        return "\n".join(lines)

    def _emit_grain_safe_ratio_timeseries_query(
        self,
        model: ResolvedModel,
        metric_name: str,
        metric_expr: str,
        ratio: tuple[tuple[str, str, str], tuple[str, str]],
        time_dataset: str,
        time_field: str,
        grain: str,
        filter_grain: str | None,
        filter_value: str | None,
    ) -> str:
        """`emit_timeseries_query`'s counterpart to `_emit_grain_safe_ratio_query`:
        the period bucket (`DATE_TRUNC(grain, time_field)`) is computed *inside* the
        inner pre-aggregation (joining `time_dataset` there, same as any other extra
        group-by attribute), so `dim`'s column is summed once per distinct store per
        period - not once per sales line, which is what the plain flat join in
        `emit_timeseries_query` would otherwise do for this metric shape. A
        drill-down filter (`filter_grain`/`filter_value`) is applied as a `WHERE` on
        that same inner query, before the pre-aggregation, matching how
        `emit_timeseries_query` applies it at the (single-level) flat-query grain."""
        (fact_dataset, fact_col, numerator_text), (dim_dataset, _dim_col) = ratio

        time_expr = self._resolve_field_expr(model, time_dataset, time_field)
        period_alias = self.quote("__period")
        extra_specs = [(time_dataset, f"DATE_TRUNC('{grain}', {time_expr})", period_alias)]

        where_clause = None
        if filter_grain is not None:
            if filter_grain not in self.TIME_GRAINS:
                raise ValueError(f"Unsupported time grain: {filter_grain!r}")
            if not filter_value or not _ISO_DATE_RE.match(filter_value):
                raise ValueError(f"filter_value must be an ISO date (YYYY-MM-DD): {filter_value!r}")
            where_clause = f"DATE_TRUNC('{filter_grain}', {time_expr}) = DATE '{filter_value}'"

        inner_sql, fact_fk_col, dim_key_col = self._grain_safe_inner_query(
            model, fact_dataset, fact_col, dim_dataset, extra_specs, where_clause=where_clause
        )

        base_alias = self.quote("__base")
        numerator_alias = self.quote("__numerator")
        dim_alias = self.quote(dim_dataset)
        outer_metric_expr = metric_expr.replace(numerator_text, f"SUM({base_alias}.{numerator_alias})", 1)
        lines = [
            f"SELECT {base_alias}.{period_alias} AS {self.quote('period')}, "
            f"{outer_metric_expr} AS {self.quote(metric_name)}",
            f"FROM ({inner_sql}) AS {base_alias}",
            f"JOIN {model.datasets[dim_dataset].source} AS {dim_alias} "
            f"ON {base_alias}.{fact_fk_col} = {dim_alias}.{dim_key_col}",
            "GROUP BY 1",
            "ORDER BY 1",
        ]
        return "\n".join(lines)

    def _fact_group_subquery(
        self,
        model: ResolvedModel,
        fact: str,
        agg_col: str,
        group_by: list[str],
        time_axis: tuple[str, str, str] | None,
        filter_grain: str | None,
        filter_value: str | None,
    ) -> tuple[str, list[str], str]:
        """One fact's side of a drill-across query (see `_emit_drill_across_query`):
        `fact` collapsed to the requested `group_by` grain - joining, *inside this
        subquery*, whatever dimension each field belongs to (same reasoning as
        `_grain_safe_inner_query`: grouping by a raw foreign key instead of the
        resolved attribute would still let a shared attribute value fan out) -
        plus a `DATE_TRUNC` period column when `time_axis` is given. A drill-down
        filter (`filter_grain`/`filter_value`) applies as a `WHERE` here, before
        this fact's own aggregation.

        Returns `(sql, group_col_aliases, agg_alias)` - `group_col_aliases` in
        `group_by` order (period last, if any), so the caller can pair them up
        with the *other* fact's same-shaped subquery for a null-safe FULL OUTER
        JOIN (`IS NOT DISTINCT FROM`, not `=`, since e.g. `d_holiday_name` is NULL
        for most days and those NULLs must still match each other)."""
        fact_alias = self.quote(fact)
        joins: list[str] = []
        joined: set[str] = set()

        def _ensure_joined(ds_name: str) -> None:
            if ds_name == fact or ds_name in joined:
                return
            fk = self._one_side_fk(model, fact, ds_name)
            if fk is None:
                raise ValueError(
                    f"{ds_name!r} doesn't join directly to {fact!r} via a single column "
                    f"matching {ds_name!r}'s own primary key, so this drill-across metric "
                    f"can't be grouped by it"
                )
            ds_alias = self.quote(ds_name)
            ds_key_col = model.datasets[ds_name].primary_key[0]
            joins.append(
                f"JOIN {model.datasets[ds_name].source} AS {ds_alias} "
                f"ON {fact_alias}.{fk} = {ds_alias}.{ds_key_col}"
            )
            joined.add(ds_name)

        select_cols: list[str] = []
        aliases: list[str] = []
        for i, ref in enumerate(group_by):
            ds_name, field_name = ref.split(".", 1)
            _ensure_joined(ds_name)
            field_expr = self._resolve_field_expr(model, ds_name, field_name)
            alias = self.quote(f"__key_{i}")
            select_cols.append(f"{field_expr} AS {alias}")
            aliases.append(alias)

        where_clause = None
        if time_axis is not None:
            time_dataset, time_field, grain = time_axis
            _ensure_joined(time_dataset)
            time_expr = self._resolve_field_expr(model, time_dataset, time_field)
            period_alias = self.quote("__period")
            select_cols.append(f"DATE_TRUNC('{grain}', {time_expr}) AS {period_alias}")
            aliases.append(period_alias)

            if filter_grain is not None:
                if filter_grain not in self.TIME_GRAINS:
                    raise ValueError(f"Unsupported time grain: {filter_grain!r}")
                if not filter_value or not _ISO_DATE_RE.match(filter_value):
                    raise ValueError(f"filter_value must be an ISO date (YYYY-MM-DD): {filter_value!r}")
                where_clause = f"DATE_TRUNC('{filter_grain}', {time_expr}) = DATE '{filter_value}'"

        agg_alias = self.quote("__agg")
        select_list = [*select_cols, f"SUM({fact_alias}.{agg_col}) AS {agg_alias}"]
        lines = [
            f"SELECT {', '.join(select_list)}",
            f"FROM {model.datasets[fact].source} AS {fact_alias}",
            *joins,
        ]
        if where_clause is not None:
            lines.append(f"WHERE {where_clause}")
        if aliases:
            positions = ", ".join(str(i + 1) for i in range(len(aliases)))
            lines.append(f"GROUP BY {positions}")
        return "\n".join(lines), aliases, agg_alias

    def _emit_drill_across_query(
        self,
        model: ResolvedModel,
        metric_name: str,
        metric_expr: str,
        home_facts: list[str],
        group_by: list[str],
        time_axis: tuple[str, str, str] | None = None,
        filter_grain: str | None = None,
        filter_value: str | None = None,
    ) -> str:
        """A metric whose expression spans two fact tables (e.g. `return_rate_pct`
        = returns / sales) can't be computed by one flat join - `fct_store_sales`
        and `fct_store_returns` only connect through shared dimensions
        (`dim_date`, ...), and joining both facts directly to those dimensions in
        one query fan-traps (each sales row multiplies against every matching
        return row and vice versa - the exact bug this rewrite exists to avoid).

        Instead: aggregate each fact to the requested grain independently (see
        `_fact_group_subquery` - each is a normal single-fact query), then
        combine the two *already-aggregated* one-row-per-group results with a
        `FULL OUTER JOIN` on the (null-safe) group keys, so every group that
        exists in *either* fact gets a row, and the ratio is computed from there:
        a group with sales but no returns gets a real 0 on the returns side (`0 /
        sales` = 0.0); a group with returns but no sales gets `NULLIF`'d to NULL
        on the sales side (`returns / NULL` = NULL) - not silently dropped or
        multiplied, either way."""
        facts = model.fact_datasets()
        ratio = _decompose_cross_fact_ratio(metric_expr, facts)
        if ratio is None:
            raise ValueError(
                f"Metric {metric_name!r} spans multiple fact tables ({', '.join(home_facts)}) "
                f"but isn't a supported drill-across shape - only `[K *] SUM(factA.col) / "
                f"[NULLIF(]SUM(factB.col)[, 0)]` is supported today"
            )
        (num_fact, num_col, num_text), (den_fact, den_col, den_text) = ratio

        num_sql, num_aliases, num_agg_alias = self._fact_group_subquery(
            model, num_fact, num_col, group_by, time_axis, filter_grain, filter_value
        )
        den_sql, den_aliases, den_agg_alias = self._fact_group_subquery(
            model, den_fact, den_col, group_by, time_axis, filter_grain, filter_value
        )

        num_alias = self.quote("__num")
        den_alias = self.quote("__den")
        on_parts = [
            f"{num_alias}.{a} IS NOT DISTINCT FROM {den_alias}.{b}"
            for a, b in zip(num_aliases, den_aliases)
        ]
        on_clause = " AND ".join(on_parts) if on_parts else "1 = 1"

        key_pairs = list(zip(num_aliases, den_aliases))
        if time_axis is not None:
            *key_pairs, period_pair = key_pairs  # period is always last, per _fact_group_subquery

        select_cols = []
        if time_axis is not None:
            period_num, period_den = period_pair
            select_cols.append(f"COALESCE({num_alias}.{period_num}, {den_alias}.{period_den}) AS {self.quote('period')}")
        for (na, da), ref in zip(key_pairs, group_by):
            field_name = ref.split(".", 1)[1]
            select_cols.append(f"COALESCE({num_alias}.{na}, {den_alias}.{da}) AS {self.quote(field_name)}")

        outer_num_expr = f"COALESCE({num_alias}.{num_agg_alias}, 0)"
        outer_den_expr = f"COALESCE({den_alias}.{den_agg_alias}, 0)"
        outer_metric_expr = metric_expr.replace(num_text, outer_num_expr, 1).replace(den_text, outer_den_expr, 1)

        select_cols.append(f"{outer_metric_expr} AS {self.quote(metric_name)}")
        lines = [
            f"SELECT {', '.join(select_cols)}",
            f"FROM ({num_sql}) AS {num_alias}",
            f"FULL OUTER JOIN ({den_sql}) AS {den_alias} ON {on_clause}",
        ]
        if time_axis is not None:
            lines.append("ORDER BY 1")
        return "\n".join(lines)

    def _validate_metric_query(
        self, model: ResolvedModel, metric_name: str, metric_expr: str, group_by: list[str]
    ) -> None:
        """Shared enforcement point for every query path (REST `/run`, per-model
        MCP, workspace MCP, WebMCP - they all funnel through `emit_metric_query`/
        `emit_timeseries_query`): reject a metric whose single aggregate spans
        multiple fact tables outright (see
        `ResolvedModel.metric_aggregate_spans_multiple_facts`), and reject any
        `group_by` ref outside the metric's allowed set (see
        `ResolvedModel.metric_allowed_group_by`) with a clear error naming the
        metric, the rejected field, and the valid dataset prefixes - instead of
        silently fan-trapping through a shared dimension (e.g.
        `total_revenue GROUP BY fct_store_returns.sr_reason`, which used to
        inflate to 1.65x the true total)."""
        if model.metric_aggregate_spans_multiple_facts(metric_expr):
            raise ValueError(
                f"Metric {metric_name!r} has a single aggregate whose arguments span more "
                f"than one fact table - combine separate per-fact aggregates instead (e.g. "
                f"a ratio like return_rate_pct), each touching only one fact"
            )
        if not group_by:
            return
        allowed = set(model.metric_allowed_group_by(metric_expr))
        for ref in group_by:
            if ref not in allowed:
                valid_datasets = sorted({r.split(".", 1)[0] for r in allowed})
                raise ValueError(
                    f"Metric {metric_name!r} can't be grouped by {ref!r} - valid group_by "
                    f"datasets for this metric: {', '.join(valid_datasets) or '(none)'}"
                )

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
        group_by = group_by or []

        self._validate_metric_query(model, metric_name, metric_expr, group_by)

        home_facts = model.metric_home_facts(metric_expr)
        if len(home_facts) > 1:
            return self._emit_drill_across_query(model, metric.name, metric_expr, home_facts, group_by)

        ratio = _decompose_cross_dataset_sum_ratio(metric_expr)
        if ratio is not None:
            return self._emit_grain_safe_ratio_query(model, metric.name, metric_expr, ratio, group_by)

        group_exprs: list[str] = []
        group_datasets: list[str] = []
        for ref in group_by:
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

        self._validate_metric_query(model, metric_name, metric_expr, [])

        home_facts = model.metric_home_facts(metric_expr)
        if len(home_facts) > 1:
            return self._emit_drill_across_query(
                model, metric.name, metric_expr, home_facts, [],
                time_axis=(time_dataset, time_field, grain),
                filter_grain=filter_grain, filter_value=filter_value,
            )

        ratio = _decompose_cross_dataset_sum_ratio(metric_expr)
        if ratio is not None:
            return self._emit_grain_safe_ratio_timeseries_query(
                model, metric.name, metric_expr, ratio,
                time_dataset, time_field, grain, filter_grain, filter_value,
            )

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
