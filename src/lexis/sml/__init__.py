"""Ossie <-> SML (Semantic Modeling Language, github.com/semanticdatalayer/SML)
bidirectional converter.

See SML_OSSIE_CONVERTER_PLAN.md at the repo root for the full design: the
documented "supported subset" scope, the data-model mapping table, and the
edge cases that cannot be losslessly resolved.

Phase 1 (this module set, so far): Ossie -> SML only (`emit.py`), wired into
`lexis.dispatch`'s `--target sml`. Phase 2 will add `parse.py` for SML -> Ossie.
"""
