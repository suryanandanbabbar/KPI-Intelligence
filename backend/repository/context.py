"""
KPI Intelligence — Tenant Context and Security Boundaries.

Enforces:
- Mandatory explicit tenant context on all tenant-scoped operations
- Multi-tenant isolation without reliance on database-level RLS
- Fail-closed authorization checks
"""

import uuid
from dataclasses import dataclass, field
from typing import List, Optional


class TenantAccessDeniedError(PermissionError):
    """Raised when an operation attempts to breach tenant boundaries."""
    pass


@dataclass(frozen=True)
class TenantContext:
    """
    Explicit trusted tenant context.
    Must be established by the application authentication/authorization layer.
    Never derived from untrusted client payloads or file paths.
    """
    tenant_id: str
    user_id: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    is_system: bool = False

    def __post_init__(self):
        if not self.tenant_id or not str(self.tenant_id).strip():
            raise ValueError("TenantContext requires a non-empty, valid 'tenant_id'.")
        # Validate UUID format if formatted as UUID
        try:
            uuid.UUID(str(self.tenant_id).strip())
        except (ValueError, AttributeError):
            # Allow clean string tenant IDs if non-UUID, but must be valid non-empty string
            if len(self.tenant_id.strip()) < 3:
                raise ValueError(f"Invalid tenant_id format: '{self.tenant_id}'")

    def assert_authorized(self, document_tenant_id: Optional[str]) -> None:
        """
        Enforces tenant isolation on read, write, and delete operations.
        Raises TenantAccessDeniedError if document tenant_id differs from context.
        """
        if self.is_system:
            return  # System/admin bypass for global maintenance if explicitly marked
        if document_tenant_id is None:
            raise TenantAccessDeniedError("Attempted to access non-tenant or null-tenant document under tenant context.")
        if str(document_tenant_id).strip().lower() != str(self.tenant_id).strip().lower():
            raise TenantAccessDeniedError(
                f"Tenant boundary violation: context tenant '{self.tenant_id}' "
                f"cannot access document belonging to tenant '{document_tenant_id}'."
            )

    @classmethod
    def system_context(cls) -> "TenantContext":
        """Creates a privileged system context for background global tasks (e.g. ontology sync)."""
        return cls(tenant_id="00000000-0000-0000-0000-000000000000", user_id="system", is_system=True)
