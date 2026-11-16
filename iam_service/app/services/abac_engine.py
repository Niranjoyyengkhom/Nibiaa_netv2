import fnmatch
import re
import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.abac_policy import ABACPolicy
from app.models.user import User
from app.services.attribute_service import attribute_service
from app.services.role_service import role_service

logger = logging.getLogger("nibiaanet.iam.abac_engine")


class ABACEngine:
    """
    Attribute-Based Access Control (ABAC) Policy Decision Point (PDP).
    Evaluates requests against subject attributes, resource attributes,
    action requested, and environmental context.
    """

    def evaluate(
        self,
        db: Session,
        action: str,
        resource_type: str,
        user: Optional[User] = None,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        resource_id: Optional[str] = None,
        resource_attributes: Optional[Dict[str, Any]] = None,
        context_attributes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        start_time = time.perf_counter()

        # 1. Resolve User
        if user is None:
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
            elif username:
                user = db.query(User).filter(User.name == username).first()

        # Check account activity
        if user and not user.is_active:
            elapsed = (time.perf_counter() - start_time) * 1000
            return {
                "allowed": False,
                "effect": "DENY",
                "matched_policies": [],
                "reasons": ["User account is inactive or revoked"],
                "evaluation_time_ms": round(elapsed, 3),
                "user_attributes": {},
                "effective_permissions": [],
            }

        # 2. Gather Subject Attributes & Roles
        subject_attrs: Dict[str, Any] = {}
        effective_permissions: List[str] = []
        user_roles: List[str] = []

        if user:
            subject_attrs["id"] = user.id
            subject_attrs["username"] = user.name
            subject_attrs["email"] = user.email or ""
            subject_attrs["role"] = user.role
            subject_attrs["tenant_id"] = user.tenant_id

            # Add user assigned attributes from DB
            loaded_attrs = attribute_service.get_entity_attributes(db, "user", user.id)
            subject_attrs.update(loaded_attrs)

            # Gather roles and RBAC permissions
            roles = role_service.get_user_roles(db, user.id)
            user_roles = [r.name for r in roles]
            if user.role not in user_roles:
                user_roles.append(user.role)

            for r in roles:
                perms = role_service.get_effective_permissions_for_role(db, r.id)
                effective_permissions.extend(list(perms))

            # Admin shortcut if standard superuser
            if user.role == "admin":
                effective_permissions.append("*")

        # 3. Gather Resource Attributes
        res_attrs: Dict[str, Any] = dict(resource_attributes or {})
        if resource_id:
            res_attrs["id"] = resource_id
            # Load stored resource attributes if any
            stored_res = attribute_service.get_entity_attributes(db, "resource", resource_id)
            for k, v in stored_res.items():
                if k not in res_attrs:
                    res_attrs[k] = v

        # 4. Context Attributes
        ctx_attrs: Dict[str, Any] = dict(context_attributes or {})
        now_utc = time.gmtime()
        ctx_attrs.setdefault("time_hour", now_utc.tm_hour)
        ctx_attrs.setdefault("time_weekday", now_utc.tm_wday)

        # 5. Load Candidate Policies (tenant-specific or global)
        tenant_id = user.tenant_id if user else None
        policies_query = db.query(ABACPolicy).filter(ABACPolicy.is_active.is_(True))
        if tenant_id is not None:
            policies_query = policies_query.filter(
                (ABACPolicy.tenant_id == tenant_id) | (ABACPolicy.tenant_id.is_(None))
            )
        else:
            policies_query = policies_query.filter(ABACPolicy.tenant_id.is_(None))

        policies = policies_query.order_by(ABACPolicy.priority.desc(), ABACPolicy.id.asc()).all()

        matched_policies: List[str] = []
        deny_reasons: List[str] = []
        allow_reasons: List[str] = []
        has_allow = False
        has_deny = False

        for policy in policies:
            # Check Action Target
            if not self._match_target(action, policy.target_actions):
                continue

            # Check Resource Type Target
            if not self._match_target(resource_type, policy.target_resource_types):
                continue

            # Evaluate Subject Conditions
            subject_ok, subj_reason = self._evaluate_condition_set(
                policy.subject_conditions or {}, subject_attrs, res_attrs, ctx_attrs
            )
            if not subject_ok:
                continue

            # Evaluate Resource Conditions
            resource_ok, res_reason = self._evaluate_condition_set(
                policy.resource_conditions or {}, res_attrs, subject_attrs, ctx_attrs
            )
            if not resource_ok:
                continue

            # Evaluate Environment Conditions
            env_ok, env_reason = self._evaluate_condition_set(
                policy.environment_conditions or {}, ctx_attrs, subject_attrs, res_attrs
            )
            if not env_ok:
                continue

            # Policy Matched!
            matched_policies.append(policy.name)
            if policy.effect == "DENY":
                has_deny = True
                deny_reasons.append(f"Explicitly DENIED by policy '{policy.name}': {policy.description or ''}")
            elif policy.effect == "ALLOW":
                has_allow = True
                allow_reasons.append(f"ALLOWED by policy '{policy.name}': {policy.description or ''}")

        # Decision synthesis (DENY overrides ALLOW)
        final_allowed = False
        final_effect = "DENY"
        reasons = []

        if has_deny:
            final_allowed = False
            final_effect = "DENY"
            reasons = deny_reasons
        elif has_allow:
            final_allowed = True
            final_effect = "ALLOW"
            reasons = allow_reasons
        else:
            # Default fallback: check if standard RBAC permission permits the action
            rbac_match = self._check_rbac_permission(action, effective_permissions)
            if rbac_match:
                final_allowed = True
                final_effect = "ALLOW"
                reasons = [f"Allowed via assigned RBAC permission '{rbac_match}'"]
            else:
                final_allowed = False
                final_effect = "DENY"
                reasons = [f"No matching ALLOW policy and subject lacks RBAC permission for '{action}'"]

        elapsed = (time.perf_counter() - start_time) * 1000

        return {
            "allowed": final_allowed,
            "effect": final_effect,
            "matched_policies": matched_policies,
            "reasons": reasons,
            "evaluation_time_ms": round(elapsed, 3),
            "user_attributes": subject_attrs,
            "effective_permissions": sorted(list(set(effective_permissions))),
        }

    def _match_target(self, value: str, patterns: List[str]) -> bool:
        if not patterns or "*" in patterns:
            return True
        for pat in patterns:
            if fnmatch.fnmatch(value.lower(), pat.lower()):
                return True
        return False

    def _check_rbac_permission(self, action: str, permissions: List[str]) -> Optional[str]:
        if "*" in permissions or "all" in permissions:
            return "*"
        for perm in permissions:
            if fnmatch.fnmatch(action.lower(), perm.lower()):
                return perm
        return None

    def _resolve_dynamic_value(
        self,
        operand: Any,
        subject: Dict[str, Any],
        resource: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        if isinstance(operand, str):
            if operand.startswith("subject."):
                return subject.get(operand[8:])
            if operand.startswith("resource."):
                return resource.get(operand[9:])
            if operand.startswith("context."):
                return context.get(operand[8:])
        return operand

    def _evaluate_condition_set(
        self,
        conditions: Dict[str, Any],
        target_attrs: Dict[str, Any],
        subject: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Tuple[bool, str]:
        if not conditions:
            return True, "No conditions specified"

        for attr_key, rule in conditions.items():
            attr_val = target_attrs.get(attr_key)

            if isinstance(rule, dict):
                # Operator object like {"$gte": 2, "$in": [...]}
                for op, expected in rule.items():
                    resolved_expected = self._resolve_dynamic_value(
                        expected, subject, target_attrs, context
                    )
                    passed = self._eval_operator(op, attr_val, resolved_expected)
                    if not passed:
                        return False, f"Failed condition on '{attr_key}': {attr_val} {op} {resolved_expected}"
            else:
                # Direct equality check
                resolved_expected = self._resolve_dynamic_value(
                    rule, subject, target_attrs, context
                )
                if attr_val != resolved_expected:
                    return False, f"Attribute '{attr_key}' value {attr_val} does not match {resolved_expected}"

        return True, "All conditions satisfied"

    def _eval_operator(self, op: str, actual: Any, expected: Any) -> bool:
        try:
            if op == "$eq":
                return actual == expected
            if op == "$ne":
                return actual != expected
            if op == "$gt":
                return float(actual) > float(expected)
            if op == "$gte":
                return float(actual) >= float(expected)
            if op == "$lt":
                return float(actual) < float(expected)
            if op == "$lte":
                return float(actual) <= float(expected)
            if op == "$in":
                if isinstance(expected, (list, tuple, set)):
                    return actual in expected
                return False
            if op == "$nin":
                if isinstance(expected, (list, tuple, set)):
                    return actual not in expected
                return True
            if op == "$contains":
                if isinstance(actual, (list, tuple, set, str)):
                    return expected in actual
                return False
            if op == "$regex":
                if actual is None:
                    return False
                return bool(re.search(str(expected), str(actual)))
        except (ValueError, TypeError):
            return False
        return False


abac_engine = ABACEngine()
