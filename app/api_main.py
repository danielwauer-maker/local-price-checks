from .main import app
from .api_routes import router
from .admin_routes import router as admin_router
from .media_routes import router as media_router

app.include_router(router)
app.include_router(admin_router)
app.include_router(media_router)
