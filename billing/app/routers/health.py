from fastapi import APIRouter
from app.config import PORT

router = APIRouter(tags=["Health & Status"])

@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "billing-microservice",
        "port": PORT,
        "version": "2.0.0",
        "features": [
            "odoo_erp_sync",
            "1nce_cellular",
            "monogoto_software_defined",
            "dynamic_sim_drivers",
            "aes256_encrypted_database",
        ],
    }
