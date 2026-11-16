from typing import Dict, Any, List, Optional
from app.models.decoder import DecoderDefinition, DecoderVersion

MATCH_FIELDS = ["providerId", "protocolId", "deviceTypeId", "messageType", "version", "payloadFormat", "format"]


def specificity(match: dict) -> int:
    if not match or not isinstance(match, dict):
        return 0
    return sum(1 for field in MATCH_FIELDS if match.get(field))


def matches_criteria(decoder_match: dict, context: dict) -> bool:
    if not decoder_match or not isinstance(decoder_match, dict):
        return False
    # If match criteria has fields, all of them must match context
    for field in MATCH_FIELDS:
        val = decoder_match.get(field)
        if val is not None and str(val).strip() != "":
            val_clean = str(val).strip().lower()
            if field in ("payloadFormat", "format"):
                if val_clean in ("any", "all", "*"):
                    continue
                ctx_fmt = str(context.get("format") or context.get("payload_format") or context.get("payloadFormat") or "").strip().lower()
                if ctx_fmt != val_clean:
                    return False
            else:
                context_val = context.get(field)
                if str(context_val).strip() != str(val).strip():
                    return False
    return True


def select_best_decoder(candidates: List[dict], context: dict) -> Optional[dict]:
    """
    Selects the most specific live decoder matching the given context.
    Candidates should have 'match' dict.
    """
    matching = []
    for cand in candidates:
        match_def = cand.get("match", {})
        if specificity(match_def) > 0 and matches_criteria(match_def, context):
            matching.append(cand)

    if not matching:
        return None

    # Sort descending by specificity
    matching.sort(key=lambda c: specificity(c.get("match", {})), reverse=True)
    return matching[0]
