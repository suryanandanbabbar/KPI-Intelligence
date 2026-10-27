"""
KPI Intelligence — FastAPI Backend API Package.
"""

from backend.api.app import app, create_app, KPIIntelligenceAPI, router

__all__ = ["app", "create_app", "KPIIntelligenceAPI", "router"]
