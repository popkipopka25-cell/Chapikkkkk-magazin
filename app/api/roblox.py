"""Проверка Roblox-ника: показывает аватар и имя игрока. Только подсказка — заказ она не блокирует."""
import re
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/roblox", tags=["roblox"])
NICK_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
_cache: dict[str, tuple[float, dict]] = {}
_hits: dict[str, deque] = defaultdict(deque)
CACHE_TTL, LIMIT, WINDOW = 600, 30, 60


def _fetch(nick: str) -> dict:
    """Публичные API Roblox: поиск по нику и аватар-миниатюра. Токены не нужны."""
    with httpx.Client(timeout=5.0) as c:
        r = c.post("https://users.roblox.com/v1/usernames/users",
                   json={"usernames": [nick], "excludeBannedUsers": True})
        r.raise_for_status()
        data = (r.json().get("data") or [])
        if not data:
            return {"found": False}
        u = data[0]
        avatar = None
        try:
            t = c.get("https://thumbnails.roblox.com/v1/users/avatar-headshot",
                      params={"userIds": u["id"], "size": "150x150", "format": "Png"})
            item = (t.json().get("data") or [{}])[0]
            url = item.get("imageUrl") or ""
            # принимаем картинку только с официального CDN Roblox
            if item.get("state") == "Completed" and re.match(r"^https://[a-z0-9.-]+\.rbxcdn\.com/", url):
                avatar = url
        except Exception:
            avatar = None
        return {"found": True, "id": u["id"], "name": u["name"],
                "display_name": u.get("displayName") or u["name"], "avatar_url": avatar}


@router.get("/lookup")
def lookup(request: Request, username: str = Query(..., max_length=20)):
    nick = username.strip()
    if not NICK_RE.match(nick):
        raise HTTPException(422, "3–20 символов: латиница, цифры и _")
    ip = request.client.host if request.client else "?"
    q, t = _hits[ip], time.monotonic()
    while q and t - q[0] > WINDOW:
        q.popleft()
    if len(q) >= LIMIT:
        raise HTTPException(429, "Слишком много проверок, подождите минуту")
    q.append(t)
    key = nick.lower()
    hit = _cache.get(key)
    if hit and t - hit[0] < CACHE_TTL:
        return hit[1]
    try:
        res = _fetch(nick)
    except Exception:
        raise HTTPException(502, "Roblox сейчас недоступен")
    if len(_cache) > 2000:
        _cache.clear()
    _cache[key] = (t, res)
    return res
