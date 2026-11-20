"""Publica no Instagram @olhar_.psicopedagogico o post aprovado do dia, pela API oficial (Graph API da Meta).

Roda no GitHub Actions (.github/workflows/instagram.yml) às segundas, quartas e sextas às 19h.
Não depende de nenhum computador ligado.

Fluxo:
  1. pega na pauta (instagram/pauta.json) o 1º post com status "aprovado" e data <= hoje que ainda não saiu;
  2. gera as artes (estudio.py) e converte para JPEG, o único formato que a API aceita;
  3. sobe as mídias para o branch `instagram-midia` e usa o link do jsDelivr (espelho público do GitHub);
  4. cria o container na API (imagem ou carrossel), espera processar, publica e depois publica o story;
  5. registra em `estado.json`, no mesmo branch, para nunca publicar o mesmo post duas vezes;
  6. avisa no Telegram que o post saiu, com o link.

Reels: a Meta recusa vídeo pela API. Por isso o vídeo e a legenda vão pelo Telegram para alguém postar
pelo celular, e no feed sai o próximo post aprovado.

Secrets do repositório:
  IG_TOKEN         token da Página (começa com EAA e não expira), gerado a partir do token de longa duração do Tony
  IG_USER_ID       id da conta do Instagram (17841412464328630)
  TELEGRAM_TOKEN   token do bot @pedagoga_post_bot
  TELEGRAM_CHATS   ids do Telegram do Tony e da Michelle, separados por vírgula

Opções: --seco (gera e mostra o que faria, sem subir nem publicar); --id 003 (publica um post específico).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

D = Path(__file__).resolve().parent
RAIZ = D.parent
sys.path.insert(0, str(D))
import estudio  # noqa: E402
import telegram  # noqa: E402

API = "https://graph.facebook.com/v23.0"
IG_USER_ID = os.environ.get("IG_USER_ID") or "17841412464328630"     # @olhar_.psicopedagogico
REPO = os.environ.get("GITHUB_REPOSITORY", "Tony-Re1s/olhar-psicopedagogico")
BRANCH = "instagram-midia"
MIDIA = RAIZ / "_midia"          # worktree do branch de mídias (criado pelo workflow)
TZ = ZoneInfo("America/Sao_Paulo")
HOJE = datetime.now(TZ).date()


class IGErro(Exception):
    pass


# ---------------------------------------------------------------- HTTP
def _req(metodo: str, url: str, dados: dict | None = None) -> dict:
    corpo = urllib.parse.urlencode(dados).encode() if dados is not None else None
    req = urllib.request.Request(url, data=corpo, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            bruto = e.read().decode()
            print(f"  resposta da Meta ({e.code}): {bruto[:800]}")
            err = json.loads(bruto).get("error", {})
            msg = err.get("message") or str(e)
            extra = [f"{k}={err[k]}" for k in ("code", "error_subcode", "error_user_title", "error_user_msg")
                     if err.get(k)]
            if extra:
                msg += " [" + "; ".join(str(x) for x in extra) + "]"
        except Exception:  # noqa: BLE001
            msg = str(e)
        raise IGErro(f"{metodo} {url.split('?')[0].replace(API, '')}: {msg}") from e


def token() -> str:
    tok = os.environ.get("IG_TOKEN") or ""
    if not tok:
        raise IGErro("Sem token do Instagram (Secret IG_TOKEN).")
    return tok


# ---------------------------------------------------------------- API de publicação
def _criar(tok: str, **campos) -> str:
    return _req("POST", f"{API}/{IG_USER_ID}/media", dict(campos, access_token=tok))["id"]


def _esperar(cid: str, tok: str, limite=600):
    t0 = time.time()
    while time.time() - t0 < limite:
        st = _req("GET", f"{API}/{cid}?fields=status_code,status&access_token={tok}")
        if st.get("status_code") == "FINISHED":
            return
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise IGErro(f"processamento da mídia falhou: {st.get('status')}")
        time.sleep(6)
    raise IGErro("a mídia demorou demais para processar")


def _ja_publicado(tok: str, cid: str) -> str | None:
    """Depois de um erro no media_publish o post às vezes sai mesmo assim. Devolve o id se saiu."""
    try:
        if _req("GET", f"{API}/{cid}?fields=status_code&access_token={tok}").get("status_code") == "PUBLISHED":
            recentes = _req("GET", f"{API}/{IG_USER_ID}/media?fields=id&limit=1&access_token={tok}").get("data", [])
            return recentes[0]["id"] if recentes else cid
    except IGErro:
        pass
    return None


def _publicar(tok: str, cid: str, tentativas=4) -> str:
    """Publica o container. Erro genérico da Meta costuma ser passageiro: espera, confere se saiu
    mesmo assim (nunca duplica) e só então tenta de novo."""
    _esperar(cid, tok)
    for n in range(1, tentativas + 1):
        try:
            return _req("POST", f"{API}/{IG_USER_ID}/media_publish", {"creation_id": cid, "access_token": tok})["id"]
        except IGErro as e:
            print(f"aviso: publicação falhou (tentativa {n}/{tentativas}): {e}")
            time.sleep(40 * n)
            pid = _ja_publicado(tok, cid)
            if pid:
                print("o post saiu mesmo com o erro; não vou publicar de novo")
                return pid
            if n == tentativas:
                raise


def publicar(urls: dict, legenda: str, tok: str) -> dict:
    if len(urls["imagens"]) == 1:
        cid = _criar(tok, image_url=urls["imagens"][0], caption=legenda)
    else:
        filhos = [_criar(tok, image_url=u, is_carousel_item="true") for u in urls["imagens"]]
        for f in filhos:
            _esperar(f, tok)
        cid = _criar(tok, media_type="CAROUSEL", children=",".join(filhos), caption=legenda)
    mid = _publicar(tok, cid)
    link = _req("GET", f"{API}/{mid}?fields=permalink&access_token={tok}").get("permalink")
    story = None
    if urls.get("story"):
        try:
            story = _publicar(tok, _criar(tok, media_type="STORIES", image_url=urls["story"]))
        except IGErro as e:        # o post do feed já saiu; o story é bônus
            print("aviso: story não publicado:", e)
    return {"media_id": mid, "link": link, "story_id": story}


# ---------------------------------------------------------------- mídias públicas (branch instagram-midia)
def _jpeg(png: Path) -> Path:
    from PIL import Image
    jpg = png.with_suffix(".jpg")
    Image.open(png).convert("RGB").save(jpg, quality=92, optimize=True)
    return jpg


def subir_midias(post: dict, pasta: Path) -> dict:
    """Copia para o worktree do branch de mídias, faz commit/push e devolve os links (fixos no commit)."""
    destino = MIDIA / "posts" / post["id"]
    destino.mkdir(parents=True, exist_ok=True)
    nomes = {"imagens": []}
    for f in sorted(pasta.iterdir()):
        if f.suffix != ".png":
            continue
        j = _jpeg(f)
        if f.stem == "story":
            (destino / "story.jpg").write_bytes(j.read_bytes())
            nomes["story"] = "story.jpg"
        else:
            (destino / j.name).write_bytes(j.read_bytes())
            nomes["imagens"].append(j.name)
    sha = _git_commit(f"mídias do post {post['id']}")
    base = f"https://cdn.jsdelivr.net/gh/{REPO}@{sha}/posts/{post['id']}/"
    urls = {"imagens": [base + n for n in nomes["imagens"]]}
    if nomes.get("story"):
        urls["story"] = base + nomes["story"]
    for u in urls["imagens"] + [urls.get("story")]:   # espera o link responder antes de chamar a Meta
        if not u:
            continue
        for _ in range(20):
            try:
                with urllib.request.urlopen(urllib.request.Request(u, method="HEAD"), timeout=20) as r:
                    if r.status == 200:
                        break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3)
    return urls


def _git(*args) -> str:
    return subprocess.run(["git", "-C", str(MIDIA), *args], check=True, capture_output=True, text=True).stdout.strip()


def _git_commit(msg: str) -> str:
    _git("add", "-A")
    if _git("status", "--porcelain"):
        _git("-c", "user.name=Olhar Bot", "-c", "user.email=bot@users.noreply.github.com", "commit", "-m", msg)
        _git("push", "origin", f"HEAD:{BRANCH}")
    return _git("rev-parse", "HEAD")


def estado() -> dict:
    arq = MIDIA / "estado.json"
    return json.loads(arq.read_text()) if arq.exists() else {"publicados": {}}


def salvar_estado(e: dict, msg: str):
    (MIDIA / "estado.json").write_text(json.dumps(e, ensure_ascii=False, indent=1))
    _git_commit(msg)


# ---------------------------------------------------------------- principal
def escolher(pauta: list[dict], feitos: dict, forcado: str | None, sem_reels=False) -> dict | None:
    if forcado:
        return next(p for p in pauta if p["id"] == forcado)
    for p in sorted(pauta, key=lambda x: (x.get("data") or "", x["id"])):
        if p["id"] in feitos or p.get("status") != "aprovado":
            continue
        if p.get("hora"):      # horário escolhido no Telegram: o bot dispara este post na hora certa (--id)
            continue
        if sem_reels and p["formato"] == "reels":
            continue
        if not p.get("data") or datetime.fromisoformat(p["data"]).date() <= HOJE:
            return p
    return None


def main():
    seco = "--seco" in sys.argv
    forcado = sys.argv[sys.argv.index("--id") + 1] if "--id" in sys.argv else None
    agora = datetime.now(TZ)
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not 18 <= agora.hour < 23:
        print(f"Agendamento do GitHub chegou atrasado ({agora:%H:%M}); fora da janela 18h–23h, não publico.")
        return
    if telegram.config().get("pausado") and not forcado:
        print("Publicação pausada pelo Telegram (/pausar).")
        return
    e = estado() if MIDIA.exists() else {"publicados": {}}
    if forcado and forcado in {**e["publicados"], **e.get("manuais", {})}:
        print(f"O post {forcado} já foi publicado; não publico de novo.")
        return
    if [k for k, v in e["publicados"].items() if v.get("data") == HOJE.isoformat() and not v.get("avulso")] and not forcado:
        print("Já saiu post hoje.")
        return
    feitos = {**e["publicados"], **e.get("manuais", {})}
    post = escolher(estudio.carregar(), feitos, forcado)
    if not post:
        print("Nada aprovado para hoje.")
        return
    print("post:", post["id"], post["formato"], "—", post["tema"])
    pasta = estudio.gerar(post)
    leg = estudio.legenda(post)
    if seco:
        print(leg)
        print(sorted(f.name for f in pasta.iterdir()))
        return
    if post["formato"] == "reels":
        saiu = telegram.mandar_kit(post, pasta, leg)
        if not saiu:
            raise RuntimeError(f"Reels {post['id']}: o vídeo não saiu pelo Telegram")
        e.setdefault("manuais", {})[post["id"]] = dict(data=HOJE.isoformat(), tema=post["tema"])
        salvar_estado(e, f"kit manual {post['id']}")
        post = escolher(estudio.carregar(), {**feitos, post["id"]: 1}, None, sem_reels=True)
        if not post:
            return
        pasta, leg = estudio.gerar(post), estudio.legenda(post)
    tok = token()
    res = publicar(subir_midias(post, pasta), leg, tok)
    e["publicados"][post["id"]] = dict(res, data=HOJE.isoformat(), tema=post["tema"], avulso=bool(post.get("hora")))
    salvar_estado(e, f"publicado {post['id']}")
    print("PUBLICADO:", res.get("link"))
    telegram.avisar(f"✅ Post publicado: {post['tema']}\n{res.get('link') or ''}")


if __name__ == "__main__":
    try:
        main()
    except (IGErro, RuntimeError) as err:
        print("ERRO:", err)
        try:
            telegram.avisar(f"⚠️ O post de hoje não saiu: {err}"[:900])
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
