from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/home")


@router.get("/", response_class=HTMLResponse)
def home():
    return """
    <p><a href="/oauth/google/login">Connect your Google Drive</a></p>
    """
