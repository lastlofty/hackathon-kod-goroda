from typing import Any, TypeVar

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


ModelT = TypeVar("ModelT")


def get_or_404(db: Session, model: type[ModelT], entity_id: Any) -> ModelT:
    entity = db.get(model, entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    return entity


def apply_patch(entity: Any, payload: BaseModel) -> Any:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, field, value)
    return entity


def commit(db: Session, entity: ModelT) -> ModelT:
    db.add(entity)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entity conflicts with an existing record",
        ) from exc
    db.refresh(entity)
    return entity
