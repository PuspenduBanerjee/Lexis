"""Framework-free round-trip property generation + assertions for the Ossie <->
SML converter (src/lexis/sml/). Shared by test_sml_roundtrip_properties.py
(Hypothesis-backed) and test_sml_roundtrip_properties_seeded.py (plain seeded
`random.Random`-backed), so the exact same logic runs whether or not
`hypothesis` is installed - mirrors
third_party/ossie/converters/databricks/tests/_roundtrip_helpers.py's `Rnd`
interface and file split.

Generates strictly within the v1 "documented supported subset" (no
calculation_groups, row_security, or anything else emit.py/parse.py don't
interpret functionally) - this exercises the round-trippable core across many
random shapes; the stash / no-silent-loss paths for what's *outside* that
subset are covered directly, by hand, in test_sml_roundtrip.py.
"""

from __future__ import annotations

import random
import tempfile
from pathlib import Path
from typing import Any, Protocol

from lexis._vendor.ossie import OssieDocument
from lexis.sml.emit import emit_sml_files
from lexis.sml.parse import parse_sml_repo

_AGG_FUNCS = ("SUM", "AVG", "COUNT", "MIN", "MAX")
_ALPHANUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_IDENT_CHARS = "abcdefghijklmnopqrstuvwxyz_"


class Rnd(Protocol):
    def chance(self, p: float = 0.5) -> bool: ...
    def count(self, lo: int, hi: int) -> int: ...
    def pick(self, seq): ...
    def text(self) -> str: ...
    def colname(self) -> str: ...


class RandomRnd:
    """The `Rnd` interface backed by a plain seeded `random.Random`."""

    def __init__(self, seed: int) -> None:
        self._r = random.Random(seed)

    def chance(self, p: float = 0.5) -> bool:
        return self._r.random() < p

    def count(self, lo: int, hi: int) -> int:
        return self._r.randint(lo, hi)

    def pick(self, seq):
        return self._r.choice(list(seq))

    def text(self) -> str:
        return "".join(self._r.choice(_ALPHANUM) for _ in range(self._r.randint(1, 10)))

    def colname(self) -> str:
        return "".join(self._r.choice(_IDENT_CHARS) for _ in range(self._r.randint(1, 8)))


def _unique(existing: set[str], factory) -> str:
    for _ in range(50):
        candidate = factory()
        if candidate not in existing:
            existing.add(candidate)
            return candidate
    # Degenerate case (e.g. Hypothesis's shrinker collapses the generator's
    # alphabet toward one repeated minimal value): guarantee uniqueness with a
    # numeric suffix rather than raising - the exact text no longer matters
    # once we're here, only distinctness does.
    base = factory()
    n = 2
    while f"{base}_{n}" in existing:
        n += 1
    candidate = f"{base}_{n}"
    existing.add(candidate)
    return candidate


def build_ossie_document(rnd: Rnd) -> dict[str, Any]:
    """A random-but-valid Ossie document dict within the v1 SML-round-trippable
    subset: 1-2 dimension datasets (each with a primary key + 1-3 other
    fields), one fact dataset with a foreign key + 1-2 measure columns per
    dimension, a relationship fact -> each dimension, and 1-2 metrics that are
    each either a simple aggregate or a ratio of two."""
    used_names: set[str] = set()

    def dataset_name() -> str:
        return _unique(used_names, lambda: f"ds_{rnd.colname()}")

    dim_specs = []
    for _ in range(rnd.count(1, 2)):
        name = dataset_name()
        key_col = f"{rnd.colname()}_id"
        col_names_used = {key_col}
        extra_cols = [_unique(col_names_used, rnd.colname) for _ in range(rnd.count(1, 3))]
        dim_specs.append({"name": name, "key_col": key_col, "extra_cols": extra_cols})

    fact_name = dataset_name()
    fact_col_names: set[str] = set()
    fk_cols = [_unique(fact_col_names, lambda: f"fk_{rnd.colname()}") for _ in dim_specs]
    measure_cols = [_unique(fact_col_names, rnd.colname) for _ in range(rnd.count(1, 2))]

    def source_for(name: str) -> str:
        return f"db_{rnd.colname()}.sch_{rnd.colname()}.{name}"

    def ansi_field(dataset_name: str, col: str, datatype: str) -> dict[str, Any]:
        return {
            "name": col,
            "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": f"{dataset_name}.{col}"}]},
            "datatype": datatype,
        }

    datasets = []
    for spec in dim_specs:
        fields = [ansi_field(spec["name"], spec["key_col"], "Integer")]
        fields += [ansi_field(spec["name"], col, "String") for col in spec["extra_cols"]]
        datasets.append(
            {
                "name": spec["name"],
                "source": source_for(spec["name"]),
                "primary_key": [spec["key_col"]],
                "fields": fields,
            }
        )

    fact_fields = [ansi_field(fact_name, fk, "Integer") for fk in fk_cols]
    fact_fields += [ansi_field(fact_name, col, "Decimal") for col in measure_cols]
    datasets.append({"name": fact_name, "source": source_for(fact_name), "fields": fact_fields})

    relationships = [
        {
            "name": f"{fact_name}_to_{spec['name']}",
            "from": fact_name,
            "to": spec["name"],
            "from_columns": [fk],
            "to_columns": [spec["key_col"]],
        }
        for spec, fk in zip(dim_specs, fk_cols)
    ]

    used_metric_names: set[str] = set()
    metrics = []
    for _ in range(rnd.count(1, 2)):
        name = _unique(used_metric_names, lambda: f"metric_{rnd.colname()}")
        expr = f"{rnd.pick(_AGG_FUNCS)}({fact_name}.{rnd.pick(measure_cols)})"
        if rnd.chance(0.4):
            expr = f"{expr} / {rnd.pick(_AGG_FUNCS)}({fact_name}.{rnd.pick(measure_cols)})"
        metrics.append({"name": name, "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": expr}]}})

    return {
        "version": "0.2.0.dev0",
        "semantic_model": [
            {"name": "generated_model", "datasets": datasets, "relationships": relationships, "metrics": metrics}
        ],
    }


def assert_ossie_roundtrip(document_dict: dict[str, Any]) -> None:
    """Ossie -> SML -> Ossie: dataset names, relationship (from, to) pairs, and
    every original metric name must survive, each still resolving to an
    ANSI_SQL expression (never silently dropped or downgraded to MDX for
    anything the generator produces, since it only emits the round-trippable
    simple/ratio-aggregate shapes)."""
    document = OssieDocument.model_validate(document_dict)
    emitted = emit_sml_files(document)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for filename, content in emitted.files.items():
            path = tmp_path / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        parsed = parse_sml_repo(tmp_path)

    original = document.semantic_model[0]
    reparsed = parsed.document.semantic_model[0]

    assert {d.name for d in reparsed.datasets} == {d.name for d in original.datasets}

    original_rel_pairs = {(r.from_dataset, r.to) for r in original.relationships or []}
    reparsed_rel_pairs = {(r.from_dataset, r.to) for r in reparsed.relationships or []}
    assert reparsed_rel_pairs == original_rel_pairs

    original_metric_names = {m.name for m in original.metrics or []}
    reparsed_by_name = {m.name: m for m in reparsed.metrics or []}
    assert original_metric_names <= set(reparsed_by_name)
    for name in original_metric_names:
        assert reparsed_by_name[name].expression.dialects[0].dialect.value == "ANSI_SQL"
