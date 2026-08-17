from .main import app
from .api_routes import router
from .admin_routes import router as admin_router

app.include_router(router)
app.include_router(admin_router)
