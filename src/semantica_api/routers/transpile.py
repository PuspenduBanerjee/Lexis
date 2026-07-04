"""Transpile a persisted model to any of the existing 8 targets."""

from fastapi import APIRouter, Depends

from semantica.dispatch import transpile as dispatch_transpile
from semantica.parser import parse_osi_yaml
from semantica.resolved_model import ResolvedModel
from semantica_api.deps import get_visible_model
from semantica_api.models import SemanticModelRecord
from semantica_api.schemas import TranspileIn, TranspileOut

router = APIRouter(prefix="/api/models", tags=["transpile"])


@router.post("/{model_id}/transpile", response_model=TranspileOut)
def transpile_model(
    body: TranspileIn,
    record: SemanticModelRecord = Depends(get_visible_model),
) -> TranspileOut:
    document = parse_osi_yaml(record.raw_yaml)
    model = ResolvedModel.build(document.semantic_model[0])
    result = dispatch_transpile(document, model, body.target, body.metric, body.group_by)
    return TranspileOut(content=result.content, warnings=result.warnings)
