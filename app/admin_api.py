"""Admin HTTP routes, mounted by app/main.py under /admin.

Kept out of main.py so they can move to a separate service later.
NO AUTHENTICATION YET: run the app on 127.0.0.1 only (see README).
"""
from dataclasses import asdict

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.ingestion.upload import MAX_UPLOAD_BYTES, UploadError, save_and_ingest

# Room for the multipart boundaries and part headers around the file itself; the
# exact 10 MB limit on the file is enforced again while it is copied.
MULTIPART_SLACK = 64 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + MULTIPART_SLACK
NO_FILE = "no file: send the PDF in a form field named 'file'"


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


class SizeLimitedRoute(APIRoute):
    """Checks Content-Length BEFORE FastAPI reads and parses the body, so an oversized
    upload is refused without being received. (Dependencies run too late for this:
    FastAPI parses the form before it solves them.)"""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def limited(request: Request):
            length = request.headers.get("content-length")
            if length is None:
                return _error(411, "Content-Length header required")
            if not length.isdigit():
                return _error(400, "invalid Content-Length header")
            if int(length) > MAX_REQUEST_BYTES:
                return _error(413, f"file too large: the limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
            try:
                return await handler(request)
            except RequestValidationError:
                # The only field is "file": it was a text field, or a file part with an
                # empty file name (the multipart parser does not treat those as files).
                # FastAPI's own 422 would echo the whole field back.
                return _error(400, NO_FILE)

        return limited


router = APIRouter()


# Plain def: ingestion blocks (embedding, database), so FastAPI runs it in a worker thread.
def upload(file: UploadFile | None = File(None, description="one PDF, at most 10 MB")):
    """Save one PDF in data/inbox and ingest it. Same file name = same document."""
    if file is None:
        return _error(400, NO_FILE)
    try:
        result = save_and_ingest(file.file, file.filename)
    except UploadError as e:
        return _error(e.status, e.detail)
    return asdict(result)


router.add_api_route(
    "/upload", upload, methods=["POST"], route_class_override=SizeLimitedRoute
)
