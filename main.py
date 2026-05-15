"""
HR Sistem - Backend API Server
FastAPI + PostgreSQL + JWT Auth
Deploy na Render.com
"""

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta, date
import jwt
import bcrypt
import os
import asyncpg
from contextlib import asynccontextmanager

# ── Config ────────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "hr-sistem-tajni-kljuc-2026-promijeniti!")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/hrdb")

# ── App ───────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    await init_db(app.state.pool)
    yield
    await app.state.pool.close()

app = FastAPI(title="HR Sistem API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# ── DB Init ───────────────────────────────────────────────────────────────────
async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS korisnici (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            ime TEXT,
            uloga TEXT DEFAULT 'korisnik',
            aktivan BOOLEAN DEFAULT true,
            kreiran TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS sluzbe (
            id SERIAL PRIMARY KEY,
            naziv TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS uposlenici (
            id SERIAL PRIMARY KEY,
            ime TEXT NOT NULL,
            prezime TEXT NOT NULL,
            email TEXT,
            sluzba_id INTEGER REFERENCES sluzbe(id),
            pozicija TEXT,
            datum_zaposlenja TEXT,
            status TEXT DEFAULT 'Aktivan'
        );
        CREATE TABLE IF NOT EXISTS sifrarnik_bolovanja (
            id SERIAL PRIMARY KEY,
            sifra TEXT NOT NULL UNIQUE,
            naziv TEXT NOT NULL,
            opis TEXT
        );
        CREATE TABLE IF NOT EXISTS tipovi_odsustava (
            id SERIAL PRIMARY KEY,
            naziv TEXT NOT NULL UNIQUE,
            placeno BOOLEAN DEFAULT true
        );
        CREATE TABLE IF NOT EXISTS bolovanja (
            id SERIAL PRIMARY KEY,
            uposlenik_id INTEGER REFERENCES uposlenici(id),
            datum_od TEXT,
            datum_do TEXT,
            dana INTEGER,
            sifra TEXT,
            razlog TEXT,
            napomena TEXT,
            kreirao INTEGER REFERENCES korisnici(id),
            kreirano TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS odsustva (
            id SERIAL PRIMARY KEY,
            uposlenik_id INTEGER REFERENCES uposlenici(id),
            tip_id INTEGER REFERENCES tipovi_odsustava(id),
            datum_od TEXT,
            datum_do TEXT,
            dana INTEGER,
            status TEXT DEFAULT 'Na cekanju',
            napomena TEXT,
            kreirao INTEGER REFERENCES korisnici(id),
            kreirano TIMESTAMP DEFAULT NOW()
        );
        """)

        # Seed admin korisnik
        admin = await conn.fetchrow("SELECT id FROM korisnici WHERE username='admin'")
        if not admin:
            pw = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
            await conn.execute(
                "INSERT INTO korisnici(username,password_hash,ime,uloga) VALUES($1,$2,$3,$4)",
                "admin", pw, "Administrator", "admin"
            )

        # Seed sluzbe
        count = await conn.fetchval("SELECT COUNT(*) FROM sluzbe")
        if count == 0:
            sluzbe = ["IT","HR","Racunovodstvo","Prodaja","Skladiste","Marketing","Menadzment"]
            for s in sluzbe:
                await conn.execute("INSERT INTO sluzbe(naziv) VALUES($1) ON CONFLICT DO NOTHING", s)

            sifre = [
                ("B01","Akutna bolest","Kratkotrajna bolest do 7 dana"),
                ("B02","Operacija","Hirurski zahvat"),
                ("B03","Njega clana porodice","Njega bolesnog djeteta"),
                ("B04","Povreda na radu","Obavezna prijava"),
                ("B05","Hronicna bolest","Dugotrajno lijecenje"),
                ("B09","Ostalo","Drugi razlozi"),
            ]
            for s in sifre:
                await conn.execute("INSERT INTO sifrarnik_bolovanja(sifra,naziv,opis) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", *s)

            tipovi = [
                ("Godisnji odmor", True),("Placeno odsustvo", True),
                ("Neplaceno odsustvo", False),("Sluzbeni put", True),
                ("Obrazovanje", True),("Ostalo", False),
            ]
            for t in tipovi:
                await conn.execute("INSERT INTO tipovi_odsustava(naziv,placeno) VALUES($1,$2) ON CONFLICT DO NOTHING", *t)

            # Demo uposlenici
            sl = await conn.fetch("SELECT id,naziv FROM sluzbe")
            sm = {r['naziv']: r['id'] for r in sl}
            demo = [
                ("Marko","Markovic","marko@firma.ba",sm.get("IT"),"Senior Developer","2021-03-15","Aktivan"),
                ("Ana","Kovacevic","ana@firma.ba",sm.get("Racunovodstvo"),"Racunovoda","2019-07-01","Aktivan"),
                ("Ivan","Petrovic","ivan@firma.ba",sm.get("HR"),"HR Menadzer","2020-01-10","Aktivan"),
                ("Maja","Novak","maja@firma.ba",sm.get("Prodaja"),"Prodajni agent","2022-05-20","Aktivan"),
                ("Elma","Husic","elma@firma.ba",sm.get("IT"),"Junior Developer","2023-02-14","Aktivan"),
            ]
            for d in demo:
                await conn.execute(
                    "INSERT INTO uposlenici(ime,prezime,email,sluzba_id,pozicija,datum_zaposlenja,status) VALUES($1,$2,$3,$4,$5,$6,$7)",
                    *d
                )

# ── Auth ──────────────────────────────────────────────────────────────────────
def create_token(data: dict):
    exp = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({**data, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), request=None):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except:
        raise HTTPException(status_code=401, detail="Nevalidan token")

async def get_pool(request):
    return request.app.state.pool

# ── Dependency ────────────────────────────────────────────────────────────────
from fastapi import Request

async def db(request: Request):
    return request.app.state.pool

# ── Modeli ────────────────────────────────────────────────────────────────────
class UposlenikIn(BaseModel):
    ime: str
    prezime: str
    email: Optional[str] = ""
    sluzba_id: Optional[int] = None
    pozicija: Optional[str] = ""
    datum_zaposlenja: Optional[str] = ""
    status: str = "Aktivan"

class BolovanjeIn(BaseModel):
    uposlenik_id: int
    datum_od: str
    datum_do: str
    dana: int
    sifra: str
    razlog: Optional[str] = ""
    napomena: Optional[str] = ""

class OdsustvoIn(BaseModel):
    uposlenik_id: int
    tip_id: int
    datum_od: str
    datum_do: str
    dana: int
    status: str = "Na cekanju"
    napomena: Optional[str] = ""

class SluzbaIn(BaseModel):
    naziv: str

class SifraIn(BaseModel):
    sifra: str
    naziv: str
    opis: Optional[str] = ""

class TipIn(BaseModel):
    naziv: str
    placeno: bool = True

class KorisnikIn(BaseModel):
    username: str
    password: str
    ime: Optional[str] = ""
    uloga: str = "korisnik"

class PromijeniLozinkuIn(BaseModel):
    stara_lozinka: str
    nova_lozinka: str

# ── AUTH endpoints ────────────────────────────────────────────────────────────
@app.post("/auth/login")
async def login(form: OAuth2PasswordRequestForm = Depends(), request: Request = None):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM korisnici WHERE username=$1 AND aktivan=true", form.username)
        if not user or not bcrypt.checkpw(form.password.encode(), user['password_hash'].encode()):
            raise HTTPException(status_code=401, detail="Pogresno korisnicko ime ili lozinka")
        token = create_token({"sub": user['username'], "id": user['id'], "uloga": user['uloga'], "ime": user['ime']})
        return {"access_token": token, "token_type": "bearer", "uloga": user['uloga'], "ime": user['ime']}

@app.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return user

# ── KORISNICI (samo admin) ────────────────────────────────────────────────────
@app.get("/korisnici")
async def get_korisnici(request: Request, user=Depends(get_current_user)):
    if user['uloga'] != 'admin':
        raise HTTPException(status_code=403, detail="Nemate pristup")
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id,username,ime,uloga,aktivan,kreiran FROM korisnici ORDER BY username")
        return [dict(r) for r in rows]

@app.post("/korisnici")
async def add_korisnik(data: KorisnikIn, request: Request, user=Depends(get_current_user)):
    if user['uloga'] != 'admin':
        raise HTTPException(status_code=403, detail="Nemate pristup")
    pool = request.app.state.pool
    pw = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO korisnici(username,password_hash,ime,uloga) VALUES($1,$2,$3,$4)",
                data.username, pw, data.ime, data.uloga
            )
            return {"ok": True}
        except:
            raise HTTPException(status_code=400, detail="Korisnicko ime vec postoji")

@app.delete("/korisnici/{kid}")
async def del_korisnik(kid: int, request: Request, user=Depends(get_current_user)):
    if user['uloga'] != 'admin':
        raise HTTPException(status_code=403, detail="Nemate pristup")
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("UPDATE korisnici SET aktivan=false WHERE id=$1", kid)
        return {"ok": True}

@app.post("/auth/promijeni-lozinku")
async def promijeni_lozinku(data: PromijeniLozinkuIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        u = await conn.fetchrow("SELECT * FROM korisnici WHERE id=$1", user['id'])
        if not bcrypt.checkpw(data.stara_lozinka.encode(), u['password_hash'].encode()):
            raise HTTPException(status_code=400, detail="Stara lozinka nije tacna")
        pw = bcrypt.hashpw(data.nova_lozinka.encode(), bcrypt.gensalt()).decode()
        await conn.execute("UPDATE korisnici SET password_hash=$1 WHERE id=$2", pw, user['id'])
        return {"ok": True}

# ── SLUZBE ────────────────────────────────────────────────────────────────────
@app.get("/sluzbe")
async def get_sluzbe(request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.id, s.naziv,
                   (SELECT COUNT(*) FROM uposlenici WHERE sluzba_id=s.id) as cnt
            FROM sluzbe s ORDER BY naziv""")
        return [dict(r) for r in rows]

@app.post("/sluzbe")
async def add_sluzba(data: SluzbaIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        try:
            await conn.execute("INSERT INTO sluzbe(naziv) VALUES($1)", data.naziv)
            return {"ok": True}
        except:
            raise HTTPException(status_code=400, detail="Naziv vec postoji")

@app.put("/sluzbe/{sid}")
async def update_sluzba(sid: int, data: SluzbaIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("UPDATE sluzbe SET naziv=$1 WHERE id=$2", data.naziv, sid)
        return {"ok": True}

@app.delete("/sluzbe/{sid}")
async def del_sluzba(sid: int, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        cnt = await conn.fetchval("SELECT COUNT(*) FROM uposlenici WHERE sluzba_id=$1", sid)
        if cnt > 0:
            raise HTTPException(status_code=400, detail=f"Sluzba ima {cnt} uposlenika")
        await conn.execute("DELETE FROM sluzbe WHERE id=$1", sid)
        return {"ok": True}

# ── UPOSLENICI ────────────────────────────────────────────────────────────────
@app.get("/uposlenici")
async def get_uposlenici(request: Request, user=Depends(get_current_user), q: str = ""):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        if q:
            rows = await conn.fetch("""
                SELECT u.*, s.naziv as sluzba_naziv FROM uposlenici u
                LEFT JOIN sluzbe s ON u.sluzba_id=s.id
                WHERE (u.ime||' '||u.prezime) ILIKE $1 ORDER BY u.ime""", f"%{q}%")
        else:
            rows = await conn.fetch("""
                SELECT u.*, s.naziv as sluzba_naziv FROM uposlenici u
                LEFT JOIN sluzbe s ON u.sluzba_id=s.id ORDER BY u.ime""")
        return [dict(r) for r in rows]

@app.post("/uposlenici")
async def add_uposlenik(data: UposlenikIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO uposlenici(ime,prezime,email,sluzba_id,pozicija,datum_zaposlenja,status) VALUES($1,$2,$3,$4,$5,$6,$7)",
            data.ime, data.prezime, data.email, data.sluzba_id, data.pozicija, data.datum_zaposlenja, data.status
        )
        return {"ok": True}

@app.put("/uposlenici/{uid}")
async def update_uposlenik(uid: int, data: UposlenikIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE uposlenici SET ime=$1,prezime=$2,email=$3,sluzba_id=$4,pozicija=$5,datum_zaposlenja=$6,status=$7 WHERE id=$8",
            data.ime, data.prezime, data.email, data.sluzba_id, data.pozicija, data.datum_zaposlenja, data.status, uid
        )
        return {"ok": True}

@app.delete("/uposlenici/{uid}")
async def del_uposlenik(uid: int, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM uposlenici WHERE id=$1", uid)
        return {"ok": True}

# ── SIFRARNIK ─────────────────────────────────────────────────────────────────
@app.get("/sifrarnik")
async def get_sifrarnik(request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM sifrarnik_bolovanja ORDER BY sifra")
        return [dict(r) for r in rows]

@app.post("/sifrarnik")
async def add_sifra(data: SifraIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        try:
            await conn.execute("INSERT INTO sifrarnik_bolovanja(sifra,naziv,opis) VALUES($1,$2,$3)", data.sifra.upper(), data.naziv, data.opis)
            return {"ok": True}
        except:
            raise HTTPException(status_code=400, detail="Sifra vec postoji")

@app.put("/sifrarnik/{sid}")
async def update_sifra(sid: int, data: SifraIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("UPDATE sifrarnik_bolovanja SET sifra=$1,naziv=$2,opis=$3 WHERE id=$4", data.sifra.upper(), data.naziv, data.opis, sid)
        return {"ok": True}

@app.delete("/sifrarnik/{sid}")
async def del_sifra(sid: int, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        sifra = await conn.fetchval("SELECT sifra FROM sifrarnik_bolovanja WHERE id=$1", sid)
        cnt = await conn.fetchval("SELECT COUNT(*) FROM bolovanja WHERE sifra=$1", sifra)
        if cnt > 0:
            raise HTTPException(status_code=400, detail=f"Sifra se koristi u {cnt} bolovanja")
        await conn.execute("DELETE FROM sifrarnik_bolovanja WHERE id=$1", sid)
        return {"ok": True}

# ── TIPOVI ODSUSTAVA ──────────────────────────────────────────────────────────
@app.get("/tipovi-odsustava")
async def get_tipovi(request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM tipovi_odsustava ORDER BY naziv")
        return [dict(r) for r in rows]

@app.post("/tipovi-odsustava")
async def add_tip(data: TipIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        try:
            await conn.execute("INSERT INTO tipovi_odsustava(naziv,placeno) VALUES($1,$2)", data.naziv, data.placeno)
            return {"ok": True}
        except:
            raise HTTPException(status_code=400, detail="Naziv vec postoji")

@app.put("/tipovi-odsustava/{tid}")
async def update_tip(tid: int, data: TipIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("UPDATE tipovi_odsustava SET naziv=$1,placeno=$2 WHERE id=$3", data.naziv, data.placeno, tid)
        return {"ok": True}

@app.delete("/tipovi-odsustava/{tid}")
async def del_tip(tid: int, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        cnt = await conn.fetchval("SELECT COUNT(*) FROM odsustva WHERE tip_id=$1", tid)
        if cnt > 0:
            raise HTTPException(status_code=400, detail=f"Tip se koristi u {cnt} odsustva")
        await conn.execute("DELETE FROM tipovi_odsustava WHERE id=$1", tid)
        return {"ok": True}

# ── BOLOVANJA ─────────────────────────────────────────────────────────────────
@app.get("/bolovanja")
async def get_bolovanja(request: Request, user=Depends(get_current_user), q: str = "", sifra: str = ""):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        sql = """SELECT b.*, u.ime||' '||u.prezime as uposlenik_name, s.naziv as sluzba
                 FROM bolovanja b JOIN uposlenici u ON b.uposlenik_id=u.id
                 LEFT JOIN sluzbe s ON u.sluzba_id=s.id WHERE 1=1"""
        params = []
        if q:
            params.append(f"%{q}%")
            sql += f" AND (u.ime||' '||u.prezime) ILIKE ${len(params)}"
        if sifra:
            params.append(sifra)
            sql += f" AND b.sifra=${len(params)}"
        sql += " ORDER BY b.datum_od DESC"
        rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

@app.post("/bolovanja")
async def add_bolovanje(data: BolovanjeIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bolovanja(uposlenik_id,datum_od,datum_do,dana,sifra,razlog,napomena,kreirao) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
            data.uposlenik_id, data.datum_od, data.datum_do, data.dana, data.sifra, data.razlog, data.napomena, user['id']
        )
        return {"ok": True}

@app.put("/bolovanja/{bid}")
async def update_bolovanje(bid: int, data: BolovanjeIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE bolovanja SET uposlenik_id=$1,datum_od=$2,datum_do=$3,dana=$4,sifra=$5,razlog=$6,napomena=$7 WHERE id=$8",
            data.uposlenik_id, data.datum_od, data.datum_do, data.dana, data.sifra, data.razlog, data.napomena, bid
        )
        return {"ok": True}

@app.delete("/bolovanja/{bid}")
async def del_bolovanje(bid: int, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM bolovanja WHERE id=$1", bid)
        return {"ok": True}

# ── ODSUSTVA ──────────────────────────────────────────────────────────────────
@app.get("/odsustva")
async def get_odsustva(request: Request, user=Depends(get_current_user), tip_id: int = 0, status_filter: str = ""):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        sql = """SELECT o.*, u.ime||' '||u.prezime as uposlenik_name, t.naziv as tip_naziv
                 FROM odsustva o JOIN uposlenici u ON o.uposlenik_id=u.id
                 JOIN tipovi_odsustava t ON o.tip_id=t.id WHERE 1=1"""
        params = []
        if tip_id:
            params.append(tip_id)
            sql += f" AND o.tip_id=${len(params)}"
        if status_filter:
            params.append(status_filter)
            sql += f" AND o.status=${len(params)}"
        sql += " ORDER BY o.datum_od DESC"
        rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

@app.post("/odsustva")
async def add_odsustvo(data: OdsustvoIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO odsustva(uposlenik_id,tip_id,datum_od,datum_do,dana,status,napomena,kreirao) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
            data.uposlenik_id, data.tip_id, data.datum_od, data.datum_do, data.dana, data.status, data.napomena, user['id']
        )
        return {"ok": True}

@app.put("/odsustva/{oid}")
async def update_odsustvo(oid: int, data: OdsustvoIn, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE odsustva SET uposlenik_id=$1,tip_id=$2,datum_od=$3,datum_do=$4,dana=$5,status=$6,napomena=$7 WHERE id=$8",
            data.uposlenik_id, data.tip_id, data.datum_od, data.datum_do, data.dana, data.status, data.napomena, oid
        )
        return {"ok": True}

@app.patch("/odsustva/{oid}/status")
async def update_status(oid: int, body: dict, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("UPDATE odsustva SET status=$1 WHERE id=$2", body.get("status"), oid)
        return {"ok": True}

@app.delete("/odsustva/{oid}")
async def del_odsustvo(oid: int, request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM odsustva WHERE id=$1", oid)
        return {"ok": True}

# ── STATISTIKE ────────────────────────────────────────────────────────────────
@app.get("/statistike/dashboard")
async def dashboard_stats(request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        uposlenici = await conn.fetchval("SELECT COUNT(*) FROM uposlenici WHERE status='Aktivan'")
        bolovanja = await conn.fetchval("SELECT COUNT(*) FROM bolovanja")
        dana = await conn.fetchval("SELECT COALESCE(SUM(dana),0) FROM bolovanja")
        aktivna = await conn.fetchval("SELECT COUNT(*) FROM bolovanja WHERE datum_do >= CURRENT_DATE::text")
        by_sluzba = await conn.fetch("""
            SELECT s.naziv, COALESCE(SUM(b.dana),0) as dana
            FROM sluzbe s LEFT JOIN uposlenici u ON u.sluzba_id=s.id
            LEFT JOIN bolovanja b ON b.uposlenik_id=u.id
            GROUP BY s.id ORDER BY dana DESC""")
        by_sifra = await conn.fetch("""
            SELECT sb.sifra, sb.naziv, COALESCE(SUM(b.dana),0) as dana
            FROM sifrarnik_bolovanja sb LEFT JOIN bolovanja b ON b.sifra=sb.sifra
            GROUP BY sb.id ORDER BY dana DESC""")
        recent = await conn.fetch("""
            SELECT u.ime||' '||u.prezime as name, s.naziv as sluzba,
                   b.datum_od, b.datum_do, b.dana, b.razlog
            FROM bolovanja b JOIN uposlenici u ON b.uposlenik_id=u.id
            LEFT JOIN sluzbe s ON u.sluzba_id=s.id
            ORDER BY b.datum_od DESC LIMIT 8""")
        return {
            "uposlenici": uposlenici, "bolovanja": bolovanja,
            "dana": dana, "aktivna": aktivna,
            "by_sluzba": [dict(r) for r in by_sluzba],
            "by_sifra": [dict(r) for r in by_sifra],
            "recent": [dict(r) for r in recent],
        }

@app.get("/statistike/detalji")
async def statistike_detalji(request: Request, user=Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        by_emp = await conn.fetch("""
            SELECT u.ime||' '||u.prezime as name,
                   (SELECT naziv FROM sluzbe WHERE id=u.sluzba_id) as sluzba,
                   COUNT(b.id) as slucajeva, COALESCE(SUM(b.dana),0) as dana
            FROM uposlenici u LEFT JOIN bolovanja b ON b.uposlenik_id=u.id
            WHERE u.status='Aktivan' GROUP BY u.id ORDER BY dana DESC""")
        by_month = await conn.fetch("""
            SELECT SUBSTRING(datum_od,6,2) as mj, SUM(dana) as dana
            FROM bolovanja WHERE SUBSTRING(datum_od,1,4)='2026'
            GROUP BY mj ORDER BY mj""")
        by_tip = await conn.fetch("""
            SELECT t.naziv, COUNT(o.id) as zahtjeva, COALESCE(SUM(o.dana),0) as dana,
                   SUM(CASE WHEN o.status='Odobreno' THEN 1 ELSE 0 END) as odobreno
            FROM tipovi_odsustava t LEFT JOIN odsustva o ON o.tip_id=t.id
            GROUP BY t.id ORDER BY zahtjeva DESC""")
        return {
            "by_emp": [dict(r) for r in by_emp],
            "by_month": [dict(r) for r in by_month],
            "by_tip": [dict(r) for r in by_tip],
        }

@app.get("/")
async def root():
    return {"status": "HR Sistem API radi!", "verzija": "1.0.0"}
