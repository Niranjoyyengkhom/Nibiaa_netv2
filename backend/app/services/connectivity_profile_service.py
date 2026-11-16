import ipaddress

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.connectivity_profile import ConnectivityProfile
from app.models.provider_source import ProviderSource
from app.models.telemetry import Telemetry
from app.models.user import User
from app.schemas.connectivity_profile import (
    ConnectivityProfileCreate,
    ConnectivityProfileUpdate,
    ProviderSourceCreate,
)


# Transports whose provider is recognised by the sender's IP address;
# the others by the client / session id
ADDRESS_TRANSPORTS = {"udp", "satellite"}


def source_host(address: str) -> str:
    """
    The host part of "203.0.113.5:4000", "[2001:db8::1]:4000",
    "203.0.113.5" or "2001:db8::1", the way provider sources are stored.
    """

    address = address.strip()

    if address.startswith("[") and "]" in address:
        return address[1:address.index("]")]

    try:
        return str(ipaddress.ip_address(address))
    except ValueError:
        pass

    host, separator, port = address.rpartition(":")

    if separator and port.isdigit():
        return host

    return address


class ConnectivityProfileService:
    """
    Connectivity profiles = the satellite / terrestrial providers
    ("Add / Manage Connectivity Profile", admin only). Any signed-in
    user can list them (names for filters and telemetry).

    Provider sources tell the ingestion pipeline which provider an
    uplink came from.
    """

    # ================================
    # Profiles
    # ================================

    def get_profiles(
        self,
        db: Session
    ):
        profiles = (
            db.query(ConnectivityProfile)
            .order_by(ConnectivityProfile.connection_type, ConnectivityProfile.name)
            .all()
        )

        return [
            self.profile_response(db, profile)
            for profile in profiles
        ]

    def get_profile(
        self,
        db: Session,
        profile_id: int
    ):
        return self.profile_response(
            db,
            self._get_profile(db, profile_id)
        )

    def create_profile(
        self,
        db: Session,
        data: ConnectivityProfileCreate,
        current_user: User
    ):
        self._require_admin(current_user)

        profile = ConnectivityProfile(
            code=data.code,
            **self._editable_fields(data),
        )

        db.add(profile)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            existing = db.query(ConnectivityProfile).filter(ConnectivityProfile.code == data.code).first()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"A connectivity profile with code '{data.code}' already exists"
                )
            raise HTTPException(
                status_code=400,
                detail=f"Database constraint error: {exc.orig or exc}"
            )

        db.refresh(profile)

        return self.profile_response(db, profile)

    def update_profile(
        self,
        db: Session,
        profile_id: int,
        data: ConnectivityProfileUpdate,
        current_user: User
    ):
        self._require_admin(current_user)

        profile = self._get_profile(db, profile_id)

        for field, value in self._editable_fields(data).items():
            setattr(profile, field, value)

        db.commit()
        db.refresh(profile)

        return self.profile_response(db, profile)

    def delete_profile(
        self,
        db: Session,
        profile_id: int,
        current_user: User
    ):
        self._require_admin(current_user)

        profile = self._get_profile(db, profile_id)
        counts = self._counts(db, profile.code)

        if counts["source_count"] or counts["uplink_count"]:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"The profile has {counts['source_count']} source mapping(s) and "
                    f"{counts['uplink_count']} telemetry record(s). "
                    "Disable it instead, so its history keeps its provider."
                )
            )

        db.delete(profile)
        db.commit()

    def profile_response(
        self,
        db: Session,
        profile: ConnectivityProfile
    ):
        return {
            "id": profile.id,
            "code": profile.code,
            "name": profile.name,
            "connection_type": profile.connection_type,
            "integration_status": profile.integration_status,
            "enabled": profile.enabled,
            "transport": profile.transport,
            "max_payload_bytes": profile.max_payload_bytes,
            "description": profile.description,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
            **self._counts(db, profile.code),
        }

    # ================================
    # Provider sources
    # ================================

    def get_sources(
        self,
        db: Session,
        profile_id: int,
        current_user: User
    ):
        self._require_admin(current_user)

        profile = self._get_profile(db, profile_id)

        return (
            db.query(ProviderSource)
            .filter(ProviderSource.provider == profile.code)
            .order_by(ProviderSource.id)
            .all()
        )

    def create_source(
        self,
        db: Session,
        profile_id: int,
        data: ProviderSourceCreate,
        current_user: User
    ):
        self._require_admin(current_user)

        profile = self._get_profile(db, profile_id)

        # Stored the way the pipeline looks it up
        identity = (
            source_host(data.identity)
            if data.transport in ADDRESS_TRANSPORTS
            else data.identity.strip()
        )

        source = ProviderSource(
            provider=profile.code,
            transport=data.transport,
            identity=identity,
        )

        db.add(source)

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="This transport / identity is already mapped to a provider"
            )

        db.refresh(source)

        return source

    def delete_source(
        self,
        db: Session,
        source_id: int,
        current_user: User
    ):
        self._require_admin(current_user)

        source = db.get(ProviderSource, source_id)

        if source is None:
            raise HTTPException(
                status_code=404,
                detail="Provider source not found"
            )

        db.delete(source)
        db.commit()

    # ================================
    # Pipeline: provider resolution
    # ================================

    def resolve(
        self,
        db: Session,
        transport: str,
        source_address: str | None,
        client_id: str | None,
        provider_code: str | None = None
    ):
        """
        The profile an uplink came through, or None when unknown:
          1. the provider code given by the adapter, if any
          2. else the provider source matching the transport identity
        """

        if provider_code is None:
            identity = (
                source_host(source_address)
                if transport in ADDRESS_TRANSPORTS and source_address
                else client_id
            )

            if identity is None:
                return None

            source = (
                db.query(ProviderSource)
                .filter(
                    ProviderSource.transport == transport,
                    ProviderSource.identity == identity
                )
                .first()
            )

            if source is None:
                return None

            provider_code = source.provider

        return (
            db.query(ConnectivityProfile)
            .filter(ConnectivityProfile.code == provider_code)
            .first()
        )

    # ================================
    # Helpers
    # ================================

    def _editable_fields(
        self,
        data: ConnectivityProfileUpdate
    ):
        return {
            "name": data.name.strip(),
            "connection_type": data.connection_type,
            "integration_status": data.integration_status,
            "enabled": data.enabled,
            "transport": data.transport,
            "max_payload_bytes": data.max_payload_bytes,
            "description": data.description,
        }

    def _counts(
        self,
        db: Session,
        code: str
    ):
        return {
            "source_count": (
                db.query(func.count(ProviderSource.id))
                .filter(ProviderSource.provider == code)
                .scalar()
            ),
            "uplink_count": (
                db.query(func.count(Telemetry.id))
                .filter(Telemetry.provider == code)
                .scalar()
            ),
        }

    def _get_profile(
        self,
        db: Session,
        profile_id: int
    ):
        profile = db.get(ConnectivityProfile, profile_id)

        if profile is None:
            raise HTTPException(
                status_code=404,
                detail="Connectivity profile not found"
            )

        return profile

    def _require_admin(
        self,
        current_user: User
    ):
        if current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Only admins can manage connectivity profiles"
            )
