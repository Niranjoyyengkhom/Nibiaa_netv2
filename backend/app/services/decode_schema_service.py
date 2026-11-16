from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application_decoder import ApplicationDecoder
from app.models.device_type_decoder import DeviceTypeDecoder
from app.models.decode_schema import (
    DecodeSchema,
    DecodeSchemaActivation,
)
from app.models.device_configuration import utc_now
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.decode_schema import (
    MATCH_KEYS,
    DecodeSchemaActivate,
    DecodeSchemaCreate,
    DecoderMatchRequest,
)
from app.services.collaborator_permission_service import (
    collaborator_permission_service,
)
from app.services.js_decoder_runtime import (
    DecoderRuntimeError,
    DecoderRuntimeUnavailable,
    js_runtime,
)
from app.services.payload_decoder import (
    DecodeError,
    decode_payload,
)
from app.services.python_executor import python_engine
from app.services.notification_service import NotificationType, notify_tenant
from app.services.payload_detector import detect_and_parse_payload


def match_columns(schema: DecodeSchema):
    # {attribute: value} of the decoder's DecoderMatch
    return {
        key: getattr(schema, f"match_{key}")
        for key in MATCH_KEYS
    }


def normalise_result(result: dict):
    """
    A decoder returns its values directly, e.g.
    {"temperature": 21.5}, or {"data": {...}, "units": {...}, "deviceName": "..."}.
    Returns (values, units).
    """
    if not isinstance(result, dict):
        raise DecodeError("Decoder must return an object/dict")

    units = {}
    if "units" in result and isinstance(result["units"], dict):
        units = {str(k): str(v) for k, v in result["units"].items()}

    # If "data" is present and is a dictionary, extract telemetry values from "data"
    if "data" in result and isinstance(result["data"], dict):
        out_data = dict(result["data"])
        # Preserve device metadata keys so ingestion_service can auto-provision the device
        for meta_k in ("deviceName", "device_name", "deviceType", "device_type", "credentials"):
            if meta_k in result and meta_k not in out_data:
                out_data[meta_k] = result[meta_k]
        return out_data, units

    # Flat dictionary: remove units from measurements
    out_data = dict(result)
    out_data.pop("units", None)
    return out_data, units


def run_decoder(schema: DecodeSchema, payload: bytes, context: dict):
    """
    Decodes a payload with any decoder version.
    Returns (values, units); raises DecodeError.
    """
    code = schema.code or ""
    # Native Python execution
    if schema.kind == "python" or "def decode" in code or "def transform" in code:
        ok, res, logs, err = python_engine.execute(
            code=code,
            raw_bytes=payload,
            hex_str=payload.hex(),
            context=context,
        )
        if not ok:
            raise DecodeError(err or "Python decoder execution failed")
        return normalise_result(res)

    if schema.kind == "javascript":
        try:
            result = js_runtime.decode(
                schema.code or "",
                payload,
                {
                    **context,
                    "decoderId": str(schema.id),
                    "decoderName": schema.name,
                    "decoderVersion": schema.version,
                },
            )
        except DecoderRuntimeError as error:
            raise DecodeError(str(error))

        return normalise_result(result)

    return decode_payload(payload, schema.byte_order, schema.fields)


