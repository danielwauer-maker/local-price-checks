"""Import every SQLAlchemy model module exactly once.

Alembic, application startup and data-maintenance tools import this module
before reading ``Base.metadata``. This prevents additive tables from silently
disappearing because a route happened not to be imported first.
"""

from . import activity_models as activity_models
from . import client_models as client_models
from . import collection_quality as collection_quality
from . import coverage_models as coverage_models
from . import lokero_models as lokero_models
from . import market_activation as market_activation
from . import models as models
from . import prospect_models as prospect_models
from . import push_models as push_models
from . import sharing_models as sharing_models
from . import ux_routes as ux_routes
from . import web_offer_audit_models as web_offer_audit_models
from .db import Base


def metadata():
    """Return complete application metadata after model registration."""

    return Base.metadata
