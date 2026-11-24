import os, sqlite3, random, hmac, hashlib, json
from urllib.parse import parse_qsl
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL   = os.getenv("CHANNEL", "@twxinet")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")  # например https://your-app.onrender.com/

app = FastAPI()

def init_db():
    conn = sqlite3.connect("game.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 100,
        bonus_claimed INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        trophy TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit(); conn.close()

init_db()

def verify_telegram_data(init_data: str):
    try:
        parsed = dict(parse_qsl(init_data))
        hash_val = parsed.pop("hash", None)
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        if calc != hash_val: return None
        return json.loads(parsed["user"])
    except Exception:
        return None

async def check_subscription(user_id: int) -> bool:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",
            params={"chat_id": CHANNEL, "user_id": user_id})
        d = r.json()
        if d.get("ok"):
            return d["result"]["status"] in ("member", "administrator", "creator")
    return False

class InitData(BaseModel):
    initData: str

@app.post("/api/balance")
async def balance(data: InitData):
    u = verify_telegram_data(data.initData)
    if not u: raise HTTPException(401)
    conn = sqlite3.connect("game.db"); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)",
              (u["id"], u.get("username","")))
    c.execute("SELECT balance, bonus_claimed FROM users WHERE user_id=?", (u["id"],))
    bal, claimed = c.fetchone(); conn.commit(); conn.close()
    return {"balance": bal, "bonus_claimed": bool(claimed)}

@app.post("/api/claim-bonus")
async def claim_bonus(data: InitData):
    u = verify_telegram_data(data.initData)
    if not u: raise HTTPException(401)
    conn = sqlite3.connect("game.db"); c = conn.cursor()
    c.execute("SELECT bonus_claimed FROM users WHERE user_id=?", (u["id"],))
    row = c.fetchone()
    if not row or row[0]:
        conn.close(); return {"error": "Бонус уже получен"}
    if not await check_subscription(u["id"]):
        conn.close(); return {"error": "Подпишитесь на @twxinet и попробуйте снова"}
    c.execute("UPDATE users SET balance=balance+1500, bonus_claimed=1 WHERE user_id=?", (u["id"],))
    conn.commit(); conn.close()
    return {"success": True, "bonus": 1500}

@app.post("/api/open-case")
async def open_case(data: InitData):
    u = verify_telegram_data(data.initData)
    if not u: raise HTTPException(401)
    conn = sqlite3.connect("game.db"); c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id=?", (u["id"],))
    bal = c.fetchone()[0]
    if bal < 100: conn.close(); return {"error": "Недостаточно демо-Stars"}
    pool = [("Обычная звезда",60),("Серебряная звезда",25),
            ("Золотая звезда",10),("Кристальная",4),("Легендарная",1)]
    trophy = random.choices([p[0] for p in pool], weights=[p[1] for p in pool])[0]
    c.execute("UPDATE users SET balance=balance-100 WHERE user_id=?", (u["id"],))
    c.execute("INSERT INTO inventory (user_id, trophy) VALUES (?,?)", (u["id"], trophy))
    c.execute("SELECT balance FROM users WHERE user_id=?", (u["id"],))
    nb = c.fetchone()[0]; conn.commit(); conn.close()
    return {"trophy": trophy, "balance": nb}

@app.post("/api/inventory")
async def inventory(data: InitData):
    u = verify_telegram_data(data.initData)
    if not u: raise HTTPException(401)
    conn = sqlite3.connect("game.db"); c = conn.cursor()
    c.execute("SELECT trophy, created_at FROM inventory WHERE user_id=? ORDER BY id DESC", (u["id"],))
    items = [{"trophy": r[0], "date": r[1]} for r in c.fetchall()]
    conn.close(); return {"items": items}

@app.post("/webhook")
async def webhook(request: Request):
    upd = await request.json()
    msg = upd.get("message")
    if msg and msg.get("text","").startswith("/start"):
        chat_id = msg["chat"]["id"]
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": "🎮 Демо-игра против азарта.\n\nВнутри: бесплатные демо-Stars, кейсы и трофеи. Реальные деньги не используются, призы не выдаются.",
                "reply_markup": {"inline_keyboard": [[
                    {"text":"Открыть демо","web_app":{"url": WEBAPP_URL}}
                ]]}
            })
    return {"ok": True}

app.mount("/", StaticFiles(directory="webapp", html=True), name="webapp")