class DecodeSchemaService:
    """
    Manages versioned application decoders.

    An Application points to a DecodeSchema through:

        Application.decode_schema_id

    A DecodeSchema is immutable after creation.
    A correction creates a new version (same name).

    Decoders belong to an organization (tenant_id), or to the
    platform (tenant_id None, created by admins, usable by every
    organization).

    Activating a version makes it the live version of its decoder:
    every application using another version of that decoder is moved
    to it. Activating an older version is a rollback.

    A decoder is JavaScript (DecoderDefinition.code, run in the sandboxed
    runtime) or a declarative field list. Its DecoderMatch criteria pick
    it for devices whose application has no decoder (match_decoder).

    Who may do what (RBAC matrix):
        view / test     admin, owner, collaborator with Create or Manage Decoder
        create          admin, owner, collaborator with Create Decoder
        activate/delete admin, owner, collaborator with Manage Decoder
                        (platform decoders: admins only)
    """

    # ================================
    # Pipeline
    # ================================

    def get_schema_for_application(
        self,
        db: Session,
        schema_id: int
    ):
        """
        Returns the decoder assigned to an Application.

        Returns:
            DecodeSchema | None
        """

        return (
            db.query(DecodeSchema)
            .filter(
                DecodeSchema.id == schema_id
            )
            .first()
        )

    def active_activation_id(
        self,
        db: Session,
        schema_id: int
    ):
        # The activation that is live for this version, if any
        return (
            db.query(DecodeSchemaActivation.id)
            .filter(
                DecodeSchemaActivation.schema_id == schema_id,
                DecodeSchemaActivation.deactivated_at.is_(None)
            )
            .scalar()
        )

    # ================================
    # Management
    # ================================

    def create_schema(
        self,
        db: Session,
        data: DecodeSchemaCreate,
        current_user: User
    ):
        tenant_id = self._tenant_for_create(
            db,
            data.tenant_id,
            current_user
        )

        name = data.name.strip()

        if data.code is not None and data.code.strip():
            if "def decode" in data.code or "def transform" in data.code:
                kind, code, fields = "python", data.code, []
                valid, err = python_engine.validate_syntax(code)
                if not valid:
                    raise HTTPException(status_code=422, detail=f"Python Decoder code: {err}")
            else:
                kind, code, fields = "javascript", data.code, []
                try:
                    js_runtime.check(code)
                except DecoderRuntimeUnavailable as error:
                    raise HTTPException(status_code=503, detail=str(error))
                except DecoderRuntimeError as error:
                    raise HTTPException(status_code=422, detail=f"Decoder code: {error}")
        else:
            kind, code = "fields", None
            fields = [field.model_dump() for field in data.fields]

        last_version = (
            db.query(func.max(DecodeSchema.version))
            .filter(
                DecodeSchema.name == name,
                self._same_owner(tenant_id)
            )
            .scalar()
        )

        schema = DecodeSchema(
            tenant_id=tenant_id,
            name=name,
            version=(last_version or 0) + 1,
            kind=kind,
            code=code,
            byte_order=data.byte_order,
            fields=fields,
            description=data.description,
            **{
                f"match_{key}": value
                for key, value in data.match.model_dump().items()
            },
            created_by=current_user.id,
        )

        db.add(schema)

        try:
            db.commit()

        except IntegrityError:
            db.rollback()

            raise HTTPException(
                status_code=409,
                detail=(
                    "Another decoder version was created "
                    "at the same time, retry"
                )
            )

        db.refresh(schema)

        return self.schema_response(
            db,
            schema
        )

    def get_schemas(
        self,
        db: Session,
        current_user: User,
        name: str | None = None
    ):
        self._require_view(db, current_user)

        query = self._visible_query(db, current_user)

        if name is not None:
            query = query.filter(
                DecodeSchema.name == name
            )

        schemas = (
            query
            .order_by(
                DecodeSchema.tenant_id.nulls_first(),
                DecodeSchema.name,
                DecodeSchema.version.desc()
            )
            .all()
        )

        return [
            self.schema_response(db, schema)
            for schema in schemas
        ]

    def get_schema(
        self,
        db: Session,
        schema_id: int,
        current_user: User
    ):
        self._require_view(db, current_user)

        return self.schema_response(
            db,
            self._get_schema(db, schema_id, current_user)
        )

    def delete_schema(
        self,
        db: Session,
        schema_id: int,
        current_user: User
    ):
        schema = self._get_schema(db, schema_id, current_user)
        self._require_manage(db, current_user, schema)

        # Unlink any applications using this decoder as their default fallback
        (
            db.query(Application)
            .filter(Application.decode_schema_id == schema.id)
            .update({Application.decode_schema_id: None}, synchronize_session=False)
        )

        # Delete any application decoder assignments for this schema
        (
            db.query(ApplicationDecoder)
            .filter(ApplicationDecoder.decode_schema_id == schema.id)
            .delete(synchronize_session=False)
        )

        # Delete any device type decoder assignments for this schema
        (
            db.query(DeviceTypeDecoder)
            .filter(DeviceTypeDecoder.decode_schema_id == schema.id)
            .delete(synchronize_session=False)
        )

        # Telemetry keeps its rows; its link to the activation
        # becomes NULL (ON DELETE SET NULL)
        (
            db.query(DecodeSchemaActivation)
            .filter(DecodeSchemaActivation.schema_id == schema.id)
            .delete(synchronize_session=False)
        )

        db.delete(schema)
        db.commit()

    def unassign_schema(
        self,
        db: Session,
        schema_id: int,
        current_user: User
    ):
        """
        Unassigns this decoder version from all applications and device types
        without deleting the decoder itself.
        """
        schema = self._get_schema(db, schema_id, current_user)
        self._require_manage(db, current_user, schema)

        apps_updated = (
            db.query(Application)
            .filter(Application.decode_schema_id == schema.id)
            .update({Application.decode_schema_id: None}, synchronize_session=False)
        )
        app_decoders_deleted = (
            db.query(ApplicationDecoder)
            .filter(ApplicationDecoder.decode_schema_id == schema.id)
            .delete(synchronize_session=False)
        )
        dt_decoders_deleted = (
            db.query(DeviceTypeDecoder)
            .filter(DeviceTypeDecoder.decode_schema_id == schema.id)
            .delete(synchronize_session=False)
        )
        db.commit()

        return {
            "unassigned_applications": apps_updated,
            "unassigned_application_decoders": app_decoders_deleted,
            "unassigned_device_types": dt_decoders_deleted,
        }

    # ================================
    # Activation
    # ================================

    def activate(
        self,
        db: Session,
        schema_id: int,
        data: DecodeSchemaActivate,
        current_user: User
    ):
        schema = self._get_schema(
            db,
            schema_id,
            current_user
        )

        self._require_manage(db, current_user, schema)

        now = utc_now()

        # Every version of this decoder (same owner, same name)
        family_ids = [
            row.id
            for row in (
                db.query(DecodeSchema.id)
                .filter(
                    DecodeSchema.name == schema.name,
                    self._same_owner(schema.tenant_id)
                )
                .all()
            )
        ]

        # Only one live version per decoder
        (
            db.query(DecodeSchemaActivation)
            .filter(
                DecodeSchemaActivation.schema_id.in_(family_ids),
                DecodeSchemaActivation.deactivated_at.is_(None)
            )
            .update(
                {
                    DecodeSchemaActivation.deactivated_at: now
                },
                synchronize_session=False
            )
        )

        activation = DecodeSchemaActivation(
            schema_id=schema.id,
            note=data.note,
            activated_by=current_user.id,
            activated_at=now,
        )

        db.add(activation)

        # Roll every application using this decoder to the version
        applications = (
            db.query(Application)
            .filter(
                Application.decode_schema_id.in_(family_ids),
                Application.decode_schema_id != schema.id
            )
        )

        if schema.tenant_id is not None:
            applications = applications.filter(
                Application.tenant_id == schema.tenant_id
            )

        applications_updated = applications.update(
            {
                Application.decode_schema_id: schema.id
            },
            synchronize_session=False
        )

        try:
            db.commit()

        except IntegrityError:
            db.rollback()

            raise HTTPException(
                status_code=409,
                detail=(
                    "Another activation happened at "
                    "the same time, retry"
                )
            )

        db.refresh(activation)

        notify_tenant(
            db,
            schema.tenant_id,
            "Decoder activated",
            f"{current_user.name} made {schema.name} v{schema.version} live"
            f" ({applications_updated} application(s) moved to it).",
            NotificationType.DECODER,
        )

        return {
            **self.activation_response(
                activation,
                schema
            ),
            "applications_updated": applications_updated,
        }

    def get_activations(
        self,
        db: Session,
        current_user: User,
        schema_id: int | None = None
    ):
        self._require_view(db, current_user)

        visible_ids = self._visible_query(db, current_user).with_entities(
            DecodeSchema.id
        )

        query = (
            db.query(
                DecodeSchemaActivation,
                DecodeSchema
            )
            .join(
                DecodeSchema,
                DecodeSchema.id
                == DecodeSchemaActivation.schema_id
            )
            .filter(
                DecodeSchema.id.in_(visible_ids)
            )
        )

        if schema_id is not None:
            query = query.filter(
                DecodeSchemaActivation.schema_id
                == schema_id
            )

        rows = (
            query
            .order_by(
                DecodeSchemaActivation.id.desc()
            )
            .all()
        )

        return [
            self.activation_response(
                activation,
                schema
            )
            for activation, schema in rows
        ]

    # ================================
    # Decoder testing
    # ================================

    def test_decode(
        self,
        db: Session,
        schema_id: int,
        payload_hex: str,
        current_user: User,
        context: dict | None = None
    ):
        """
        Dry-run a decoder against a sample payload.

        Nothing is stored.
        """

        self._require_view(db, current_user)

        schema = self._get_schema(
            db,
            schema_id,
            current_user
        )

        try:
            raw_payload, hex_str, detected_fmt, json_obj, b64_str, text_str = detect_and_parse_payload(payload_hex)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not parse payload: {e}"
            )

        ctx = dict(context or {})
        ctx["format"] = detected_fmt
        ctx["payloadFormat"] = detected_fmt
        if json_obj is not None:
            ctx["json"] = json_obj
            ctx["data"] = json_obj

        try:
            values, units = run_decoder(schema, raw_payload, ctx)

        except DecodeError as error:
            return {
                "ok": False,
                "decoded": None,
                "units": None,
                "error": str(error),
                "detected_format": detected_fmt,
            }

        return {
            "ok": True,
            "decoded": values,
            "units": units,
            "error": None,
            "detected_format": detected_fmt,
        }

    # ================================
    # Decoder matching (DecoderMatch)
    # ================================

    def match_candidates(
        self,
        db: Session,
        tenant_id: int | None,
        attributes: dict
    ):
        """
        Live decoder versions whose criteria all fit the attributes,
        best first: most criteria set, then the organization's own
        decoders before platform decoders, then the newest.

        A decoder without any criterion is never picked by matching:
        it is only used when an application is assigned to it.
        """

        live_ids = (
            db.query(DecodeSchemaActivation.schema_id)
            .filter(DecodeSchemaActivation.deactivated_at.is_(None))
        )

        query = db.query(DecodeSchema).filter(DecodeSchema.id.in_(live_ids))

        if tenant_id is None:
            query = query.filter(DecodeSchema.tenant_id.is_(None))
        else:
            query = query.filter(
                or_(
                    DecodeSchema.tenant_id.is_(None),
                    DecodeSchema.tenant_id == tenant_id
                )
            )

        candidates = []

        for schema in query.all():
            criteria = {
                key: value
                for key, value in match_columns(schema).items()
                if value is not None
            }

            if not criteria:
                continue

            if all(attributes.get(key) == value for key, value in criteria.items()):
                candidates.append((schema, len(criteria)))

        candidates.sort(
            key=lambda item: (
                item[1],
                item[0].tenant_id is not None,
                item[0].id,
            ),
            reverse=True
        )

        return candidates

    def match_decoder(
        self,
        db: Session,
        tenant_id: int | None,
        attributes: dict
    ):
        """The best matching live decoder, or None."""

        candidates = self.match_candidates(db, tenant_id, attributes)
        return candidates[0][0] if candidates else None

    def explain_match(
        self,
        db: Session,
        data: DecoderMatchRequest,
        current_user: User
    ):
        """Which decoder the pipeline would pick (debugging aid)."""

        self._require_view(db, current_user)

        tenant_id = (
            data.tenant_id
            if current_user.role == "admin"
            else current_user.tenant_id
        )

        attributes = {
            key: value
            for key, value in data.model_dump().items()
            if key in MATCH_KEYS
        }

        candidates = self.match_candidates(db, tenant_id, attributes)

        return {
            "decoder": (
                self.schema_response(db, candidates[0][0])
                if candidates
                else None
            ),
            "candidates": [
                {
                    "id": schema.id,
                    "name": schema.name,
                    "version": schema.version,
                    "tenant_id": schema.tenant_id,
                    "specificity": specificity,
                }
                for schema, specificity in candidates
            ],
        }

    # ================================
    # Responses
    # ================================

    def schema_response(
        self,
        db: Session,
        schema: DecodeSchema
    ):
        return {
            "id": schema.id,
            "tenant_id": schema.tenant_id,
            "name": schema.name,
            "version": schema.version,
            "kind": schema.kind,
            "code": schema.code,
            "byte_order": schema.byte_order,
            "fields": schema.fields or [],
            "match": match_columns(schema),
            "description": schema.description,
            "created_by": schema.created_by,
            "created_at": schema.created_at,
            "active_activation_id": self.active_activation_id(db, schema.id),
            "application_count": self._application_count(db, schema.id),
        }

    def activation_response(
        self,
        activation: DecodeSchemaActivation,
        schema: DecodeSchema
    ):
        return {
            "activation_id": activation.id,
            "schema_id": schema.id,
            "schema_name": schema.name,
            "schema_version": schema.version,
            "note": activation.note,
            "activated_by": activation.activated_by,
            "activated_at": activation.activated_at,
            "deactivated_at": activation.deactivated_at,
            "active": (
                activation.deactivated_at is None
            ),
        }

    # ================================
    # Helpers
    # ================================

    def _same_owner(
        self,
        tenant_id: int | None
    ):
        if tenant_id is None:
            return DecodeSchema.tenant_id.is_(None)

        return DecodeSchema.tenant_id == tenant_id

    def _application_count(
        self,
        db: Session,
        schema_id: int
    ):
        fallback_app_ids = {
            row[0] for row in (
                db.query(Application.id)
                .filter(Application.decode_schema_id == schema_id)
                .all()
            )
        }
        assigned_app_ids = {
            row[0] for row in (
                db.query(ApplicationDecoder.application_id)
                .filter(ApplicationDecoder.decode_schema_id == schema_id)
                .all()
            )
        }
        return len(fallback_app_ids.union(assigned_app_ids))

    def _visible_query(
        self,
        db: Session,
        current_user: User
    ):
        query = db.query(DecodeSchema)

        if current_user.role == "admin":
            return query

        # Own organization's decoders + platform decoders
        return query.filter(
            or_(
                DecodeSchema.tenant_id.is_(None),
                DecodeSchema.tenant_id == current_user.tenant_id
            )
        )

    def _get_schema(
        self,
        db: Session,
        schema_id: int,
        current_user: User
    ):
        schema = (
            self._visible_query(db, current_user)
            .filter(
                DecodeSchema.id == schema_id
            )
            .first()
        )

        # Another organization's decoder is not found, not revealed
        if schema is None:
            raise HTTPException(
                status_code=404,
                detail="Decode schema not found"
            )

        return schema

    def _check_role(
        self,
        current_user: User
    ):
        if current_user.role not in ("admin", "owner", "collaborator"):
            raise HTTPException(
                status_code=403,
                detail="User cannot access decoders"
            )

        if current_user.role != "admin" and current_user.tenant_id is None:
            raise HTTPException(
                status_code=403,
                detail="User has no organization"
            )

    def _require_view(
        self,
        db: Session,
        current_user: User
    ):
        self._check_role(current_user)

        collaborator_permission_service.require(
            db,
            current_user,
            "create_decoder",
            "manage_decoder"
        )

    def _require_manage(
        self,
        db: Session,
        current_user: User,
        schema: DecodeSchema
    ):
        self._check_role(current_user)

        collaborator_permission_service.require(
            db,
            current_user,
            "manage_decoder"
        )

        if schema.tenant_id is None and current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Platform decoders are managed by admins"
            )

    def _tenant_for_create(
        self,
        db: Session,
        requested_tenant_id: int | None,
        current_user: User
    ):
        self._check_role(current_user)

        collaborator_permission_service.require(
            db,
            current_user,
            "create_decoder"
        )

        if current_user.role == "admin":

            if (
                requested_tenant_id is not None
                and db.get(Tenant, requested_tenant_id) is None
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Tenant not found"
                )

            # None = platform decoder
            return requested_tenant_id

        if (
            requested_tenant_id is not None
            and requested_tenant_id != current_user.tenant_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Cannot create a decoder for another organization"
            )

        return current_user.tenant_id
