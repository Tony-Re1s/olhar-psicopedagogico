"""Bot do Telegram @pedagoga_post_bot: o jeito da Michelle (e do Tony) gerir o Instagram.

O que o bot faz:
  previa   manda as artes e as legendas dos posts em rascunho da semana, com os botões
           "✅ Aprovar a semana" e "🔄 Trocar este post". Os posts passam para "aguardando".
  escutar  fica ligado (até ~5h30 por vez, reinicia sozinho) e responde na hora; é o modo normal.
  ler      lê o que chegou no bot (cliques e mensagens) e atualiza a pauta. Roda de hora em hora.
           /novo (com ANTHROPIC_API_KEY) cria a arte na hora e manda a sugestão; ✅ escolhe dia e horário
           ✅ Aprovar a semana    os posts aguardando viram "aprovado" e saem sozinhos às 19h
           🔄 Trocar / /mudar     o bot pergunta o que mudar (texto ou áudio); vira pedido "troca" em pedidos.json
           /novo                  pede um post novo (texto ou áudio); vira pedido "novo" em pedidos.json
           /status                mostra os próximos posts
           /pausar /retomar       para e volta a publicação
           texto/áudio solto      o bot pergunta: criar post novo, mudar um post ou era só recado
                                  (recado não é gravado — só repassado aos outros chats, porque o repositório é público)
  Áudios são transcritos no próprio GitHub Actions com faster-whisper (modelo "small", português), sem chave de API.
  ids      mostra no log os ids de quem mandou mensagem ao bot (para configurar TELEGRAM_CHATS)

Os pedidos ("novo" e "troca") são lidos pelo Claude na tarefa agendada, que cria ou refaz o post e põe em
"rascunho". O push dele manda a prévia de novo sozinho.

Secrets: TELEGRAM_TOKEN (token do bot) e TELEGRAM_CHATS (ids autorizados, separados por vírgula).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.parse
import urllib.error
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
    return f"{DIAS[d.weekday()]} {d:%d/%m} às {int((p.get('hora') or '19')[:2])}h"


# ---------------------------------------------------------------- API do Telegram
def _token() -> str:
    return os.environ.get("TELEGRAM_TOKEN") or ""


def chats() -> list[str]:
    return [c.strip() for c in (os.environ.get("TELEGRAM_CHATS") or "").split(",") if c.strip()]


def api(metodo: str, **params) -> dict:
    dados = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                    for k, v in params.items() if v is not None}).encode()
    espera = 60 + int(params.get("timeout") or 0)
    with urllib.request.urlopen(f"https://api.telegram.org/bot{_token()}/{metodo}", dados, timeout=espera) as r:
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
         "No sábado mando a prévia da semana para você aprovar. Você também pode, a qualquer hora:\n\n"
         "➕ /novo — criar um post novo: me conta o tema ou o conteúdo, por texto ou ÁUDIO\n"
         "✏️ /mudar — mudar o conteúdo de um post que ainda não saiu (texto ou áudio)\n"
         "📋 /status — ver os próximos posts\n"
         "⏸ /pausar e ▶️ /retomar — parar e voltar a publicar\n\n"
         "Se mandar um texto ou áudio solto, eu pergunto o que fazer com ele.\n"
         "Quando você pede um post novo, a arte chega aqui para você ver. Se gostar, toque em ✅ e escolha o dia e o horário.")

PRAZO = "Em até 1 hora te mando a prévia aqui para aprovar. 💜"


_MODELO = None


def _transcrever(midia: dict) -> str:
    """Baixa o áudio do Telegram e transcreve em português com faster-whisper (roda no próprio GitHub Actions,
    sem chave de API). O modelo fica em cache entre as execuções."""
    import subprocess
    import tempfile
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "faster-whisper"], check=True)
        from faster_whisper import WhisperModel
    caminho = api("getFile", file_id=midia["file_id"])["result"]["file_path"]
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{_token()}/{caminho}", timeout=120) as r:
        dados = r.read()
    with tempfile.NamedTemporaryFile(suffix=Path(caminho).suffix or ".ogg", delete=False) as f:
        f.write(dados)
    # Decodifica com o ffmpeg do sistema (16 kHz, mono): o decodificador interno do faster-whisper (PyAV)
    # quebra com versões novas da biblioteca.
    import numpy as np
    bruto = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", f.name, "-f", "s16le",
                            "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(bruto, np.int16).astype(np.float32) / 32768.0
    global _MODELO
    if _MODELO is None:
        _MODELO = WhisperModel(os.environ.get("WHISPER_MODELO", "small"), device="cpu", compute_type="int8")
    trechos, _ = _MODELO.transcribe(audio, language="pt", vad_filter=True)
    return " ".join(t.text.strip() for t in trechos).strip()


def _abertos(pauta: list[dict]) -> list[dict]:
    """Posts que ainda podem ser mudados (não publicados, data de hoje em diante)."""
    hoje = datetime.now(TZ).date()
    return [p for p in sorted(pauta, key=lambda x: (x.get("data") or "", x["id"]))
            if p.get("status") != "publicado" and (not p.get("data") or date.fromisoformat(p["data"]) >= hoje)]


def _botoes_posts(pauta: list[dict], prefixo: str) -> list[list[dict]]:
    return [[{"text": f"{p['id']} · {_quando(p).split(' às')[0]} · {p['tema'][:40]}", "callback_data": f"{prefixo}:{p['id']}"}]
            for p in _abertos(pauta)[:8]]


def _status(pauta: list[dict], cfg: dict) -> str:
    nomes = {"rascunho": "em preparação", "aguardando": "esperando aprovação", "aprovado": "aprovado ✅",
             "trocar": "em ajuste 🔄", "publicado": "publicado", "sugestao": "sugestão: falta você aprovar e escolher o dia"}
    linhas = [f"• {_quando(p)}: {p['tema']} ({nomes.get(p.get('status'), p.get('status'))})" for p in _abertos(pauta)[:6]]
    topo = "⏸ Publicação PAUSADA (use /retomar)\n\n" if cfg.get("pausado") else ""
    if cfg.get("teste"):
        topo += "🧪 Modo de teste: pode aprovar, mudar e criar à vontade — nada vai para o Instagram até o Tony liberar.\n\n"
    return topo + ("Próximos posts:\n" + "\n".join(linhas) if linhas else "Nenhum post agendado ainda.")


def _mandar_sugestao(p: dict, titulo: str):
    """Manda a arte de um post recém-criado, com os botões para aprovar e programar, ajustar ou descartar."""
    import estudio
    pasta = estudio.gerar(p)
    imagens = sorted(f for f in pasta.iterdir() if f.suffix == ".png" and f.stem != "story")
    if (pasta / "story.png").exists():
        imagens.append(pasta / "story.png")
    p["enviada"] = True
    for c in chats():
        enviar(titulo, c)
        _fotos(c, imagens)
        enviar("Legenda:\n\n" + estudio.legenda(p), c, [
            [{"text": "✅ Gostei — escolher dia e horário", "callback_data": f"prog:{p['id']}"}],
            [{"text": "✏️ Ajustar", "callback_data": f"trocar:{p['id']}"},
             {"text": "🗑 Descartar", "callback_data": f"descartar:{p['id']}"}]])


def _botoes_dias(pid: str) -> list[list[dict]]:
    hoje = datetime.now(TZ)
    linhas, linha = [], []
    for n in range(0, 14):
        d = date.fromordinal(hoje.date().toordinal() + n)
        if n == 0 and hoje.hour >= 21:
            continue
        rot = "Hoje" if n == 0 else ("Amanhã" if n == 1 else f"{DIAS[d.weekday()][:3]} {d:%d/%m}")
        linha.append({"text": rot, "callback_data": f"dia:{pid}:{d:%Y%m%d}"})
        if len(linha) == 3:
            linhas.append(linha)
            linha = []
    return linhas + ([linha] if linha else [])


HORAS = [8, 10, 12, 15, 18, 19, 20, 21]


def _botoes_horas(pid: str, dia: str) -> list[list[dict]]:
    agora = datetime.now(TZ)
    d = datetime.strptime(dia, "%Y%m%d").date()
    hs = [h for h in HORAS if d > agora.date() or h > agora.hour]
    bts = [{"text": f"{h}h", "callback_data": f"hora:{pid}:{dia}:{h:02d}"} for h in hs]
    return [bts[i:i + 4] for i in range(0, len(bts), 4)]


def ler(espera: int = 0) -> bool:
    if not (_token() and chats()):
        # sem a lista de chats não lê nada, para não "consumir" as mensagens antes de rodar `ids`
        print("TELEGRAM_TOKEN ou TELEGRAM_CHATS não configurado.")
        return False
    autorizados = set(chats())
    cfg, pauta, pedidos = config(), _ler(PAUTA, []), _ler(PEDIDOS, [])
    por_id = {p["id"]: p for p in pauta}
    esperando = cfg.setdefault("esperando", {})      # chave do chat -> "novo" ou id do post a mudar
    soltos = cfg.setdefault("soltos", {})            # chave do chat -> texto solto aguardando decisão
    mudou = False
    if cfg.get("menu") != 2:      # menu de comandos que aparece ao digitar "/" no Telegram
        api("setMyCommands", commands=[
            {"command": "novo", "description": "Criar um post novo (texto ou áudio)"},
            {"command": "mudar", "description": "Mudar o conteúdo de um post"},
            {"command": "status", "description": "Ver os próximos posts"},
            {"command": "pausar", "description": "Parar de publicar"},
            {"command": "retomar", "description": "Voltar a publicar"},
            {"command": "ajuda", "description": "Como eu funciono"}])
        cfg["menu"] = 2
        mudou = True
    upd = api("getUpdates", offset=cfg.get("offset", 0) + 1, timeout=espera, allowed_updates=["message", "callback_query"])

    def pedir(tipo: str, texto: str, quem: str, agora: str, post: str | None = None):
        item = {"tipo": tipo, "texto": texto, "de": quem, "em": agora, "feito": False}
        if post:
            item["post"] = post
            if post in por_id:
                por_id[post]["status"] = "trocar"
        pedidos.append(item)

    def novo(texto: str, quem: str, agora: str, chat: str):
        """Com a chave da API do Claude, cria a arte na hora; sem ela, vira pedido para a tarefa agendada."""
        import criador
        if criador.disponivel():
            enviar("🎨 Criando a arte agora, leva 1 ou 2 minutinhos…", chat)
            try:
                p = criador.criar(texto, pauta)
                pauta.append(p)
                por_id[p["id"]] = p
                _mandar_sugestao(p, f"✨ Sugestão de post {p['id']} ({quem} pediu): {p['tema']}\n"
                                    "Se gostar, toque em ✅ e escolha o dia e o horário.")
                return
            except Exception as err:  # noqa: BLE001
                print("aviso: não consegui criar na hora:", type(err).__name__, err)
        pedir("novo", texto, quem, agora)
        enviar("➕ Anotado, vou criar um post novo com isso. " + PRAZO, chat)

    def refazer(pid: str, texto: str, quem: str, agora: str, chat: str):
        import criador
        if criador.disponivel() and pid in por_id:
            enviar(f"🎨 Refazendo o post {pid} agora, leva 1 ou 2 minutinhos…", chat)
            try:
                p = criador.criar(texto, pauta, base=por_id[pid])
                pauta[pauta.index(por_id[pid])] = p
                por_id[pid] = p
                _mandar_sugestao(p, f"✏️ Post {pid} refeito ({quem} pediu): {p['tema']}\n"
                                    "Ele só volta para a programação quando você tocar em ✅ e escolher o dia e o horário.")
                return
            except Exception as err:  # noqa: BLE001
                print("aviso: não consegui refazer na hora:", type(err).__name__, err)
        pedir("troca", texto, quem, agora, pid)
        enviar(f"✏️ Anotado! Vou refazer o post {pid}. " + PRAZO, chat)

    for u in upd.get("result", []):
        cfg["offset"] = u["update_id"]
        mudou = True
        cb = u.get("callback_query")
        msg = u.get("message") or (cb or {}).get("message") or {}
        chat = str(msg.get("chat", {}).get("id", ""))
        k = _chave(chat)
        quem = (cb or msg).get("from", {}).get("first_name", "")
        if chat not in autorizados:
            print(f"mensagem de chat não autorizado: ...{chat[-3:]}")
            continue
        agora = datetime.now(TZ).isoformat(timespec="minutes")

        # ------------------------------------------------ botões
        if cb:
            dado = cb.get("data", "")
            try:
                api("answerCallbackQuery", callback_query_id=cb["id"])
            except urllib.error.HTTPError:
                pass  # clique antigo: o Telegram recusa a resposta, mas o clique vale
            acao, _, pid = dado.partition(":")
            if acao == "aprovar":
                ok = [p for p in pauta if p.get("status") == "aguardando"]
                for p in ok:
                    p["status"] = "aprovado"
                if ok:
                    enviar(f"✅ {quem} aprovou {len(ok)} post(s)" +
                           (" (🧪 modo de teste: nada vai para o Instagram até o Tony liberar):\n" if cfg.get("teste")
                            else ". Vão sair sozinhos:\n") +
                           "\n".join(f"• {_quando(p)}: {p['tema']}" for p in sorted(ok, key=lambda x: x.get('data') or '')))
                else:
                    enviar("Não há posts esperando aprovação agora. 😊", chat)
            elif acao == "trocar" and pid in por_id:
                esperando[k] = pid
                enviar(f"Certo! O que você quer mudar no post {pid} ({por_id[pid]['tema']})?\n"
                       "Pode escrever ou mandar um ÁUDIO: o tema, o texto, uma frase, o que quiser. 🎙️", chat)
            elif acao == "livre" and pid == "novo" and k in soltos:
                novo(soltos.pop(k), quem, agora, chat)
            elif acao == "livre" and pid == "mudar" and k in soltos:
                bts = _botoes_posts(pauta, "aplicar")
                enviar("Em qual post eu aplico isso?" if bts else "Não há posts abertos para mudar agora.", chat, bts or None)
            elif acao == "aplicar" and pid in por_id and k in soltos:
                refazer(pid, soltos.pop(k), quem, agora, chat)
            elif acao == "prog" and pid in por_id:
                enviar(f"🗓 Em que dia sai o post {pid} ({por_id[pid]['tema']})?", chat, _botoes_dias(pid))
            elif acao == "dia":
                p_id, _, dia = pid.partition(":")
                if p_id in por_id:
                    bts = _botoes_horas(p_id, dia)
                    enviar("⏰ Em que horário?" if bts else "Esse dia já passou dos horários. Escolha outro dia.",
                           chat, bts or _botoes_dias(p_id))
            elif acao == "hora":
                p_id, dia, h = (pid.split(":") + ["", ""])[:3]
                if p_id in por_id and dia and h:
                    d = datetime.strptime(dia, "%Y%m%d").date()
                    p = por_id[p_id]
                    p.update(data=d.isoformat(), hora=f"{h}:00", status="aprovado",
                             semana=date.fromordinal(d.toordinal() - d.weekday()).isoformat())
                    cfg.setdefault("disparados", {}).pop(p_id, None)
                    enviar(f"✅ {quem} programou o post {p_id} ({p['tema']}) para {_quando(p)}. Sai sozinho. 💜")
            elif acao == "descartar" and pid in por_id:
                if por_id[pid].get("status") == "sugestao":
                    pauta.remove(por_id.pop(pid))
                    enviar(f"🗑 Post {pid} descartado.", chat)
                else:
                    enviar("Esse post já está programado. Para mudar, use /mudar.", chat)
            elif acao == "livre" and pid == "recado" and k in soltos:
                texto = soltos.pop(k)
                for c in chats():
                    if c != chat:
                        enviar(f"💬 Recado de {quem} no bot:\n\n{texto}", c)
                enviar("Recebido! Passei seu recado. 💜", chat)
            elif acao == "postei":
                cfg.setdefault("reels_postados", {})[pid] = agora
                enviar("Obrigado! Reels marcado como postado 💜", chat)
            continue

        # ------------------------------------------------ mensagens (texto ou áudio)
        texto = (msg.get("text") or msg.get("caption") or "").strip()
        midia = msg.get("voice") or msg.get("audio") or msg.get("video_note")
        if midia and not texto:
            try:
                api("sendChatAction", chat_id=chat, action="typing")
                texto = _transcrever(midia)
                enviar(f"🎙️ Entendi assim:\n\n«{texto}»", chat)
            except Exception as err:  # noqa: BLE001
                print("aviso: não consegui transcrever o áudio:", err)
                enviar("Não consegui entender esse áudio 😕 Pode mandar de novo ou escrever?", chat)
                continue
        if not texto:
            continue
        palavras = texto.split()
        cmd = palavras[0].split("@")[0].lower() if texto.startswith("/") else ""
        resto = texto[len(palavras[0]):].strip() if cmd else texto
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
        elif cmd in ("/novo", "/ideia"):
            if resto:
                novo(resto, quem, agora, chat)
            else:
                esperando[k] = "novo"
                enviar("➕ Vamos criar! Me conta o tema ou o conteúdo do post, por texto ou por áudio. 🎙️", chat)
        elif cmd in ("/mudar", "/trocar"):
            bts = _botoes_posts(pauta, "trocar")
            enviar("Qual post você quer mudar?" if bts else "Não há posts abertos para mudar agora.", chat, bts or None)
        elif cmd:
            enviar("Não conheço esse comando. Mande /ajuda para ver o que eu sei fazer.", chat)
        elif k in esperando:
            alvo = esperando.pop(k)
            if alvo == "novo":
                novo(texto, quem, agora, chat)
            else:
                refazer(alvo, texto, quem, agora, chat)
        else:
            soltos[k] = texto
            enviar("O que eu faço com isso?", chat, [
                [{"text": "➕ Criar um post novo", "callback_data": "livre:novo"}],
                [{"text": "✏️ Mudar um post que já existe", "callback_data": "livre:mudar"}],
                [{"text": "💬 Era só um recado", "callback_data": "livre:recado"}]])
    if mudou:
        _gravar(CONFIG, cfg)
        _gravar(PAUTA, pauta)
        _gravar(PEDIDOS, pedidos)
        print(f"{len(upd.get('result', []))} atualização(ões) processada(s)")
    elif not espera:
        print("Nada novo no Telegram.")
    return mudou


def ids():
    upd = api("getUpdates", timeout=0)
    vistos = {}
    for u in upd.get("result", []):
        m = u.get("message") or (u.get("callback_query") or {}).get("message") or {}
        c = m.get("chat", {})
        if c.get("id"):
            vistos[c["id"]] = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x)
    # o log do Actions é público: mostra só o final do id e a inicial do nome.
    # O id completo vai por mensagem privada para o próprio chat.
    for k, v in vistos.items():
        print(f"chat ...{str(k)[-3:]}: {v[:1]}.")
        try:
            api("sendMessage", chat_id=k, text=f"Seu id do Telegram para o Secret TELEGRAM_CHATS é: {k}")
        except Exception as err:  # noqa: BLE001
            print("  aviso: não consegui mandar o id por mensagem:", err)
    if not vistos:
        print("Ninguém mandou mensagem ao bot ainda (mande /start para ele e rode de novo).")


def _git(*args: str) -> int:
    import subprocess
    return subprocess.run(["git", *args], cwd=D.parent).returncode


def disparar() -> bool:
    """Posts programados com horário ("hora"): quando chega a hora, dispara a publicação daquele post."""
    import subprocess
    cfg = config()
    if cfg.get("pausado"):
        return False
    agora = datetime.now(TZ)
    feitos = cfg.setdefault("disparados", {})
    mudou = False
    for p in _ler(PAUTA, []):
        if p.get("status") != "aprovado" or not p.get("hora") or not p.get("data") or p["id"] in feitos:
            continue
        quando = datetime.fromisoformat(f"{p['data']}T{p['hora']}").replace(tzinfo=TZ)
        if agora >= quando:
            r = subprocess.run(["gh", "workflow", "run", "instagram.yml", "--ref", "main",
                                "-R", os.environ.get("GITHUB_REPOSITORY", "Tony-Re1s/olhar-psicopedagogico"),
                                "-f", f"id={p['id']}"])
            if r.returncode == 0:
                print("publicação disparada:", p["id"])
                feitos[p["id"]] = agora.isoformat(timespec="minutes")
                mudou = True
    if mudou:
        _gravar(CONFIG, cfg)
    return mudou


def sugestoes_pendentes() -> bool:
    """Posts em "sugestao" criados pela tarefa agendada (caminho sem chave da API): manda a arte com os botões."""
    pauta = _ler(PAUTA, [])
    pend = [p for p in pauta if p.get("status") == "sugestao" and not p.get("enviada")]
    for p in pend:
        _mandar_sugestao(p, f"✨ Sugestão de post {p['id']}: {p['tema']}\n"
                            "Se gostar, toque em ✅ e escolha o dia e o horário.")
    if pend:
        _gravar(PAUTA, pauta)
    return bool(pend)


def escutar():
    """Fica ligado respondendo o Telegram na hora (long polling), por até ESCUTA_MIN minutos.
    Grava e manda para o GitHub a cada mudança. O workflow se reinicia sozinho no fim."""
    import time
    fim = time.time() + 60 * int(os.environ.get("ESCUTA_MIN", "330"))
    print("Bot ligado, respondendo na hora.")
    while time.time() < fim:
        _git("pull", "--rebase", "-q", "origin", "main")
        try:
            mudou = ler(espera=50)
            mudou = disparar() or mudou
            mudou = sugestoes_pendentes() or mudou
        except urllib.error.HTTPError as err:
            print("aviso: Telegram respondeu", err.code)
            time.sleep(30)
            continue
        except Exception as err:  # noqa: BLE001  (rede instável: tenta de novo)
            print("aviso:", type(err).__name__, err)
            time.sleep(10)
            continue
        if mudou:
            _git("add", "instagram/pauta.json", "instagram/config.json", "instagram/pedidos.json")
            if _git("diff", "--cached", "--quiet"):
                _git("-c", "user.name=Olhar Bot", "-c", "user.email=bot@users.noreply.github.com",
                     "commit", "-q", "-m", "bot: ler pelo Telegram")
                for _ in range(3):
                    if _git("pull", "--rebase", "-q", "origin", "main") == 0 and _git("push", "-q", "origin", "HEAD:main") == 0:
                        break
                    time.sleep(5)
    print("Fim do turno do bot; o próximo começa em seguida.")


if __name__ == "__main__":
    sys.path.insert(0, str(D))
    acao = sys.argv[1] if len(sys.argv) > 1 else "ler"
    {"previa": previa, "ler": ler, "ids": ids, "escutar": escutar}[acao]()
