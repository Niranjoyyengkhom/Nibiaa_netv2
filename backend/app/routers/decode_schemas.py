from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.decode_schema import (
    DecodeSchemaActivate,
    DecodeSchemaActivationResponse,
    DecodeSchemaCreate,
    DecodeSchemaResponse,
    DecodeTestRequest,
    DecodeTestResponse,
    DecoderMatchRequest,
    DecoderMatchResponse,
)
from app.services.decode_schema_service import DecodeSchemaService


router = APIRouter(
    prefix="/decode-schemas",
    tags=["Decode Schemas"],
)

decode_schema_service = DecodeSchemaService()


@router.post(
    "/",
    response_model=DecodeSchemaResponse,
    summary="Create a decoder",
    description=(
        "Creates a new decoder version (DecoderDefinition): JavaScript "
        "code defining decode(input), or a declarative field list, with "
        "optional DecoderMatch criteria. "
        "Versions cannot be edited: a correction is a new version. "
        "Collaborators need the Create Decoder function."
    ),
)
def create_schema(
    data: DecodeSchemaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return decode_schema_service.create_schema(
        db,
        data,
        current_user,
    )


@router.get(
    "/",
    response_model=list[DecodeSchemaResponse],
    summary="List decoders",
    description=(
        "The organization's decoders and the platform decoders "
        "(admins: all). Collaborators need Create or Manage Decoder."
    ),
)
def get_schemas(
    name: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return decode_schema_service.get_schemas(
        db,
        current_user,
        name,
    )


@router.post(
    "/match",
    response_model=DecoderMatchResponse,
    summary="Which decoder matches these attributes?",
    description=(
        "Used by the pipeline when a device's application has no decoder: "
        "the live decoder whose DecoderMatch criteria all fit "
        "(providerId, protocolId, deviceTypeId, messageType, version); "
        "the most specific wins."
    ),
)
def match_decoder(
    data: DecoderMatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return decode_schema_service.explain_match(
        db,
        data,
        current_user,
    )


# Declared before /{schema_id} so "activations" is not read as an id
@router.get(
    "/activations",
    response_model=list[DecodeSchemaActivationResponse],
    summary="Activation history",
    description="Newest first.",
)
def get_activations(
    schema_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return decode_schema_service.get_activations(
        db,
        current_user,
        schema_id,
    )


@router.get(
    "/{schema_id}",
    response_model=DecodeSchemaResponse,
)
def get_schema(
    schema_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return decode_schema_service.get_schema(
        db,
        schema_id,
        current_user,
    )


@router.post(
    "/{schema_id}/activate",
    response_model=DecodeSchemaActivationResponse,
    summary="Activate a decoder version",
    description=(
        "Makes this the live version of its decoder: every application "
        "using another version of the decoder is moved to it. "
        "Activating an older version is a rollback. "
        "Collaborators need the Manage Decoder function."
    ),
)
def activate_schema(
    schema_id: int,
    data: DecodeSchemaActivate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return decode_schema_service.activate(
        db,
        schema_id,
        data,
        current_user,
    )


@router.post(
    "/{schema_id}/test",
    response_model=DecodeTestResponse,
    summary="Dry-run decode",
    description="Decodes a sample payload with this decoder version. Nothing is stored.",
)
def test_schema(
    schema_id: int,
    data: DecodeTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return decode_schema_service.test_decode(
        db,
        schema_id,
        data.payload_hex,
        current_user,
        data.context,
    )


@router.post(
    "/{schema_id}/unassign",
    summary="Unassign a decoder version from all applications and device types",
)
def unassign_schema(
    schema_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return decode_schema_service.unassign_schema(
        db,
        schema_id,
        current_user,
    )


@router.delete(
    "/{schema_id}",
    status_code=204,
    summary="Delete a decoder version",
    description=(
        "Unlinks from any applications and deletes. "
        "Collaborators need the Manage Decoder function."
    ),
)
def delete_schema(
    schema_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    decode_schema_service.delete_schema(
        db,
        schema_id,
        current_user,
    )
