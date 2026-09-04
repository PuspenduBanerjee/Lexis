"""Index an OssieSemanticModel and resolve join paths / dialect expressions."""

import re
from collections import deque
from dataclasses import dataclass, field

from semantica._vendor.ossie import (
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
