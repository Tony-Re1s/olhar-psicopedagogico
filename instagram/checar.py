"""Confere se o Secret IG_TOKEN funciona, sem publicar nada.

Mostra de quem é o token (deve ser a Página "Michelle Reis Psicopedagoga"), qual conta do Instagram ele
alcança e quantas publicações a conta ainda pode fazer nas próximas 24 horas. Nunca imprime o token.
"""
import json
import os
import urllib.parse
import urllib.request

API = "https://graph.facebook.com/v23.0"
tok = os.environ.get("IG_TOKEN") or ""
uid = os.environ.get("IG_USER_ID") or "17841412464328630"


def get(caminho, **p):
    p["access_token"] = tok
    try:
        with urllib.request.urlopen(f"{API}/{caminho}?{urllib.parse.urlencode(p)}", timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"erro": json.loads(e.read().decode()).get("error", {}).get("message")}


if not tok:
    raise SystemExit("IG_TOKEN não configurado.")
print("começa com EAA:", tok.startswith("EAA"))
print("dono do token:", get("me", fields="id,name"))
print("conta do Instagram:", get(uid, fields="username,media_count"))
print("limite de publicação:", get(f"{uid}/content_publishing_limit", fields="quota_usage,config"))
