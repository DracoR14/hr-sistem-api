"""
EVOS — HR Management System
Backend API v2.0
FastAPI + PostgreSQL (SQLAlchemy) + JWT + Licence sistem
"""

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta, date
import jwt
import bcrypt
import os
import secrets
import string
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from contextlib import asynccontextmanager

# ── Config ─────────────────────────────────────────────────────────────────
SECRET_KEY  = os.getenv("SECRET_KEY", "evos-tajni-kljuc-2026-promijeniti!")
ALGORITHM   = "HS256"
TOKEN_HOURS = 24
DB_URL      = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/evosdb")

if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DB_URL, poolclass=QueuePool, pool_size=5, max_overflow=10)

# ── App ─────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="EVOS API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# ── DB Init ──────────────────────────────────────────────────────────────────
def init_db():
    with engine.connect() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS licence (
            id SERIAL PRIMARY KEY,
            kljuc TEXT NOT NULL UNIQUE,
            firma TEXT NOT NULL,
            email TEXT,
            plan TEXT DEFAULT 'basic',
            max_uposlenici INTEGER DEFAULT 25,
            datum_pocetka TEXT,
            datum_isteka TEXT,
            aktivna BOOLEAN DEFAULT true,
            napomena TEXT,
            kreirana TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS korisnici (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            ime TEXT,
            uloga TEXT DEFAULT 'korisnik',
            licenca_id INTEGER REFERENCES licence(id),
            aktivan BOOLEAN DEFAULT true,
            jezik TEXT DEFAULT 'bs',
            kreiran TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS sluzbe (
            id SERIAL PRIMARY KEY,
            naziv TEXT NOT NULL,
            licenca_id INTEGER REFERENCES licence(id),
            UNIQUE(naziv, licenca_id)
        );
        CREATE TABLE IF NOT EXISTS uposlenici (
            id SERIAL PRIMARY KEY,
            ime TEXT NOT NULL, prezime TEXT NOT NULL,
            email TEXT, sluzba_id INTEGER REFERENCES sluzbe(id),
            pozicija TEXT, datum_zaposlenja TEXT,
            status TEXT DEFAULT 'Aktivan',
            licenca_id INTEGER REFERENCES licence(id)
        );
        CREATE TABLE IF NOT EXISTS sifrarnik_bolovanja (
            id SERIAL PRIMARY KEY,
            sifra TEXT NOT NULL, naziv TEXT NOT NULL, opis TEXT,
            licenca_id INTEGER REFERENCES licence(id),
            UNIQUE(sifra, licenca_id)
        );
        CREATE TABLE IF NOT EXISTS tipovi_odsustava (
            id SERIAL PRIMARY KEY,
            naziv TEXT NOT NULL, placeno BOOLEAN DEFAULT true,
            licenca_id INTEGER REFERENCES licence(id),
            UNIQUE(naziv, licenca_id)
        );
        CREATE TABLE IF NOT EXISTS bolovanja (
            id SERIAL PRIMARY KEY,
            uposlenik_id INTEGER REFERENCES uposlenici(id),
            datum_od TEXT, datum_do TEXT, dana INTEGER,
            sifra TEXT, razlog TEXT, napomena TEXT,
            kreirao INTEGER REFERENCES korisnici(id),
            licenca_id INTEGER REFERENCES licence(id),
            kreirano TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS odsustva (
            id SERIAL PRIMARY KEY,
            uposlenik_id INTEGER REFERENCES uposlenici(id),
            tip_id INTEGER REFERENCES tipovi_odsustava(id),
            datum_od TEXT, datum_do TEXT, dana INTEGER,
            status TEXT DEFAULT 'Na cekanju', napomena TEXT,
            kreirao INTEGER REFERENCES korisnici(id),
            licenca_id INTEGER REFERENCES licence(id),
            kreirano TIMESTAMP DEFAULT NOW()
        );
        """))

        # Master admin licenca
        lic = conn.execute(text("SELECT id FROM licence WHERE kljuc='EVOS-MASTER-0000'")).fetchone()
        if not lic:
            conn.execute(text("""
                INSERT INTO licence(kljuc,firma,email,plan,max_uposlenici,datum_pocetka,datum_isteka,aktivna,napomena)
                VALUES('EVOS-MASTER-0000','EVOS Admin','admin@evos.ba','master',9999,'2026-01-01','2099-12-31',true,'Master admin licenca')
            """))
            conn.commit()
            lic = conn.execute(text("SELECT id FROM licence WHERE kljuc='EVOS-MASTER-0000'")).fetchone()

        lid = lic[0]
        admin = conn.execute(text("SELECT id FROM korisnici WHERE username='admin'")).fetchone()
        if not admin:
            pw = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
            conn.execute(text(
                "INSERT INTO korisnici(username,password_hash,ime,uloga,licenca_id) VALUES(:u,:p,:i,:r,:l)"),
                {"u": "admin", "p": pw, "i": "Administrator", "r": "superadmin", "l": lid})

        cnt = conn.execute(text("SELECT COUNT(*) FROM sluzbe WHERE licenca_id=:l"), {"l": lid}).fetchone()[0]
        if cnt == 0:
            for s in ["IT","HR","Racunovodstvo","Prodaja","Skladiste","Marketing"]:
                conn.execute(text("INSERT INTO sluzbe(naziv,licenca_id) VALUES(:n,:l)"), {"n": s, "l": lid})
            for sf in [("B01","Akutna bolest",""),("B02","Operacija",""),("B03","Njega clana porodice",""),
                        ("B04","Povreda na radu",""),("B05","Hronicna bolest",""),("B09","Ostalo","")]:
                conn.execute(text("INSERT INTO sifrarnik_bolovanja(sifra,naziv,opis,licenca_id) VALUES(:s,:n,:o,:l)"),
                             {"s": sf[0], "n": sf[1], "o": sf[2], "l": lid})
            for tp in [("Godisnji odmor",True),("Placeno odsustvo",True),("Neplaceno odsustvo",False),
                        ("Sluzbeni put",True),("Obrazovanje",True),("Ostalo",False)]:
                conn.execute(text("INSERT INTO tipovi_odsustava(naziv,placeno,licenca_id) VALUES(:n,:p,:l)"),
                             {"n": tp[0], "p": tp[1], "l": lid})
        conn.commit()

# ── Helpers ───────────────────────────────────────────────────────────────────
def create_token(data: dict):
    exp = datetime.utcnow() + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({**data, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except:
        raise HTTPException(status_code=401, detail="Nevalidan token")

def db_exec(sql, params=None):
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        conn.commit()
        return result

def db_fetch(sql, params=None):
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        cols = result.keys()
        return [dict(zip(cols, row)) for row in result.fetchall()]

def db_one(sql, params=None):
    rows = db_fetch(sql, params)
    return rows[0] if rows else None

def gen_licence_key(plan="basic"):
    chars = string.ascii_uppercase + string.digits
    parts = [''.join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
    prefix = {"basic": "EVOS-B", "pro": "EVOS-P", "enterprise": "EVOS-E", "master": "EVOS-M"}.get(plan, "EVOS-X")
    return f"{prefix}-{'-'.join(parts)}"

def lid(user):
    return user.get('licenca_id')

# ── Modeli ────────────────────────────────────────────────────────────────────
class UposlenikIn(BaseModel):
    ime: str; prezime: str; email: Optional[str]=""
    sluzba_id: Optional[int]=None; pozicija: Optional[str]=""
    datum_zaposlenja: Optional[str]=""; status: str="Aktivan"

class BolovanjeIn(BaseModel):
    uposlenik_id: int; datum_od: str; datum_do: str; dana: int
    sifra: str; razlog: Optional[str]=""; napomena: Optional[str]=""

class OdsustvoIn(BaseModel):
    uposlenik_id: int; tip_id: int; datum_od: str; datum_do: str
    dana: int; status: str="Na cekanju"; napomena: Optional[str]=""

class SluzbaIn(BaseModel):
    naziv: str

class SifraIn(BaseModel):
    sifra: str; naziv: str; opis: Optional[str]=""

class TipIn(BaseModel):
    naziv: str; placeno: bool=True

class KorisnikIn(BaseModel):
    username: str; password: str; ime: Optional[str]=""
    uloga: str="korisnik"; licenca_id: Optional[int]=None

class KorisnikUpdateIn(BaseModel):
    ime: Optional[str]=None
    uloga: Optional[str]=None
    nova_lozinka: Optional[str]=None
    aktivan: Optional[bool]=None

class LicencaIn(BaseModel):
    firma: str; email: Optional[str]=""
    plan: str="basic"; max_uposlenici: int=25
    datum_pocetka: str; datum_isteka: str
    napomena: Optional[str]=""

class StatusIn(BaseModel):
    status: str

class JezikIn(BaseModel):
    jezik: str

# ── ROOT ──────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "EVOS API radi!", "verzija": "2.0.0"}

# ── AUTH ──────────────────────────────────────────────────────────────────────
@app.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = db_one("SELECT * FROM korisnici WHERE username=:u AND aktivan=true", {"u": form.username})
    if not user or not bcrypt.checkpw(form.password.encode(), user['password_hash'].encode()):
        raise HTTPException(status_code=401, detail="Pogresno korisnicko ime ili lozinka")

    if user['uloga'] != 'superadmin' and user.get('licenca_id'):
        lic = db_one("SELECT * FROM licence WHERE id=:l", {"l": user['licenca_id']})
        if not lic or not lic['aktivna']:
            raise HTTPException(status_code=403, detail="Licenca nije aktivna")
        if lic['datum_isteka'] < date.today().isoformat():
            raise HTTPException(status_code=403, detail="Licenca je istekla")

    token = create_token({
        "sub": user['username'], "id": user['id'],
        "uloga": user['uloga'], "ime": user['ime'] or "",
        "licenca_id": user.get('licenca_id'), "jezik": user.get('jezik','bs')
    })
    return {"access_token": token, "token_type": "bearer",
            "uloga": user['uloga'], "ime": user['ime'] or "",
            "jezik": user.get('jezik','bs'), "licenca_id": user.get('licenca_id')}

@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    return user

@app.put("/auth/jezik")
def set_jezik(data: JezikIn, user=Depends(get_current_user)):
    db_exec("UPDATE korisnici SET jezik=:j WHERE id=:i", {"j": data.jezik, "i": user['id']})
    return {"ok": True}

# ── LICENCE ─────────────────────────────────────────────────────────────────
@app.get("/licence")
def get_licence(user=Depends(get_current_user)):
    if user['uloga'] != 'superadmin':
        raise HTTPException(403, "Nemate pristup")
    return db_fetch("SELECT * FROM licence ORDER BY kreirana DESC")

@app.post("/licence")
def create_licenca(data: LicencaIn, user=Depends(get_current_user)):
    if user['uloga'] != 'superadmin':
        raise HTTPException(403, "Nemate pristup")
    kljuc = gen_licence_key(data.plan)
    db_exec("""INSERT INTO licence(kljuc,firma,email,plan,max_uposlenici,datum_pocetka,datum_isteka,aktivna,napomena)
               VALUES(:k,:f,:e,:p,:m,:od,:do,true,:n)""",
            {"k": kljuc, "f": data.firma, "e": data.email, "p": data.plan,
             "m": data.max_uposlenici, "od": data.datum_pocetka, "do": data.datum_isteka, "n": data.napomena})
    lic = db_one("SELECT * FROM licence WHERE kljuc=:k", {"k": kljuc})
    lid_new = lic['id']
    for s in ["IT","HR","Racunovodstvo","Prodaja","Skladiste","Ostalo"]:
        db_exec("INSERT INTO sluzbe(naziv,licenca_id) VALUES(:n,:l) ON CONFLICT DO NOTHING", {"n": s, "l": lid_new})
    for sf in [("B01","Akutna bolest"),("B02","Operacija"),("B03","Njega clana porodice"),
                ("B04","Povreda na radu"),("B05","Hronicna bolest"),("B09","Ostalo")]:
        db_exec("INSERT INTO sifrarnik_bolovanja(sifra,naziv,opis,licenca_id) VALUES(:s,:n,:o,:l) ON CONFLICT DO NOTHING",
                {"s": sf[0], "n": sf[1], "o": "", "l": lid_new})
    for tp in [("Godisnji odmor",True),("Placeno odsustvo",True),("Sluzbeni put",True),
                ("Neplaceno odsustvo",False),("Ostalo",False)]:
        db_exec("INSERT INTO tipovi_odsustava(naziv,placeno,licenca_id) VALUES(:n,:p,:l) ON CONFLICT DO NOTHING",
                {"n": tp[0], "p": tp[1], "l": lid_new})
    return {"ok": True, "kljuc": kljuc, "licenca": lic}

@app.put("/licence/{lid_id}/toggle")
def toggle_licenca(lid_id: int, user=Depends(get_current_user)):
    if user['uloga'] != 'superadmin':
        raise HTTPException(403, "Nemate pristup")
    db_exec("UPDATE licence SET aktivna = NOT aktivna WHERE id=:l", {"l": lid_id})
    return {"ok": True}

@app.delete("/licence/{lid_id}")
def del_licenca(lid_id: int, user=Depends(get_current_user)):
    if user['uloga'] != 'superadmin':
        raise HTTPException(403, "Nemate pristup")
    db_exec("UPDATE licence SET aktivna=false WHERE id=:l", {"l": lid_id})
    return {"ok": True}

@app.get("/licence/provjeri/{kljuc}")
def provjeri_licencu(kljuc: str):
    lic = db_one("SELECT * FROM licence WHERE kljuc=:k", {"k": kljuc})
    if not lic:
        return {"validna": False, "poruka": "Licenca ne postoji"}
    if not lic['aktivna']:
        return {"validna": False, "poruka": "Licenca nije aktivna"}
    if lic['datum_isteka'] < date.today().isoformat():
        return {"validna": False, "poruka": "Licenca je istekla"}
    return {"validna": True, "firma": lic['firma'], "plan": lic['plan'],
            "max_uposlenici": lic['max_uposlenici'], "istice": lic['datum_isteka']}

# ── KORISNICI ─────────────────────────────────────────────────────────────────
@app.get("/korisnici")
def get_korisnici(user=Depends(get_current_user)):
    if user['uloga'] not in ('superadmin', 'admin'):
        raise HTTPException(403, "Nemate pristup")
    if user['uloga'] == 'superadmin':
        return db_fetch("SELECT id,username,ime,uloga,licenca_id,aktivan,jezik FROM korisnici ORDER BY username")
    return db_fetch("SELECT id,username,ime,uloga,licenca_id,aktivan,jezik FROM korisnici WHERE licenca_id=:l ORDER BY username",
                    {"l": lid(user)})

@app.post("/korisnici")
def add_korisnik(data: KorisnikIn, user=Depends(get_current_user)):
    if user['uloga'] not in ('superadmin', 'admin'):
        raise HTTPException(403, "Nemate pristup")
    l = data.licenca_id if user['uloga'] == 'superadmin' else lid(user)
    pw = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    try:
        db_exec("INSERT INTO korisnici(username,password_hash,ime,uloga,licenca_id) VALUES(:u,:p,:i,:r,:l)",
                {"u": data.username, "p": pw, "i": data.ime, "r": data.uloga, "l": l})
        return {"ok": True}
    except:
        raise HTTPException(400, "Korisnicko ime vec postoji")

@app.put("/korisnici/{kid}")
def update_korisnik(kid: int, data: KorisnikUpdateIn, user=Depends(get_current_user)):
    if user['uloga'] not in ('superadmin', 'admin'):
        raise HTTPException(403, "Nemate pristup")
    if data.ime is not None:
        db_exec("UPDATE korisnici SET ime=:i WHERE id=:k", {"i": data.ime, "k": kid})
    if data.uloga is not None and user['uloga'] == 'superadmin':
        db_exec("UPDATE korisnici SET uloga=:u WHERE id=:k", {"u": data.uloga, "k": kid})
    if data.nova_lozinka:
        pw = bcrypt.hashpw(data.nova_lozinka.encode(), bcrypt.gensalt()).decode()
        db_exec("UPDATE korisnici SET password_hash=:p WHERE id=:k", {"p": pw, "k": kid})
    if data.aktivan is not None:
        db_exec("UPDATE korisnici SET aktivan=:a WHERE id=:k", {"a": data.aktivan, "k": kid})
    return {"ok": True}

@app.delete("/korisnici/{kid}")
def del_korisnik(kid: int, user=Depends(get_current_user)):
    if user['uloga'] not in ('superadmin', 'admin'):
        raise HTTPException(403, "Nemate pristup")
    db_exec("UPDATE korisnici SET aktivan=false WHERE id=:k", {"k": kid})
    return {"ok": True}

# ── SLUZBE ────────────────────────────────────────────────────────────────────
@app.get("/sluzbe")
def get_sluzbe(user=Depends(get_current_user)):
    return db_fetch("SELECT s.*,(SELECT COUNT(*) FROM uposlenici WHERE sluzba_id=s.id) as cnt FROM sluzbe s WHERE licenca_id=:l ORDER BY naziv", {"l": lid(user)})

@app.post("/sluzbe")
def add_sluzba(data: SluzbaIn, user=Depends(get_current_user)):
    try:
        db_exec("INSERT INTO sluzbe(naziv,licenca_id) VALUES(:n,:l)", {"n": data.naziv, "l": lid(user)})
        return {"ok": True}
    except:
        raise HTTPException(400, "Naziv vec postoji")

@app.put("/sluzbe/{sid}")
def update_sluzba(sid: int, data: SluzbaIn, user=Depends(get_current_user)):
    db_exec("UPDATE sluzbe SET naziv=:n WHERE id=:s AND licenca_id=:l", {"n": data.naziv, "s": sid, "l": lid(user)})
    return {"ok": True}

@app.delete("/sluzbe/{sid}")
def del_sluzba(sid: int, user=Depends(get_current_user)):
    cnt = db_one("SELECT COUNT(*) as c FROM uposlenici WHERE sluzba_id=:s", {"s": sid})['c']
    if cnt > 0:
        raise HTTPException(400, f"Sluzba ima {cnt} uposlenika")
    db_exec("DELETE FROM sluzbe WHERE id=:s AND licenca_id=:l", {"s": sid, "l": lid(user)})
    return {"ok": True}

# ── UPOSLENICI ────────────────────────────────────────────────────────────────
@app.get("/uposlenici")
def get_uposlenici(user=Depends(get_current_user), q: str=""):
    if q:
        return db_fetch("""SELECT u.*,s.naziv as sluzba_naziv FROM uposlenici u
            LEFT JOIN sluzbe s ON u.sluzba_id=s.id
            WHERE u.licenca_id=:l AND (u.ime||' '||u.prezime) ILIKE :q ORDER BY u.ime""",
            {"l": lid(user), "q": f"%{q}%"})
    return db_fetch("""SELECT u.*,s.naziv as sluzba_naziv FROM uposlenici u
        LEFT JOIN sluzbe s ON u.sluzba_id=s.id WHERE u.licenca_id=:l ORDER BY u.ime""", {"l": lid(user)})

@app.post("/uposlenici")
def add_uposlenik(data: UposlenikIn, user=Depends(get_current_user)):
    cnt = db_one("SELECT COUNT(*) as c FROM uposlenici WHERE licenca_id=:l AND status='Aktivan'", {"l": lid(user)})['c']
    lic_data = db_one("SELECT max_uposlenici FROM licence WHERE id=:l", {"l": lid(user)})
    if lic_data and cnt >= lic_data['max_uposlenici']:
        raise HTTPException(400, f"Dostigli ste maksimum od {lic_data['max_uposlenici']} uposlenika")
    db_exec("""INSERT INTO uposlenici(ime,prezime,email,sluzba_id,pozicija,datum_zaposlenja,status,licenca_id)
               VALUES(:im,:pr,:em,:sl,:po,:da,:st,:l)""",
            {"im": data.ime, "pr": data.prezime, "em": data.email, "sl": data.sluzba_id,
             "po": data.pozicija, "da": data.datum_zaposlenja, "st": data.status, "l": lid(user)})
    return {"ok": True}

@app.put("/uposlenici/{uid}")
def update_uposlenik(uid: int, data: UposlenikIn, user=Depends(get_current_user)):
    db_exec("""UPDATE uposlenici SET ime=:im,prezime=:pr,email=:em,sluzba_id=:sl,
               pozicija=:po,datum_zaposlenja=:da,status=:st WHERE id=:uid AND licenca_id=:l""",
            {"im": data.ime, "pr": data.prezime, "em": data.email, "sl": data.sluzba_id,
             "po": data.pozicija, "da": data.datum_zaposlenja, "st": data.status, "uid": uid, "l": lid(user)})
    return {"ok": True}

@app.delete("/uposlenici/{uid}")
def del_uposlenik(uid: int, user=Depends(get_current_user)):
    db_exec("DELETE FROM uposlenici WHERE id=:uid AND licenca_id=:l", {"uid": uid, "l": lid(user)})
    return {"ok": True}

# ── SIFRARNIK ─────────────────────────────────────────────────────────────────
@app.get("/sifrarnik")
def get_sifrarnik(user=Depends(get_current_user)):
    return db_fetch("SELECT * FROM sifrarnik_bolovanja WHERE licenca_id=:l ORDER BY sifra", {"l": lid(user)})

@app.post("/sifrarnik")
def add_sifra(data: SifraIn, user=Depends(get_current_user)):
    try:
        db_exec("INSERT INTO sifrarnik_bolovanja(sifra,naziv,opis,licenca_id) VALUES(:s,:n,:o,:l)",
                {"s": data.sifra.upper(), "n": data.naziv, "o": data.opis, "l": lid(user)})
        return {"ok": True}
    except:
        raise HTTPException(400, "Sifra vec postoji")

@app.put("/sifrarnik/{sid}")
def update_sifra(sid: int, data: SifraIn, user=Depends(get_current_user)):
    db_exec("UPDATE sifrarnik_bolovanja SET sifra=:s,naziv=:n,opis=:o WHERE id=:sid AND licenca_id=:l",
            {"s": data.sifra.upper(), "n": data.naziv, "o": data.opis, "sid": sid, "l": lid(user)})
    return {"ok": True}

@app.delete("/sifrarnik/{sid}")
def del_sifra(sid: int, user=Depends(get_current_user)):
    sifra = db_one("SELECT sifra FROM sifrarnik_bolovanja WHERE id=:s", {"s": sid})
    if sifra:
        cnt = db_one("SELECT COUNT(*) as c FROM bolovanja WHERE sifra=:sf AND licenca_id=:l",
                     {"sf": sifra['sifra'], "l": lid(user)})['c']
        if cnt > 0:
            raise HTTPException(400, f"Sifra se koristi u {cnt} bolovanja")
    db_exec("DELETE FROM sifrarnik_bolovanja WHERE id=:s AND licenca_id=:l", {"s": sid, "l": lid(user)})
    return {"ok": True}

# ── TIPOVI ODSUSTAVA ──────────────────────────────────────────────────────────
@app.get("/tipovi-odsustava")
def get_tipovi(user=Depends(get_current_user)):
    return db_fetch("SELECT * FROM tipovi_odsustava WHERE licenca_id=:l ORDER BY naziv", {"l": lid(user)})

@app.post("/tipovi-odsustava")
def add_tip(data: TipIn, user=Depends(get_current_user)):
    try:
        db_exec("INSERT INTO tipovi_odsustava(naziv,placeno,licenca_id) VALUES(:n,:p,:l)",
                {"n": data.naziv, "p": data.placeno, "l": lid(user)})
        return {"ok": True}
    except:
        raise HTTPException(400, "Naziv vec postoji")

@app.put("/tipovi-odsustava/{tid}")
def update_tip(tid: int, data: TipIn, user=Depends(get_current_user)):
    db_exec("UPDATE tipovi_odsustava SET naziv=:n,placeno=:p WHERE id=:t AND licenca_id=:l",
            {"n": data.naziv, "p": data.placeno, "t": tid, "l": lid(user)})
    return {"ok": True}

@app.delete("/tipovi-odsustava/{tid}")
def del_tip(tid: int, user=Depends(get_current_user)):
    cnt = db_one("SELECT COUNT(*) as c FROM odsustva WHERE tip_id=:t", {"t": tid})['c']
    if cnt > 0:
        raise HTTPException(400, f"Tip se koristi u {cnt} odsustva")
    db_exec("DELETE FROM tipovi_odsustava WHERE id=:t AND licenca_id=:l", {"t": tid, "l": lid(user)})
    return {"ok": True}

# ── BOLOVANJA ─────────────────────────────────────────────────────────────────
@app.get("/bolovanja")
def get_bolovanja(user=Depends(get_current_user), q: str="", sifra: str=""):
    sql = """SELECT b.*,u.ime||' '||u.prezime as uposlenik_name,s.naziv as sluzba
             FROM bolovanja b JOIN uposlenici u ON b.uposlenik_id=u.id
             LEFT JOIN sluzbe s ON u.sluzba_id=s.id WHERE b.licenca_id=:l"""
    params = {"l": lid(user)}
    if q:
        sql += " AND (u.ime||' '||u.prezime) ILIKE :q"; params["q"] = f"%{q}%"
    if sifra:
        sql += " AND b.sifra=:sf"; params["sf"] = sifra
    return db_fetch(sql + " ORDER BY b.datum_od DESC", params)

@app.post("/bolovanja")
def add_bolovanje(data: BolovanjeIn, user=Depends(get_current_user)):
    db_exec("""INSERT INTO bolovanja(uposlenik_id,datum_od,datum_do,dana,sifra,razlog,napomena,kreirao,licenca_id)
               VALUES(:ui,:od,:do,:da,:sf,:ra,:na,:kr,:l)""",
            {"ui": data.uposlenik_id, "od": data.datum_od, "do": data.datum_do, "da": data.dana,
             "sf": data.sifra, "ra": data.razlog, "na": data.napomena, "kr": user['id'], "l": lid(user)})
    return {"ok": True}

@app.put("/bolovanja/{bid}")
def update_bolovanje(bid: int, data: BolovanjeIn, user=Depends(get_current_user)):
    db_exec("""UPDATE bolovanja SET uposlenik_id=:ui,datum_od=:od,datum_do=:do,dana=:da,
               sifra=:sf,razlog=:ra,napomena=:na WHERE id=:bid AND licenca_id=:l""",
            {"ui": data.uposlenik_id, "od": data.datum_od, "do": data.datum_do, "da": data.dana,
             "sf": data.sifra, "ra": data.razlog, "na": data.napomena, "bid": bid, "l": lid(user)})
    return {"ok": True}

@app.delete("/bolovanja/{bid}")
def del_bolovanje(bid: int, user=Depends(get_current_user)):
    db_exec("DELETE FROM bolovanja WHERE id=:bid AND licenca_id=:l", {"bid": bid, "l": lid(user)})
    return {"ok": True}

# ── ODSUSTVA ──────────────────────────────────────────────────────────────────
@app.get("/odsustva")
def get_odsustva(user=Depends(get_current_user), tip_id: int=0, status_filter: str=""):
    sql = """SELECT o.*,u.ime||' '||u.prezime as uposlenik_name,t.naziv as tip_naziv
             FROM odsustva o JOIN uposlenici u ON o.uposlenik_id=u.id
             JOIN tipovi_odsustava t ON o.tip_id=t.id WHERE o.licenca_id=:l"""
    params = {"l": lid(user)}
    if tip_id:
        sql += " AND o.tip_id=:t"; params["t"] = tip_id
    if status_filter:
        sql += " AND o.status=:st"; params["st"] = status_filter
    return db_fetch(sql + " ORDER BY o.datum_od DESC", params)

@app.post("/odsustva")
def add_odsustvo(data: OdsustvoIn, user=Depends(get_current_user)):
    db_exec("""INSERT INTO odsustva(uposlenik_id,tip_id,datum_od,datum_do,dana,status,napomena,kreirao,licenca_id)
               VALUES(:ui,:ti,:od,:do,:da,:st,:na,:kr,:l)""",
            {"ui": data.uposlenik_id, "ti": data.tip_id, "od": data.datum_od, "do": data.datum_do,
             "da": data.dana, "st": data.status, "na": data.napomena, "kr": user['id'], "l": lid(user)})
    return {"ok": True}

@app.put("/odsustva/{oid}")
def update_odsustvo(oid: int, data: OdsustvoIn, user=Depends(get_current_user)):
    db_exec("""UPDATE odsustva SET uposlenik_id=:ui,tip_id=:ti,datum_od=:od,datum_do=:do,
               dana=:da,status=:st,napomena=:na WHERE id=:oid AND licenca_id=:l""",
            {"ui": data.uposlenik_id, "ti": data.tip_id, "od": data.datum_od, "do": data.datum_do,
             "da": data.dana, "st": data.status, "na": data.napomena, "oid": oid, "l": lid(user)})
    return {"ok": True}

@app.patch("/odsustva/{oid}/status")
def patch_status(oid: int, data: StatusIn, user=Depends(get_current_user)):
    db_exec("UPDATE odsustva SET status=:st WHERE id=:oid AND licenca_id=:l",
            {"st": data.status, "oid": oid, "l": lid(user)})
    return {"ok": True}

@app.delete("/odsustva/{oid}")
def del_odsustvo(oid: int, user=Depends(get_current_user)):
    db_exec("DELETE FROM odsustva WHERE id=:oid AND licenca_id=:l", {"oid": oid, "l": lid(user)})
    return {"ok": True}

# ── STATISTIKE ────────────────────────────────────────────────────────────────
@app.get("/statistike/dashboard")
def dashboard_stats(user=Depends(get_current_user)):
    l = lid(user)
    uposlenici = db_one("SELECT COUNT(*) as c FROM uposlenici WHERE licenca_id=:l AND status='Aktivan'", {"l": l})['c']
    bolovanja  = db_one("SELECT COUNT(*) as c FROM bolovanja WHERE licenca_id=:l", {"l": l})['c']
    dana       = db_one("SELECT COALESCE(SUM(dana),0) as c FROM bolovanja WHERE licenca_id=:l", {"l": l})['c']
    aktivna    = db_one("SELECT COUNT(*) as c FROM bolovanja WHERE licenca_id=:l AND datum_do>=:d", {"l": l, "d": date.today().isoformat()})['c']
    by_sluzba  = db_fetch("""SELECT s.naziv,COALESCE(SUM(b.dana),0) as dana
        FROM sluzbe s LEFT JOIN uposlenici u ON u.sluzba_id=s.id
        LEFT JOIN bolovanja b ON b.uposlenik_id=u.id
        WHERE s.licenca_id=:l GROUP BY s.id ORDER BY dana DESC""", {"l": l})
    by_sifra   = db_fetch("""SELECT sb.sifra,sb.naziv,COALESCE(SUM(b.dana),0) as dana
        FROM sifrarnik_bolovanja sb LEFT JOIN bolovanja b ON b.sifra=sb.sifra AND b.licenca_id=:l
        WHERE sb.licenca_id=:l GROUP BY sb.id ORDER BY dana DESC""", {"l": l})
    recent     = db_fetch("""SELECT u.ime||' '||u.prezime as name,s.naziv as sluzba,
        b.datum_od,b.datum_do,b.dana,b.razlog
        FROM bolovanja b JOIN uposlenici u ON b.uposlenik_id=u.id
        LEFT JOIN sluzbe s ON u.sluzba_id=s.id
        WHERE b.licenca_id=:l ORDER BY b.datum_od DESC LIMIT 8""", {"l": l})
    return {"uposlenici": uposlenici, "bolovanja": bolovanja, "dana": dana, "aktivna": aktivna,
            "by_sluzba": by_sluzba, "by_sifra": by_sifra, "recent": recent}

@app.get("/statistike/detalji")
def statistike_detalji(user=Depends(get_current_user)):
    l = lid(user)
    by_emp = db_fetch("""SELECT u.ime||' '||u.prezime as name,
        (SELECT naziv FROM sluzbe WHERE id=u.sluzba_id) as sluzba,
        COUNT(b.id) as slucajeva,COALESCE(SUM(b.dana),0) as dana
        FROM uposlenici u LEFT JOIN bolovanja b ON b.uposlenik_id=u.id
        WHERE u.licenca_id=:l AND u.status='Aktivan' GROUP BY u.id ORDER BY dana DESC""", {"l": l})
    by_month = db_fetch("""SELECT SUBSTRING(datum_od,6,2) as mj,SUM(dana) as dana
        FROM bolovanja WHERE licenca_id=:l AND SUBSTRING(datum_od,1,4)=:g
        GROUP BY mj ORDER BY mj""", {"l": l, "g": str(date.today().year)})
    by_tip = db_fetch("""SELECT t.naziv,COUNT(o.id) as zahtjeva,COALESCE(SUM(o.dana),0) as dana,
        SUM(CASE WHEN o.status='Odobreno' THEN 1 ELSE 0 END) as odobreno
        FROM tipovi_odsustava t LEFT JOIN odsustva o ON o.tip_id=t.id
        WHERE t.licenca_id=:l GROUP BY t.id ORDER BY zahtjeva DESC""", {"l": l})
    return {"by_emp": by_emp, "by_month": by_month, "by_tip": by_tip}
