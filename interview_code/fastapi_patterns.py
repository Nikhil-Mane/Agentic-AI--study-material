"""Verified FastAPI patterns asked in interviews.  Run: python fastapi_patterns.py

1. Fixed version of the interview snippet (status_code, Query list, no decorator misuse)
2. Dependency injection with Depends  3. JWT authentication  4. RBAC (authorization) dependency
5. File upload (UploadFile) with validation + chunked save   6. Pydantic validation (422)   7. Rate limiting dependency (429)
Production run:  gunicorn -k uvicorn.workers.UvicornWorker -w 4 app:app   (or: uvicorn app:app --workers 4)  behind nginx/ingress
"""
import tempfile
import time
from pathlib import Path

import jwt                                   # PyJWT
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

SECRET, ALGO = "change-me-use-a-key-vault-secret", "HS256"       # prod: RS256/ES256 verified against the IdP's JWKS
app = FastAPI()


# ------------------------------------------------------------------ 1. fixed interview snippet
def second_largest(nums: list[int]):
    first = second = float("-inf")
    for n in nums:
        if n > first:
            first, second = n, first
        elif first > n > second:
            second = n
    return None if second == float("-inf") else second


@app.get("/second-largest", status_code=200)                 # was `status=201`: wrong kwarg AND GET shouldn't return 201
async def second_largest_endpoint(nums: list[int] = Query(...)):    # list query params need Query(...)
    return {"second_largest": second_largest(nums)}          # `async def` fine here (no blocking I/O); don't call it like a normal function


# ------------------------------------------------------------------ 2+3+4. DI + JWT authN + RBAC authZ
def current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    try:
        return jwt.decode(authorization[7:], SECRET, algorithms=[ALGO], audience="my-api", issuer="my-idp")   # verifies signature, exp, aud, iss
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token")


def require_role(*roles: str):
    def checker(user: dict = Depends(current_user)):          # dependency that depends on another dependency
        if not set(roles) & set(user.get("roles", [])):
            raise HTTPException(403, "forbidden")             # authenticated but NOT authorised
        return user
    return checker


@app.get("/me")
def me(user: dict = Depends(current_user)):
    return {"sub": user["sub"], "tenant": user["tenant"]}


@app.get("/admin/report")
def report(user: dict = Depends(require_role("admin"))):
    return {"ok": True}


# ------------------------------------------------------------------ 5. file upload for RAG ingestion
MAX_BYTES, ALLOWED = 1_000_000, {"application/pdf": b"%PDF", "text/plain": None}
UPLOAD_DIR = Path(tempfile.mkdtemp())


@app.post("/documents", status_code=201)                     # POST that CREATES -> 201
async def upload(file: UploadFile = File(...), user: dict = Depends(current_user)):
    if file.content_type not in ALLOWED:
        raise HTTPException(415, "unsupported media type")
    head = await file.read(4)
    magic = ALLOWED[file.content_type]
    if magic and head != magic:                              # don't trust the client's content-type header
        raise HTTPException(400, "file content does not match type")
    dest, size = UPLOAD_DIR / f"{user['tenant']}_{Path(file.filename).name}", len(head)     # Path(...).name blocks ../ traversal
    with dest.open("wb") as out:
        out.write(head)
        while chunk := await file.read(64 * 1024):           # stream in chunks: never hold a big file in RAM
            size += len(chunk)
            if size > MAX_BYTES:
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "file too large")
            out.write(chunk)
    # real system: save to Blob/S3, compute SHA-256 for dedup, enqueue an ingestion job, return job id
    return {"filename": dest.name, "bytes": size, "status": "queued"}


# ------------------------------------------------------------------ 6. Pydantic validation
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)


@app.post("/chat")
def chat(body: ChatIn, user: dict = Depends(current_user)):
    return {"echo": body.message, "top_k": body.top_k}


# ------------------------------------------------------------------ 7. rate limit dependency (in-memory; Redis in prod)
hits: dict[str, list[float]] = {}


def rate_limit(user: dict = Depends(current_user)):
    now = time.monotonic()
    window = [t for t in hits.get(user["sub"], []) if now - t < 60]
    if len(window) >= 3:
        raise HTTPException(429, "too many requests", headers={"Retry-After": "60"})
    hits[user["sub"]] = window + [now]


@app.get("/limited", dependencies=[Depends(rate_limit)])
def limited():
    return {"ok": True}


# ------------------------------------------------------------------ tests
def token(**over):
    claims = {"sub": "u1", "tenant": "acme", "roles": ["employee"], "aud": "my-api", "iss": "my-idp", "exp": time.time() + 300}
    claims.update(over)
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm=ALGO)}


c = TestClient(app)
assert c.get("/second-largest", params={"nums": [1, 10, 3, 10, 9]}).json() == {"second_largest": 9}
assert c.get("/me").status_code == 401                                              # no token -> 401 Unauthorized (authN)
assert c.get("/me", headers=token(exp=time.time() - 10)).status_code == 401         # expired
assert c.get("/me", headers=token()).json() == {"sub": "u1", "tenant": "acme"}
assert c.get("/admin/report", headers=token()).status_code == 403                    # logged in but not admin -> 403 Forbidden (authZ)
assert c.get("/admin/report", headers=token(roles=["admin"])).status_code == 200
assert c.post("/documents", files={"file": ("a.pdf", b"%PDF-1.4 hello", "application/pdf")}, headers=token()).status_code == 201
assert c.post("/documents", files={"file": ("a.pdf", b"not a pdf", "application/pdf")}, headers=token()).status_code == 400
assert c.post("/documents", files={"file": ("a.exe", b"MZ", "application/x-msdownload")}, headers=token()).status_code == 415
assert c.post("/documents", files={"file": ("../../evil.txt", b"x", "text/plain")}, headers=token()).json()["filename"] == "acme_evil.txt"
assert c.post("/chat", json={"message": ""}, headers=token()).status_code == 422                 # Pydantic validation error
assert c.post("/chat", json={"message": "hi", "top_k": 99}, headers=token()).status_code == 422
codes = [c.get("/limited", headers=token(sub="u2")).status_code for _ in range(4)]
assert codes == [200, 200, 200, 429]
print("FASTAPI PATTERNS VERIFIED")
