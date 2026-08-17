from .main import app
from .api_routes import router

app.include_router(router)
