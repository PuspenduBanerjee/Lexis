"""Hypothesis property-based round-trip test (Ossie -> SML -> Ossie) for the
v1 "documented supported subset" only (no calculation_groups/row_security in
the generator - those paths are covered directly in test_sml_roundtrip.py).

Generation and assertions live in `_sml_roundtrip_helpers.py` (no test-
framework dependency), so the exact same logic also runs under a plain seeded
RNG when `hypothesis` is unavailable - see
test_sml_roundtrip_properties_seeded.py - mirroring
third_party/ossie/converters/databricks/tests/test_roundtrip_properties.py's
Hypothesis-driver/seeded-fallback split.

Run: `pytest tests/test_sml_roundtrip_properties.py` (needs `hypothesis`).
"""

import pytest

pytest.importorskip("hypothesis")  # skip cleanly if hypothesis is not installed

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from _sml_roundtrip_helpers import assert_ossie_roundtrip, build_ossie_document

# Identifier-safe text (matches RandomRnd's alphabets, so both drivers explore
# the same shapes) - no leading/trailing space, no YAML-special characters.
_safe_text = st.from_regex(r"[A-Za-z0-9]{1,10}", fullmatch=True)
_colident = st.from_regex(r"[a-z_][a-z0-9_]{0,7}", fullmatch=True)

_SETTINGS = settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])


class _HypothesisRnd:
    """The `Rnd` interface backed by a Hypothesis `draw`. `chance(p)` ignores
    `p` (Hypothesis explores both branches regardless)."""

    def __init__(self, draw):
        self._draw = draw

    def chance(self, p: float = 0.5) -> bool:
        return self._draw(st.booleans())

    def count(self, lo: int, hi: int) -> int:
        return self._draw(st.integers(min_value=lo, max_value=hi))

    def pick(self, seq):
        return self._draw(st.sampled_from(list(seq)))

    def text(self) -> str:
        return self._draw(_safe_text)

    def colname(self) -> str:
        return self._draw(_colident)


@st.composite
def ossie_documents(draw):
    return build_ossie_document(_HypothesisRnd(draw))


class TestOssieRoundTrip:
    @given(document=ossie_documents())
    @_SETTINGS
    def test_ossie_to_sml_to_ossie(self, document):
        assert_ossie_roundtrip(document)
