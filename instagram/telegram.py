"""Bot do Telegram @pedagoga_post_bot: o jeito da Michelle (e do Tony) gerir o Instagram.

O que o bot faz:
  previa   manda as artes e as legendas dos posts em rascunho da semana, com os botões
           "✅ Aprovar a semana" e "🔄 Trocar este post". Os posts passam para "aguardando".
  ler      lê o que chegou no bot (cliques e mensagens) e atualiza a pauta. Roda de hora em hora.
           ✅ Aprovar a semana    os posts aguardando viram "aprovado" e saem sozinhos às 19h
           🔄 Trocar este post    o bot pergunta o que mudar; a resposta vai para pedidos.json
           /status                mostra os próximos posts
           /pausar /retomar       para e volta a publicação
           /ideia <texto>         guarda uma ideia de post para as próximas pautas
           qualquer outro texto   é repassado aos outros chats, sem gravar nada (o repositório é público)
  ids      mostra no log os ids de quem mandou mensagem ao bot (para configurar TELEGRAM_CHATS)

Os pedidos de troca e as ideias são lidos pelo Claude na tarefa agendada, que refaz o post e devolve
para "rascunho". A prévia sai de novo sozinha.

Secrets: TELEGRAM_TOKEN (token do bot) e TELEGRAM_CHATS (ids autorizados, separados por vírgula).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

D = Path(__file__).resolve().parent
CONFIG = D / "config.json"
PEDIDOS = D / "pedidos.json"
PAUTA = D / "pauta.json"
TZ = ZoneInfo("America/Sao_Paulo")
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


# ---------------------------------------------------------------- arquivos
def _ler(arq: Path, padrao):
    return json.loads(arq.read_text()) if arq.exists() else padrao


def _gravar(arq: Path, dados):
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n")


def _chave(chat: str) -> str:
    """O repositório é público: no config.json guardo só um código derivado do chat, nunca o id do Telegram."""
    return hashlib.sha256(f"olhar:{chat}".encode()).hexdigest()[:12]


def config() -> dict:
    return _ler(CONFIG, {})


def _quando(p: dict) -> str:
    if not p.get("data"):
        return "sem data"
    d = date.fromisoformat(p["data"])
    return f"{DIAS[d.weekday()]} {d:%d/%m} às 19h"


# ---------------------------------------------------------------- API do Telegram
def _token() -> str:
    return os.environ.get("TELEGRAM_TOKEN") or ""


def chats() -> list[str]:
    return [c.strip() for c in (os.environ.get("TELEGRAM_CHATS") or "").split(",") if c.strip()]


def api(metodo: str, **params) -> dict:
    dados = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                    for k, v in params.items() if v is not None}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{_token()}/{metodo}", dados, timeout=60) as r:
        return json.loads(r.read().decode())


def _multipart(metodo: str, campos: dict, arquivos: dict[str, tuple[str, bytes, str]]) -> dict:
    b = uuid.uuid4().hex
    partes = []
    for nome, valor in campos.items():
        valor = json.dumps(valor) if isinstance(valor, (dict, list)) else str(valor)
        partes.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{nome}\"\r\n\r\n{valor}\r\n".encode())
    for nome, (arq, conteudo, tipo) in arquivos.items():
        partes.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{nome}\"; filename=\"{arq}\"\r\n"
                      f"Content-Type: {tipo}\r\n\r\n".encode() + conteudo + b"\r\n")
    partes.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{_token()}/{metodo}", data=b"".join(partes),
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def enviar(texto: str, chat: str | None = None, botoes: list[list[dict]] | None = None):
    for c in ([chat] if chat else chats()):
        api("sendMessage", chat_id=c, text=texto[:4000],
            reply_markup={"inline_keyboard": botoes} if botoes else None)


def avisar(texto: str):
    """Aviso simples para todos os chats autorizados (não falha se o bot não estiver configurado)."""
    if not (_token() and chats()):
        print("(sem Telegram configurado) " + texto)
        return
    try:
        enviar(texto)
    except Exception as err:  # noqa: BLE001
        print("aviso: Telegram não saiu:", err)


def _fotos(chat: str, imagens: list[Path]):
    for ini in range(0, len(imagens), 10):        # o Telegram aceita no máximo 10 fotos por álbum
        lote = imagens[ini:ini + 10]
        if len(lote) == 1:
            _multipart("sendPhoto", {"chat_id": chat}, {"photo": (lote[0].name, lote[0].read_bytes(), "image/png")})
            continue
        media = [{"type": "photo", "media": f"attach://f{k}"} for k in range(len(lote))]
        _multipart("sendMediaGroup", {"chat_id": chat, "media": media},
                   {f"f{k}": (f.name, f.read_bytes(), "image/png") for k, f in enumerate(lote)})


def mandar_kit(post: dict, pasta: Path, leg: str) -> list[str]:
    """Reels: manda o vídeo pronto e a legenda para postar pelo celular."""
    if not (_token() and chats()):
        return []
    video = (pasta / "reels.mp4").read_bytes()
    passos = (f"🎬 Reels de hoje: {post['tema']}\n\nA Meta ainda não aceita vídeo pela API, então este vai à mão:\n"
              "1) Salve o vídeo  2) Instagram → + → Reel  3) Cole a legenda da próxima mensagem e publique.\n"
              "Depois toque em ✔️ Postei.")
    for c in chats():
        _multipart("sendVideo", {"chat_id": c, "caption": passos[:1000]}, {"video": ("reels.mp4", video, "video/mp4")})
        enviar(leg, c, [[{"text": "✔️ Postei", "callback_data": f"postei:{post['id']}"}]])
    return ["Telegram"]


# ---------------------------------------------------------------- prévia da semana
def previa():
    import estudio
    pauta = estudio.carregar()
    novos = [p for p in pauta if p.get("status") == "rascunho"]
    if not novos:
        print("Nenhum post em rascunho para mandar.")
        return
    if not (_token() and chats()):
        raise SystemExit("Falta configurar TELEGRAM_TOKEN e TELEGRAM_CHATS.")
    novos.sort(key=lambda x: (x.get("data") or "", x["id"]))
    enviar(f"💜 Prévia dos próximos posts ({len(novos)}). Confira as artes e as legendas.")
    for p in novos:
        pasta = estudio.gerar(p)
        imagens = sorted(f for f in pasta.iterdir() if f.suffix == ".png" and f.stem != "story")
        for c in chats():
            enviar(f"📌 Post {p['id']}: {p['tema']}\n🗓 {_quando(p)}", c)
            if p["formato"] == "reels":
                _multipart("sendVideo", {"chat_id": c}, {"video": ("reels.mp4", (pasta / "reels.mp4").read_bytes(), "video/mp4")})
            else:
                _fotos(c, imagens + ([pasta / "story.png"] if (pasta / "story.png").exists() else []))
            enviar("Legenda:\n\n" + estudio.legenda(p), c,
                   [[{"text": f"🔄 Trocar o post {p['id']}", "callback_data": f"trocar:{p['id']}"}]])
        p["status"] = "aguardando"
    enviar("Está tudo certo? Se quiser mudar algum post, toque em 🔄 Trocar nele.\n"
           "Se estiver tudo bem, aprove aqui e os posts saem sozinhos às 19h.",
           botoes=[[{"text": "✅ Aprovar a semana", "callback_data": "aprovar"}]])
    _gravar(PAUTA, pauta)


# ---------------------------------------------------------------- leitura das mensagens
AJUDA = ("Oi! Eu cuido dos posts do @olhar_.psicopedagogico 💜\n\n"
         "No sábado mando a prévia da semana para você aprovar.\n"
         "/status — próximos posts\n/pausar — para de publicar\n/retomar — volta a publicar\n"
         "/ideia <texto> — guarda uma ideia de post\n\nQualquer outra mensagem eu repasso para o Tony.")


def _status(pauta: list[dict], cfg: dict) -> str:
    nomes = {"rascunho": "em preparação", "aguardando": "esperando aprovação", "aprovado": "aprovado ✅",
             "trocar": "em ajuste 🔄", "publicado": "publicado"}
    proximos = [p for p in sorted(pauta, key=lambda x: x.get("data") or "")
                if p.get("data") and date.fromisoformat(p["data"]) >= datetime.now(TZ).date()]
    linhas = [f"• {_quando(p)}: {p['tema']} ({nomes.get(p.get('status'), p.get('status'))})" for p in proximos[:6]]
    topo = "⏸ Publicação PAUSADA (use /retomar)\n\n" if cfg.get("pausado") else ""
    return topo + ("Próximos posts:\n" + "\n".join(linhas) if linhas else "Nenhum post agendado ainda.")


def ler():
    if not (_token() and chats()):
        # sem a lista de chats não lê nada, para não "consumir" as mensagens antes de rodar `ids`
        print("TELEGRAM_TOKEN ou TELEGRAM_CHATS não configurado.")
        return
    autorizados = set(chats())
    cfg, pauta, pedidos = config(), _ler(PAUTA, []), _ler(PEDIDOS, [])
    por_id = {p["id"]: p for p in pauta}
    upd = api("getUpdates", offset=cfg.get("offset", 0) + 1, timeout=0, allowed_updates=["message", "callback_query"])
    mudou = False
    for u in upd.get("result", []):
        cfg["offset"] = u["update_id"]
        mudou = True
        cb = u.get("callback_query")
        msg = u.get("message") or (cb or {}).get("message") or {}
        chat = str(msg.get("chat", {}).get("id", ""))
        quem = (cb or msg).get("from", {}).get("first_name", "")
        if chat not in autorizados:
            print(f"mensagem de chat não autorizado: {chat} ({quem})")
            continue
        agora = datetime.now(TZ).isoformat(timespec="minutes")
        if cb:
            dado = cb.get("data", "")
            api("answerCallbackQuery", callback_query_id=cb["id"])
            if dado == "aprovar":
                ok = [p for p in pauta if p.get("status") == "aguardando"]
                for p in ok:
                    p["status"] = "aprovado"
                if ok:
                    enviar(f"✅ {quem} aprovou {len(ok)} post(s). Vão sair sozinhos:\n" +
                           "\n".join(f"• {_quando(p)}: {p['tema']}" for p in sorted(ok, key=lambda x: x.get('data') or '')))
                else:
                    enviar("Não há posts esperando aprovação agora. 😊", chat)
            elif dado.startswith("trocar:"):
                pid = dado.split(":", 1)[1]
                if pid in por_id:
                    por_id[pid]["status"] = "trocar"
                    cfg.setdefault("esperando", {})[_chave(chat)] = pid
                    enviar(f"Certo! O que você quer mudar no post {pid} ({por_id[pid]['tema']})?\n"
                           "Pode escrever do seu jeito: o tema, o texto, uma palavra…", chat)
            elif dado.startswith("postei:"):
                pid = dado.split(":", 1)[1]
                cfg.setdefault("reels_postados", {})[pid] = agora
                enviar("Obrigado! Reels marcado como postado 💜", chat)
            continue
        texto = (msg.get("text") or "").strip()
        if not texto:
            continue
        cmd = texto.split()[0].split("@")[0].lower()
        if cmd in ("/start", "/ajuda", "/help"):
            enviar(AJUDA, chat)
        elif cmd == "/status":
            enviar(_status(pauta, cfg), chat)
        elif cmd == "/pausar":
            cfg["pausado"] = True
            enviar(f"⏸ {quem} pausou a publicação. Nenhum post sai até alguém mandar /retomar.")
        elif cmd == "/retomar":
            cfg["pausado"] = False
            enviar(f"▶️ {quem} retomou a publicação.")
        elif cmd == "/ideia":
            ideia = texto[len(texto.split()[0]):].strip()
            if ideia:
                pedidos.append({"tipo": "ideia", "texto": ideia, "de": quem, "em": agora, "feito": False})
                enviar("💡 Ideia guardada! Vou usar nas próximas pautas.", chat)
            else:
                enviar("Escreva a ideia junto, assim: /ideia como ajudar na alfabetização", chat)
        elif _chave(chat) in cfg.get("esperando", {}):
            pid = cfg["esperando"].pop(_chave(chat))
            pedidos.append({"tipo": "troca", "post": pid, "texto": texto, "de": quem, "em": agora, "feito": False})
            enviar(f"Anotado! Vou refazer o post {pid} e te mando a nova versão para aprovar. 💜", chat)
        else:
            # recado livre NÃO vai para o repositório (é público): só é repassado aos outros chats autorizados
            for c in chats():
                if c != chat:
                    enviar(f"💬 Recado de {quem} no bot:\n\n{texto}", c)
            enviar("Recebido! Passei seu recado para o Tony 💜\n"
                   "(Para pedir mudança num post, use o botão 🔄 Trocar; para ideias, /ideia.)", chat)
    if mudou:
        _gravar(CONFIG, cfg)
        _gravar(PAUTA, pauta)
        _gravar(PEDIDOS, pedidos)
        print(f"{len(upd.get('result', []))} atualização(ões) processada(s)")
    else:
        print("Nada novo no Telegram.")


def ids():
    upd = api("getUpdates", timeout=0)
    vistos = {}
    for u in upd.get("result", []):
        m = u.get("message") or (u.get("callback_query") or {}).get("message") or {}
        c = m.get("chat", {})
        if c.get("id"):
            vistos[c["id"]] = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x)
    for k, v in vistos.items():
        print(f"chat {k}: {v}")
    if not vistos:
        print("Ninguém mandou mensagem ao bot ainda (mande /start para ele e rode de novo).")


if __name__ == "__main__":
    sys.path.insert(0, str(D))
    acao = sys.argv[1] if len(sys.argv) > 1 else "ler"
    {"previa": previa, "ler": ler, "ids": ids}[acao]()
