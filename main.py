"""Точка входа ChapaShop: uvicorn main:app

Что делает этот файл:
  • подключает все роутеры (каталог, бот, Mini App, Roblox, админ-API, фото товаров);
  • отдаёт страницы сайта и админки (/admin);
  • САМ добавляет к ссылкам на /static/*.js и *.css версию ?v=<хеш файла> — при каждом изменении
    файла адрес меняется, поэтому Safari и Telegram всегда скачивают свежую версию (кеш не мешает);
  • ставит заголовки безопасности и ограничивает размер запросов.
"""
import hashlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, catalog, health, miniapp, promo_requests, roblox, telegram
from app.db import SessionLocal
from app.seed import seed

WEB = Path(__file__).parent / "web"
log = logging.getLogger("chapashop")


@asynccontextmanager
async def lifespan(_: FastAPI):
    with SessionLocal() as db:
        seed(db)
        admin.ensure_owner(db)
    from bot.handlers import setup_bot
    setup_bot()
    from app.preflight import run_checks, summary
    res = summary(run_checks())
    if res["blockers"]:
        log.error("Предстартовая проверка: не настроено %s", res["blockers"])
    yield


app = FastAPI(title="ChapaShop", lifespan=lifespan)
app.include_router(health.router)
app.include_router(catalog.router)
app.include_router(catalog.media_router)     # /media/<id> — фото товаров, загруженные из галереи
app.include_router(telegram.router)
app.include_router(miniapp.router)
app.include_router(miniapp.public_router)    # /receipt/... — PDF-чек по временной ссылке
app.include_router(promo_requests.router)
app.include_router(roblox.router)
app.include_router(admin.router)


class NoCacheStatic(StaticFiles):
    """Файлы /static отдаются с «no-cache»: браузер каждый раз спрашивает, не изменился ли файл (ETag)."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", NoCacheStatic(directory=WEB / "static"), name="static")

# ---------- Страницы с автоматической версией файлов ----------
_ASSET = re.compile(r'(src|href)="(/static/[^"?]+)(?:\?[^"]*)?"')
_ver_cache: dict[str, tuple[int, str]] = {}


def file_version(path: Path) -> str:
    """Короткий хеш содержимого файла (пересчитывается, только если файл изменился)."""
    mtime = path.stat().st_mtime_ns
    hit = _ver_cache.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    ver = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
    _ver_cache[str(path)] = (mtime, ver)
    return ver


def page(name: str) -> HTMLResponse:
    """Читает HTML и заменяет /static/x.js → /static/x.js?v=<хеш>. Сам HTML кешировать нельзя."""
    html = (WEB / name).read_text(encoding="utf-8")

    def bump(m: re.Match) -> str:
        f = WEB / m.group(2).lstrip("/")
        return f'{m.group(1)}="{m.group(2)}?v={file_version(f) if f.is_file() else "0"}"'

    return HTMLResponse(_ASSET.sub(bump, html), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


MAX_BODY = 1 * 1024 * 1024            # обычные запросы — до 1 МБ
MAX_BODY_UPLOAD = 6 * 1024 * 1024     # фото товара из галереи — до 6 МБ (сайт сжимает фото заранее)
MAX_BODY_RESTORE = 50 * 1024 * 1024   # восстановление копии — до 50 МБ


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # В лог — только тип ошибки и адрес, без тела запроса и секретов.
    log.error("Ошибка %s на %s %s", type(exc).__name__, request.method, request.url.path)
    return JSONResponse({"detail": "Внутренняя ошибка сервера. Попробуйте позже."}, status_code=500)


@app.exception_handler(RequestValidationError)
async def bad_input(request: Request, exc: RequestValidationError):
    errs = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse({"detail": errs}, status_code=422)


@app.middleware("http")
async def security_headers(request, call_next):
    path = request.url.path
    limit = (MAX_BODY_RESTORE if path == "/admin/api/restore"
             else MAX_BODY_UPLOAD if path == "/admin/api/upload-image" else MAX_BODY)
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > limit:
        return JSONResponse({"detail": "Слишком большой запрос"}, status_code=413)
    try:
        resp = await call_next(request)
    except Exception as exc:
        return await unhandled(request, exc)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.scheme == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    if not path.startswith("/docs"):
        # Google Fonts (шрифт Manrope) разрешены только для стилей и файлов шрифтов.
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://telegram.org; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' https: data: blob:; "
            "connect-src 'self'; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; "
            "object-src 'none'; base-uri 'self'")
    if path.startswith("/admin"):
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------- Админка ----------
@app.get("/admin", include_in_schema=False)
def admin_page():
    return page("admin.html")


# ---------- Сайт и Mini App ----------
@app.get("/", include_in_schema=False)
def index():
    return page("index.html")


# Страницы сайта (товар, корзина, о магазине) отдаются тем же интерфейсом.
@app.get("/product/{product_id}", include_in_schema=False)
@app.get("/cart", include_in_schema=False)
@app.get("/about", include_in_schema=False)
@app.get("/app", include_in_schema=False)
@app.get("/promo", include_in_schema=False)
@app.get("/orders", include_in_schema=False)
@app.get("/orders/{order_id}", include_in_schema=False)
@app.get("/profile", include_in_schema=False)
def spa_pages(product_id: int | None = None, order_id: int | None = None):
    return page("index.html")
