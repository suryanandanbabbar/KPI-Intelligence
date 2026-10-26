"""
KPI Intelligence — Canonical Dashboard Lifecycle Classification.

Implements strict calendar arithmetic and precedence rules for dashboard lifecycle:
- Precedence: ORPHANED -> UNCLASSIFIED -> DORMANT -> ACTIVE
- Calendar Month Arithmetic: Exactly 6 calendar months (with leap-year & month-end clamping)
- Boundary condition: Exactly 6 calendar months is DORMANT
- Instant equivalence across timezones via UTC normalization
"""

import calendar
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any, Union


class LifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    ORPHANED = "ORPHANED"
    UNCLASSIFIED = "UNCLASSIFIED"


def subtract_calendar_months(dt: datetime, months: int = 6) -> datetime:
    """
    Subtracts exact calendar months matching calendar interval arithmetic.
    Handles variable month lengths and leap years via month-end clamping
    (e.g., Aug 31 - 6 months -> Feb 29 in leap year 2024, Feb 28 in non-leap year 2023,
           Mar 31 - 6 months -> Sep 30).
    Preserves time components and timezone info.
    """
    total_months = dt.year * 12 + (dt.month - 1) - months
    new_year = total_months // 12
    new_month = (total_months % 12) + 1
    _, max_days = calendar.monthrange(new_year, new_month)
    new_day = min(dt.day, max_days)
    return dt.replace(year=new_year, month=new_month, day=new_day)


def normalize_datetime(dt: Union[datetime, str, None]) -> Optional[datetime]:
    """Ensures datetime is timezone-aware UTC datetime."""
    if dt is None:
        return None
    if isinstance(dt, str):
        # Support ISO 8601 strings
        cleaned = dt.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def classify_report_lifecycle(
    owner_id: Optional[Any],
    last_accessed_at: Optional[Union[datetime, str]],
    as_of: Optional[Union[datetime, str]] = None,
) -> LifecycleStatus:
    """
    Classifies dashboard lifecycle status based on ownership and last access.
    
    Precedence:
    1. ORPHANED: owner is missing (None, empty, or whitespace).
    2. UNCLASSIFIED: owner exists but last access timestamp is None.
    3. DORMANT: owner exists and last access <= (as_of - 6 calendar months).
    4. ACTIVE: owner exists and last access > (as_of - 6 calendar months).
    
    Boundary condition:
    An access timestamp exactly equal to the 6-month threshold evaluates to DORMANT.
    """
    # 1. Precedence 1: ORPHANED
    if owner_id is None:
        return LifecycleStatus.ORPHANED
    owner_str = str(owner_id).strip()
    if not owner_str or owner_str.lower() in ("none", "null"):
        return LifecycleStatus.ORPHANED

    # 2. Precedence 2: UNCLASSIFIED
    access_dt = normalize_datetime(last_accessed_at)
    if access_dt is None:
        return LifecycleStatus.UNCLASSIFIED

    # Establish evaluation reference timestamp (as_of)
    ref_as_of = normalize_datetime(as_of)
    if ref_as_of is None:
        ref_as_of = datetime.now(timezone.utc)

    # 3. Calculate exact 6 calendar month boundary
    cutoff = subtract_calendar_months(ref_as_of, 6)

    # Boundary comparison (instant equivalence in UTC)
    if access_dt <= cutoff:
        return LifecycleStatus.DORMANT
    else:
        return LifecycleStatus.ACTIVE
