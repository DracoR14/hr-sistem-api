# Dodati u main.py na GitHubu - PUT endpoint za korisnike
# Zamijeniti postojeci @app.delete("/korisnici/{kid}") sa ovim:

@app.put("/korisnici/{kid}")
def update_korisnik(kid: int, request: Request, user=Depends(get_current_user)):
    if user['uloga'] not in ('superadmin', 'admin'):
        raise HTTPException(403, "Nemate pristup")
    import json
    data = {}
    try:
        data = json.loads(request._body.decode()) if hasattr(request, '_body') else {}
    except:
        pass
    if 'ime' in data:
        db_exec("UPDATE korisnici SET ime=:i WHERE id=:k", {"i": data['ime'], "k": kid})
    if 'uloga' in data and user['uloga'] == 'superadmin':
        db_exec("UPDATE korisnici SET uloga=:u WHERE id=:k", {"u": data['uloga'], "k": kid})
    if 'nova_lozinka' in data and data['nova_lozinka']:
        import bcrypt
        pw = bcrypt.hashpw(data['nova_lozinka'].encode(), bcrypt.gensalt()).decode()
        db_exec("UPDATE korisnici SET password_hash=:p WHERE id=:k", {"p": pw, "k": kid})
    if 'aktivan' in data:
        db_exec("UPDATE korisnici SET aktivan=:a WHERE id=:k", {"a": 1 if data['aktivan'] else 0, "k": kid})
    return {"ok": True}

@app.delete("/korisnici/{kid}")
def del_korisnik(kid: int, request: Request, user=Depends(get_current_user)):
    if user['uloga'] not in ('superadmin', 'admin'):
        raise HTTPException(403, "Nemate pristup")
    db_exec("UPDATE korisnici SET aktivan=0 WHERE id=:k", {"k": kid})
    return {"ok": True}
