from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db as get_billing_db
from app.dependencies.auth import get_current_user, AuthUser
from app.schemas.network_provider import (
    CellularSimResponse,
    DriverCatalogItem,
    NetworkProviderCreate,
    NetworkProviderResponse,
    NetworkProviderUpdate,
    OnceConnectivityResponse,
    OnceQuotaResponse,
    OnceSimAssignRequest,
    OnceSimResponse,
    OnceSmsQuotaResponse,
    OnceSmsSendRequest,
    OnceStatusUpdateRequest,
    OnceTopupRequest,
    OnceUsageResponse,
    ProviderTestResult,
)
from app.services.billing_service import billing_service
from app.services.monogoto_client import monogoto_client
from app.services.network_provider_service import network_provider_service
from app.services.once_client import once_client

router = APIRouter(
    tags=["Network Providers & Cellular Fleet"]
)


def require_admin(user: AuthUser):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin privileges required for provider management."
        )


def check_sim_access(user: AuthUser, sim_tenant_id: Optional[int]):
    if user.role == "admin":
        return
    if user.tenant_id is None or sim_tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: SIM card belongs to another organization."
        )


# =============================================================================
# Dynamic Network Provider Management (Admin CRUD & Diagnostics)
# =============================================================================

@router.get(
    "/network/drivers",
    response_model=List[DriverCatalogItem],
    summary="List available SIM Provider Drivers Catalog",
    description="Returns all registered SIM provider drivers (1NCE, Monogoto, EMnify, Twilio, Generic REST) with supported capabilities."
)
def list_driver_catalog(
    current_user: AuthUser = Depends(get_current_user),
):
    return network_provider_service.get_driver_catalog()


