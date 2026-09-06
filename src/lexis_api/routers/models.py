"""CRUD for the persisted multi-model workspace."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from lexis.parser import parse_ossie_yaml
from lexis.resolved_model import ResolvedModel
from lexis.sml._common import ConversionError
from lexis.sml.parse import parse_sml_repo
from lexis_api.db import get_db
from lexis_api.deps import get_current_user, get_owned_or_admin_model, get_visible_model, require_editor_or_admin
from lexis_api.models import SemanticModelRecord, User
from lexis_api.schemas import (
    CreateModelIn,
    ImportSmlOut,
    ModelDetailOut,
    ModelSummaryOut,
    UpdateModelIn,
    to_detail_out,
    to_summary_out,
)

router = APIRouter(prefix="/api/models", tags=["models"])


def _resolved_model(record: SemanticModelRecord) -> ResolvedModel:
    document = parse_ossie_yaml(record.raw_yaml)
    if len(document.semantic_model) != 1:
        raise ValueError(
            f"Ossie document must contain exactly one semantic_model entry, got {len(document.semantic_model)}"
        )
    return ResolvedModel.build(document.semantic_model[0])


@router.get("", response_model=list[ModelSummaryOut])
def list_models(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # noqa: ARG001 - requires a resolvable user
) -> list[ModelSummaryOut]:
    records = db.query(SemanticModelRecord).order_by(SemanticModelRecord.id).all()
    return [to_summary_out(r, _resolved_model(r)) for r in records]


@router.post("", response_model=ModelDetailOut, status_code=201)
def create_model(
    body: CreateModelIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor_or_admin),
) -> ModelDetailOut:
    document = parse_ossie_yaml(body.yaml_text)
    if len(document.semantic_model) != 1:
        raise ValueError(
            f"Ossie document must contain exactly one semantic_model entry, got {len(document.semantic_model)}"
        )
    semantic_model = document.semantic_model[0]
    model = ResolvedModel.build(semantic_model)

    record = SemanticModelRecord(
        name=body.name or semantic_model.name,
        owner_id=user.id,
        raw_yaml=body.yaml_text,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return to_detail_out(record, model)


@router.post("/import/sml", response_model=ImportSmlOut, status_code=201)
def import_sml_model(
    files: list[UploadFile] = File(..., description="Every *.yml file in the SML repo, relative path as filename"),
    name: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_editor_or_admin),
) -> ImportSmlOut:
    """Parse an uploaded SML repo (a directory of *.yml files - see `lexis.sml.parse`)
    into a new model. Each file's relative path (e.g. `dimensions/Customer
    Dimension.yml`) travels as its `UploadFile.filename`, set client-side by the
    browser's folder picker; reassembled into a temp directory here since
    `parse_sml_repo` reads a real filesystem tree, not in-memory bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for upload in files:
            if not upload.filename:
                raise HTTPException(422, "every uploaded file must have a filename")
            dest = (tmp_path / upload.filename).resolve()
            if tmp_path.resolve() not in dest.parents:
                raise HTTPException(422, f"invalid relative path: {upload.filename!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(upload.file.read())

        try:
            result = parse_sml_repo(tmp_path)
        except ConversionError as exc:
            raise HTTPException(422, str(exc)) from exc

    document = result.document
    if len(document.semantic_model) != 1:
        raise HTTPException(
            422, f"Ossie document must contain exactly one semantic_model entry, got {len(document.semantic_model)}"
        )
    semantic_model = document.semantic_model[0]
    model = ResolvedModel.build(semantic_model)
    yaml_text = document.to_ossie_yaml()

    record = SemanticModelRecord(name=name or semantic_model.name, owner_id=user.id, raw_yaml=yaml_text)
    db.add(record)
    db.commit()
    db.refresh(record)
    return ImportSmlOut(model=to_detail_out(record, model), warnings=result.warnings)


@router.get("/{model_id}", response_model=ModelDetailOut)
def get_model(record: SemanticModelRecord = Depends(get_visible_model)) -> ModelDetailOut:
    return to_detail_out(record, _resolved_model(record))


@router.put("/{model_id}", response_model=ModelDetailOut)
def update_model(
    body: UpdateModelIn,
    db: Session = Depends(get_db),
    record: SemanticModelRecord = Depends(get_owned_or_admin_model),
) -> ModelDetailOut:
    document = parse_ossie_yaml(body.yaml_text)
    if len(document.semantic_model) != 1:
        raise ValueError(
            f"Ossie document must contain exactly one semantic_model entry, got {len(document.semantic_model)}"
        )
    model = ResolvedModel.build(document.semantic_model[0])

    record.raw_yaml = body.yaml_text
    db.add(record)
    db.commit()
    db.refresh(record)
    return to_detail_out(record, model)


@router.delete("/{model_id}", status_code=204)
def delete_model(
    db: Session = Depends(get_db),
    record: SemanticModelRecord = Depends(get_owned_or_admin_model),
) -> None:
    db.delete(record)
    db.commit()
