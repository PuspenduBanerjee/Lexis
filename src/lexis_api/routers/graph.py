"""Graph-canvas structured edits (see graph_edit.py for the merge/fidelity logic)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from semantica.parser import parse_ossie_yaml
from semantica.resolved_model import ResolvedModel
from semantica_api.db import get_db
from semantica_api.deps import get_owned_or_admin_model
from semantica_api.graph_edit import apply_graph_edit
from semantica_api.models import SemanticModelRecord
from semantica_api.schemas import GraphEditIn, ModelDetailOut, to_detail_out

router = APIRouter(prefix="/api/models", tags=["graph"])


@router.put("/{model_id}/graph", response_model=ModelDetailOut)
def update_model_graph(
    body: GraphEditIn,
    db: Session = Depends(get_db),
    record: SemanticModelRecord = Depends(get_owned_or_admin_model),
) -> ModelDetailOut:
    document = parse_ossie_yaml(record.raw_yaml)
    updated_document = apply_graph_edit(document, body)
    updated_semantic_model = updated_document.semantic_model[0]

    record.raw_yaml = updated_document.to_ossie_yaml()
    db.add(record)
    db.commit()
    db.refresh(record)

    model = ResolvedModel.build(updated_semantic_model)
    return to_detail_out(record, model)