@router.get(
    "/network/providers",
    response_model=List[NetworkProviderResponse],
    summary="List configured Network Providers",
    description="Returns all active and configured network provider APIs (Monogoto, 1NCE, generic) with live SIM counts."
)
def list_providers(
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    return network_provider_service.list_providers(db)


@router.post(
    "/network/providers",
    response_model=NetworkProviderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new Network Provider API (Admin only)",
    description="Dynamically registers a new cellular network provider (Monogoto, 1NCE, or custom) with encrypted credentials."
)
def create_provider(
    data: NetworkProviderCreate,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    try:
        return network_provider_service.create_provider(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/network/providers/{provider_code}",
    response_model=NetworkProviderResponse,
    summary="Get Network Provider details"
)
def get_provider(
    provider_code: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    provider = network_provider_service.get_provider(db, provider_code)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_code}' not found.")
    
    # Format response
    providers = network_provider_service.list_providers(db)
    match = next((p for p in providers if p.provider_code == provider_code), None)
    if match:
        return match
    raise HTTPException(status_code=404, detail=f"Provider '{provider_code}' not found.")


@router.put(
    "/network/providers/{provider_code}",
    response_model=NetworkProviderResponse,
    summary="Edit Network Provider API configuration (Admin only)",
    description="Updates endpoint URL, authentication credentials, sandbox mode, and active state."
)
def update_provider(
    provider_code: str,
    data: NetworkProviderUpdate,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    try:
        return network_provider_service.update_provider(db, provider_code, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/network/providers/{provider_code}",
    summary="Remove Network Provider API configuration (Admin only)",
    description="Deletes a provider configuration. Pass force=true to dissociate mapped SIM cards."
)
def delete_provider(
    provider_code: str,
    force: bool = Query(False, description="Force delete and dissociate assigned SIM cards"),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    try:
        return network_provider_service.delete_provider(db, provider_code, force=force)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/network/providers/{provider_code}/test",
    response_model=ProviderTestResult,
    summary="Test Network Provider API connection (Admin only)",
    description="Performs live authentication and probe against the provider API (e.g. Monogoto, 1NCE)."
)
async def test_provider_connection(
    provider_code: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    require_admin(current_user)
    return await network_provider_service.test_provider_connection(db, provider_code)


@router.post(
    "/network/providers/{provider_code}/sync",
    response_model=List[OnceSimResponse],
    summary="Sync SIM cards from specified Network Provider",
    description="Triggers live SIM / Thing inventory synchronization from any provider (Monogoto, 1NCE, etc.)."
)
async def sync_sims_from_provider(
    provider_code: str,
    tenant_id: Optional[int] = Query(None, description="Admin only: target tenant ID to associate new SIMs with"),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    target_tenant = tenant_id if current_user.role == "admin" else current_user.tenant_id
    try:
        return await network_provider_service.sync_sims_from_provider(
            db, provider_code=provider_code, tenant_id=target_tenant
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to sync SIMs from provider '{provider_code}': {e}")


# =============================================================================
# Provider-Agnostic SIM Fleet Endpoints (/network/sims)
# =============================================================================

@router.get(
    "/network/sims",
    response_model=List[OnceSimResponse],
    summary="List all cellular SIM cards",
    description="Returns cellular SIM cards across all providers (1NCE, Monogoto) with optional provider/status filtering."
)
def list_all_sims(
    provider: Optional[str] = Query(None, description="Filter by provider: '1nce', 'monogoto'"),
    status_filter: Optional[str] = Query(None, description="Filter by status: Active, Suspended"),
    tenant_id: Optional[int] = Query(None, description="Filter by tenant (Organization / Individual)"),
    unassigned: Optional[bool] = Query(None, description="Admin only: filter unassigned SIMs"),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    is_unassigned = bool(unassigned) if current_user.role == "admin" else False
    target_tenant = tenant_id if current_user.role == "admin" else current_user.tenant_id
    cards = billing_service.list_sim_cards(db, tenant_id=target_tenant, status=status_filter, unassigned=is_unassigned)
    if provider:
        cards = [c for c in cards if (c.provider or "").lower() == provider.lower()]
    return cards


@router.get(
    "/network/sims/{iccid}",
    response_model=OnceSimResponse,
    summary="Get SIM card details"
)
def get_unified_sim_details(
    iccid: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if not card:
        raise HTTPException(status_code=404, detail=f"SIM with ICCID '{iccid}' not found.")
    check_sim_access(current_user, card.tenant_id)
    return card


@router.post(
    "/network/sims/{iccid}/assign",
    response_model=OnceSimResponse,
    summary="Assign SIM card to organization and device"
)
def assign_unified_sim(
    iccid: str,
    data: OnceSimAssignRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if card:
        check_sim_access(current_user, card.tenant_id)

    target_tenant = data.tenant_id if current_user.role == "admin" else current_user.tenant_id
    return billing_service.assign_sim(
        db,
        iccid=iccid,
        tenant_id=target_tenant,
        device_id=data.device_id,
        label=data.label,
        imei=getattr(data, "imei", None),
    )


@router.get(
    "/network/sims/{iccid}/quota",
    response_model=OnceQuotaResponse,
    summary="Query live data quota from assigned provider"
)
async def get_unified_sim_quota(
    iccid: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if card:
        check_sim_access(current_user, card.tenant_id)
    try:
        return await network_provider_service.get_sim_quota(db, iccid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to query quota: {e}")


@router.get(
    "/network/sims/{iccid}/connectivity",
    response_model=OnceConnectivityResponse,
    summary="Get real-time connectivity status from assigned provider"
)
async def get_unified_sim_connectivity(
    iccid: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if card:
        check_sim_access(current_user, card.tenant_id)
    try:
        return await network_provider_service.get_sim_connectivity(db, iccid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch connectivity info: {e}")


@router.post(
    "/network/sims/{iccid}/status",
    summary="Update SIM status on assigned provider (Activate or Suspend)"
)
async def set_unified_sim_status(
    iccid: str,
    data: OnceStatusUpdateRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if not card:
        raise HTTPException(status_code=404, detail="SIM not found.")
    check_sim_access(current_user, card.tenant_id)

    try:
        return await network_provider_service.update_sim_status(
            db, iccid=iccid, status=data.status, reason=data.reason
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/network/sims/{iccid}/reset",
    summary="Reset SIM network connectivity on assigned provider"
)
async def reset_unified_sim(
    iccid: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if not card:
        raise HTTPException(status_code=404, detail="SIM not found.")
    check_sim_access(current_user, card.tenant_id)

    try:
        return await network_provider_service.reset_sim(db, iccid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"SIM reset operation failed: {e}")


@router.post(
    "/network/sims/{iccid}/topup",
    summary="Top-up SIM data quota on assigned provider"
)
async def topup_unified_sim(
    iccid: str,
    data: OnceTopupRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if not card:
        raise HTTPException(status_code=404, detail="SIM not found.")
    check_sim_access(current_user, card.tenant_id)

    try:
        return await network_provider_service.topup_sim(
            db, iccid=iccid, volume_mb=data.volume_mb
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/network/sims/{iccid}/sms",
    summary="Send MT-SMS command to device via assigned provider"
)
async def send_unified_sim_sms(
    iccid: str,
    data: OnceSmsSendRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if not card:
        raise HTTPException(status_code=404, detail="SIM not found.")
    check_sim_access(current_user, card.tenant_id)

    try:
        return await network_provider_service.send_sim_sms(
            db,
            iccid=iccid,
            payload=data.payload,
            source_address=data.source_address or "NibiaaNet",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to dispatch SMS: {e}")


# =============================================================================
# Monogoto Dedicated API Endpoints (/network/monogoto)
# =============================================================================

@router.post(
    "/network/monogoto/things/sync",
    response_model=List[OnceSimResponse],
    summary="Sync Things (SIMs) from Monogoto Developer API",
    description="Fetches live IoT Things from https://developer.monogoto.io/overview and registers into platform."
)
async def sync_monogoto_things(
    tenant_id: Optional[int] = Query(None, description="Admin only: target tenant ID"),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    target_tenant = tenant_id if current_user.role == "admin" else current_user.tenant_id
    return await network_provider_service.sync_sims_from_provider(
        db, provider_code="monogoto", tenant_id=target_tenant
    )


@router.get(
    "/network/monogoto/things",
    summary="List Things directly from Monogoto API (GET /v1/things)"
)
async def list_monogoto_things(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: AuthUser = Depends(get_current_user),
):
    return await monogoto_client.list_things(limit=limit, offset=offset)


@router.get(
    "/network/monogoto/things/{iccid}",
    summary="Get Thing details from Monogoto API (GET /v1/things/{iccid})"
)
async def get_monogoto_thing(
    iccid: str,
    current_user: AuthUser = Depends(get_current_user),
):
    return await monogoto_client.get_thing_details(iccid)


@router.get(
    "/network/monogoto/things/{iccid}/status",
    summary="Get Thing connection status from Monogoto (GET /v1/things/{iccid}/status)"
)
async def get_monogoto_thing_status(
    iccid: str,
    current_user: AuthUser = Depends(get_current_user),
):
    return await monogoto_client.get_thing_status(iccid)


@router.post(
    "/network/monogoto/things/{iccid}/status",
    summary="Update Thing status in Monogoto (POST /v1/things/{iccid}/status)"
)
async def set_monogoto_thing_status(
    iccid: str,
    data: OnceStatusUpdateRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    return await network_provider_service.update_sim_status(
        db, iccid=iccid, status=data.status, reason=data.reason
    )


@router.post(
    "/network/monogoto/things/{iccid}/refresh",
    summary="Refresh Thing connection in Monogoto (POST /v1/things/{iccid}/refresh)"
)
async def refresh_monogoto_thing(
    iccid: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    return await network_provider_service.reset_sim(db, iccid)


@router.post(
    "/network/monogoto/things/{iccid}/sms",
    summary="Send SMS via Monogoto (POST /v1/things/sms/send/{iccid})"
)
async def send_monogoto_sms(
    iccid: str,
    data: OnceSmsSendRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    return await network_provider_service.send_sim_sms(
        db, iccid=iccid, payload=data.payload, source_address=data.source_address or "NibiaaNet"
    )


# =============================================================================
# 1NCE Backward-Compatible Endpoints (/network/1nce/...)
# =============================================================================

@router.get(
    "/network/1nce/sims",
    response_model=List[OnceSimResponse],
    summary="List 1NCE SIM cards"
)
def list_1nce_sims(
    status_filter: Optional[str] = Query(None),
    tenant_id: Optional[int] = Query(None),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    target_tenant_id = tenant_id if current_user.role == "admin" else current_user.tenant_id
    cards = billing_service.list_sim_cards(db, tenant_id=target_tenant_id, status=status_filter)
    return [c for c in cards if (c.provider or "").lower() == "1nce" or not c.provider]


@router.post(
    "/network/1nce/sims/sync",
    response_model=List[OnceSimResponse],
    summary="Sync SIM cards from 1NCE API"
)
async def sync_1nce_sims(
    tenant_id: Optional[int] = Query(None),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    target_tenant_id = tenant_id if current_user.role == "admin" else current_user.tenant_id
    return await billing_service.sync_sims_from_1nce(db, tenant_id=target_tenant_id)


@router.get(
    "/network/1nce/sims/{iccid}",
    response_model=OnceSimResponse,
    summary="Get 1NCE SIM details"
)
def get_1nce_sim_details(
    iccid: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if not card:
        raise HTTPException(status_code=404, detail=f"SIM with ICCID '{iccid}' not found.")
    check_sim_access(current_user, card.tenant_id)
    return card


@router.post(
    "/network/1nce/sims/{iccid}/assign",
    response_model=OnceSimResponse,
    summary="Assign 1NCE SIM card"
)
def assign_1nce_sim(
    iccid: str,
    data: OnceSimAssignRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if card:
        check_sim_access(current_user, card.tenant_id)

    target_tenant = data.tenant_id if current_user.role == "admin" else current_user.tenant_id
    return billing_service.assign_sim(
        db,
        iccid=iccid,
        tenant_id=target_tenant,
        device_id=data.device_id,
        label=data.label,
        imei=getattr(data, "imei", None),
    )


@router.get(
    "/network/1nce/sims/{iccid}/quota",
    response_model=OnceQuotaResponse,
    summary="Query live data quota from 1NCE"
)
async def get_1nce_data_quota(
    iccid: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if card:
        check_sim_access(current_user, card.tenant_id)

    try:
        quota = await once_client.get_data_quota(iccid)
        if card:
            card.quota_total_mb = quota.get("volume_total_mb", card.quota_total_mb)
            card.quota_remaining_mb = quota.get("volume_remaining_mb", card.quota_remaining_mb)
            card.quota_used_mb = quota.get("volume_used_mb", card.quota_used_mb)
            db.commit()
        return quota
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to query 1NCE quota: {e}")


@router.get(
    "/network/1nce/sims/{iccid}/quota/sms",
    response_model=OnceSmsQuotaResponse,
    summary="Query SMS quota from 1NCE"
)
async def get_1nce_sms_quota(
    iccid: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if card:
        check_sim_access(current_user, card.tenant_id)

    try:
        return await once_client.get_sms_quota(iccid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to query 1NCE SMS quota: {e}")


@router.get(
    "/network/1nce/sims/{iccid}/usage",
    response_model=OnceUsageResponse,
    summary="Get historical data & SMS consumption from 1NCE"
)
async def get_1nce_sim_usage(
    iccid: str,
    start_dt: Optional[str] = Query(None),
    end_dt: Optional[str] = Query(None),
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if card:
        check_sim_access(current_user, card.tenant_id)

    try:
        return await once_client.get_usage(iccid, start_dt=start_dt, end_dt=end_dt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch usage from 1NCE: {e}")


@router.get(
    "/network/1nce/sims/{iccid}/connectivity",
    response_model=OnceConnectivityResponse,
    summary="Get real-time connectivity status from 1NCE"
)
async def get_1nce_connectivity_info(
    iccid: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if card:
        check_sim_access(current_user, card.tenant_id)

    try:
        info = await once_client.get_connectivity_info(iccid)
        if card:
            card.last_connectivity_check = info
            db.commit()
        return info
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch connectivity info: {e}")


@router.post(
    "/network/1nce/sims/{iccid}/status",
    response_model=OnceSimResponse,
    summary="Update 1NCE SIM status"
)
async def set_1nce_sim_status(
    iccid: str,
    data: OnceStatusUpdateRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if not card:
        raise HTTPException(status_code=404, detail="SIM not found.")
    check_sim_access(current_user, card.tenant_id)

    try:
        target_tenant = None if current_user.role == "admin" else current_user.tenant_id
        return await billing_service.update_sim_status(db, iccid, data.status, tenant_id=target_tenant)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/network/1nce/sims/{iccid}/reset",
    summary="Reset 1NCE SIM connectivity"
)
async def reset_1nce_sim(
    iccid: str,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if not card:
        raise HTTPException(status_code=404, detail="SIM not found.")
    check_sim_access(current_user, card.tenant_id)

    try:
        return await billing_service.reset_sim_connectivity(db, iccid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"1NCE reset operation failed: {e}")


@router.post(
    "/network/1nce/sims/{iccid}/topup",
    summary="Top-up 1NCE SIM quota"
)
async def topup_1nce_sim(
    iccid: str,
    data: OnceTopupRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if not card:
        raise HTTPException(status_code=404, detail="SIM not found.")
    check_sim_access(current_user, card.tenant_id)

    try:
        return await billing_service.topup_sim(
            db,
            iccid=iccid,
            volume_mb=data.volume_mb,
            create_odoo_invoice=data.create_odoo_invoice,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/network/1nce/sims/{iccid}/sms",
    summary="Send MT-SMS via 1NCE"
)
async def send_1nce_sms(
    iccid: str,
    data: OnceSmsSendRequest,
    db: Session = Depends(get_billing_db),
    current_user: AuthUser = Depends(get_current_user),
):
    card = billing_service.get_sim_card(db, iccid)
    if not card:
        raise HTTPException(status_code=404, detail="SIM not found.")
    check_sim_access(current_user, card.tenant_id)

    try:
        return await billing_service.send_sim_sms(
            db,
            iccid=iccid,
            payload=data.payload,
            source_address=data.source_address or "NibiaaNet",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to dispatch SMS via 1NCE: {e}")
