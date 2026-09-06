"""Plain-seeded-random fallback for the round-trip property in
test_sml_roundtrip_properties.py - runs unconditionally (no `hypothesis`
dependency), so the Ossie -> SML -> Ossie invariants are still exercised across
many random model shapes in environments without `hypothesis` installed.
"""

import pytest

from _sml_roundtrip_helpers import RandomRnd, assert_ossie_roundtrip, build_ossie_document


@pytest.mark.parametrize("seed", range(30))
def test_ossie_to_sml_to_ossie_seeded(seed):
    document = build_ossie_document(RandomRnd(seed))
    assert_ossie_roundtrip(document)
