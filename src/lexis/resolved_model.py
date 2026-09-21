"""Index an OssieSemanticModel and resolve join paths / dialect expressions."""

import re
from collections import deque
from dataclasses import dataclass, field

from lexis._vendor.ossie import (
    OssieDataset,
    OssieDialect,
    OssieExpression,
    OssieMetric,
    OssieRelationship,
    OssieSemanticModel,
)

_QUALIFIED_REF_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_][A-Za-z0-9_]*\b")


class UnresolvedJoinError(ValueError):
    """Raised when a set of referenced datasets can't be connected via relationships."""


class MissingExpressionError(ValueError):
    """Raised when neither the requested dialect nor ANSI_SQL has an expression."""


@dataclass
class ResolvedModel:
    """Indexed view of an OssieSemanticModel: fast lookups + join-graph resolution."""

    semantic_model: OssieSemanticModel
    datasets: dict[str, OssieDataset] = field(default_factory=dict)
    metrics: dict[str, OssieMetric] = field(default_factory=dict)
    relationships: list[OssieRelationship] = field(default_factory=list)
    _adjacency: dict[str, list[tuple[str, OssieRelationship]]] = field(default_factory=dict)

    @classmethod
    def build(cls, semantic_model: OssieSemanticModel) -> "ResolvedModel":
        model = cls(semantic_model=semantic_model)
        for dataset in semantic_model.datasets:
            model.datasets[dataset.name] = dataset
        for metric in semantic_model.metrics or []:
            model.metrics[metric.name] = metric
        model.relationships = list(semantic_model.relationships or [])

        adjacency: dict[str, list[tuple[str, OssieRelationship]]] = {
            name: [] for name in model.datasets
        }
        for rel in model.relationships:
            adjacency.setdefault(rel.from_dataset, []).append((rel.to, rel))
            adjacency.setdefault(rel.to, []).append((rel.from_dataset, rel))
        model._adjacency = adjacency
        return model

    def referenced_datasets(self, expression: str) -> list[str]:
        """Datasets referenced as `dataset.column` qualifiers, in first-occurrence order."""
        seen: dict[str, None] = {}
        for match in _QUALIFIED_REF_RE.findall(expression):
            if match in self.datasets:
                seen[match] = None
        return list(seen)

    def join_path(self, dataset_names: list[str] | set[str]) -> list[OssieRelationship]:
        """Relationships connecting the given datasets: union of shortest paths from
        the root to each target dataset (not a full BFS spanning tree — irrelevant
        datasets that merely happen to be closer to the root than a target are not
        pulled in).

        The first element of `dataset_names` (order preserved for lists; arbitrary for
        sets) is used as the root, e.g. the base table in a generated FROM clause.
        """
        ordered = list(dict.fromkeys(dataset_names))
        if not ordered:
            return []
        for name in ordered:
            if name not in self.datasets:
                raise UnresolvedJoinError(f"Unknown dataset: {name!r}")

        root = ordered[0]
        targets = ordered[1:]
        if not targets:
            return []

        # BFS from root, recording the edge/predecessor used to first reach each node.
        predecessor_edge: dict[str, OssieRelationship] = {}
        predecessor_node: dict[str, str] = {}
        visited = {root}
        queue: deque[str] = deque([root])
        while queue:
            current = queue.popleft()
            for neighbor, rel in self._adjacency.get(current, []):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                predecessor_edge[neighbor] = rel
                predecessor_node[neighbor] = current
                queue.append(neighbor)

        missing = [t for t in targets if t not in visited]
        if missing:
            raise UnresolvedJoinError(
                f"No relationship path connects dataset(s) {missing} to {root!r}"
            )

        # Union the shortest root->target path edges, in root-to-leaf order, dedup'd.
        edges: list[OssieRelationship] = []
        added_nodes = {root}
        for target in targets:
            path_nodes: list[str] = []
            node = target
            while node not in added_nodes:
                path_nodes.append(node)
                node = predecessor_node[node]
            for n in reversed(path_nodes):
                edges.append(predecessor_edge[n])
                added_nodes.add(n)
        return edges

    def resolve_expression(self, expression: OssieExpression, dialect: OssieDialect) -> str:
        """Pick the expression text for `dialect`, falling back to ANSI_SQL."""
        by_dialect = {d.dialect: d.expression for d in expression.dialects}
        if dialect in by_dialect:
            return by_dialect[dialect]
        if OssieDialect.ANSI_SQL in by_dialect:
            return by_dialect[OssieDialect.ANSI_SQL]
        raise MissingExpressionError(
            f"No expression for dialect {dialect!r} or ANSI_SQL fallback"
        )

    def fact_datasets(self) -> set[str]:
        """Datasets that are always the "many" side of a relationship: a
        `from_dataset` somewhere, never a `to` anywhere. Everything else is a
        dimension - in a star/conformed-dimension schema, fact tables only ever
        originate a relationship and dimensions only ever receive one, so this is
        a reliable structural signal rather than a naming convention. Used to
        stop a metric's allowed `group_by` set from crossing into a different
        fact table's dimensions (see `reachable_dimensions`/`allowed_group_by_refs`),
        which is what let `total_revenue GROUP BY fct_store_returns.sr_reason`
        silently fan-trap through the shared `dim_date`."""
        from_names = {r.from_dataset for r in self.relationships}
        to_names = {r.to for r in self.relationships}
        return from_names - to_names

    def reachable_dimensions(self, fact: str) -> set[str]:
        """Dimensions reachable from `fact` via its own declared relationships,
        stopping at any other fact table - so a dimension shared with a
        *different* fact (e.g. `dim_date`, joined by both `fct_store_sales` and
        `fct_store_returns`) never pulls that other fact's own dimensions (e.g.
        `dim_promotion`, which only `fct_store_sales` reaches) into `fact`'s
        reachable set."""
        facts = self.fact_datasets()
        visited = {fact}
        dims: set[str] = set()
        queue: deque[str] = deque([fact])
        while queue:
            current = queue.popleft()
            for neighbor, _rel in self._adjacency.get(current, []):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                if neighbor in facts:
                    continue  # don't cross into (or through) another fact table
                dims.add(neighbor)
                queue.append(neighbor)
        return dims

    def allowed_group_by_refs(self, fact: str) -> list[str]:
        """`dataset.field` refs a metric whose home fact is `fact` may legally be
        grouped by: every field of `fact` itself, plus every field of every
        dimension reachable from it (see `reachable_dimensions`) - nothing from a
        different fact table, and nothing from a dimension only that other fact
        reaches.

        This is a *structural* safety guarantee (no fan-trap), not a field
        hygiene one - it still includes surrogate keys, raw measure columns, and
        PII fields indiscriminately; see TODO.md's "Metric group_by field
        hygiene" for that follow-up."""
        refs: list[str] = []
        for ds_name in [fact, *sorted(self.reachable_dimensions(fact))]:
            for f in self.datasets[ds_name].fields or []:
                refs.append(f"{ds_name}.{f.name}")
        return refs

    def metric_home_facts(self, metric_expr: str) -> list[str]:
        """The fact dataset(s) `metric_expr` (an already dialect-resolved metric
        expression) references, in first-occurrence order - `referenced_datasets`
        filtered down to just the facts (see `fact_datasets`). An ordinary metric
        has exactly one; a drill-across metric like `return_rate_pct` has two."""
        facts = self.fact_datasets()
        return [ds for ds in self.referenced_datasets(metric_expr) if ds in facts]

    def metric_allowed_group_by(self, metric_expr: str) -> list[str]:
        """`dataset.field` refs `metric_expr` may legally be grouped by: the
        intersection of `allowed_group_by_refs` for each of its home facts (see
        `metric_home_facts`). For an ordinary single-fact metric that's just its
        one fact's allowed set; for a drill-across metric spanning two facts,
        only what *both* facts can safely be grouped by (e.g. date/customer/item/
        store, never a dimension only one side reaches, like promotion for
        returns). Empty if the expression references no fact table at all."""
        home_facts = self.metric_home_facts(metric_expr)
        if not home_facts:
            return []
        allowed: set[str] | None = None
        for fact in home_facts:
            fact_allowed = set(self.allowed_group_by_refs(fact))
            allowed = fact_allowed if allowed is None else allowed & fact_allowed
        return sorted(allowed or set())

    def metric_aggregate_spans_multiple_facts(self, metric_expr: str) -> bool:
        """True if some *single* aggregate call's own arguments (e.g.
        `SUM(fct_store_sales.a - fct_store_returns.b)`) reference more than one
        fact table. Unlike a drill-across ratio (`SUM(returns.x) /
        NULLIF(SUM(sales.y), 0)`, where each aggregate call individually touches
        only one fact), this shape mixes two facts inside one aggregate - no
        single query can compute that correctly (it would have to fan-trap
        through whatever dimension connects them), so it must be rejected
        outright rather than routed through the drill-across path."""
        facts = self.fact_datasets()
        stack: list[int] = []
        for i, ch in enumerate(metric_expr):
            if ch == "(":
                stack.append(i)
            elif ch == ")" and stack:
                start = stack.pop()
                body = metric_expr[start + 1 : i]
                referenced = {ds for ds in self.referenced_datasets(body) if ds in facts}
                if len(referenced) > 1:
                    return True
        return False
