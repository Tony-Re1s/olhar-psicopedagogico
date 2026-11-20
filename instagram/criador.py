"""Cria (ou refaz) um post na hora, a partir do pedido da Michelle no Telegram, usando a API do Claude.

Precisa do Secret ANTHROPIC_API_KEY. Sem ele, o bot volta ao caminho antigo (pedido em pedidos.json,
atendido pela tarefa agendada de hora em hora).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
MODELO = os.environ.get("CLAUDE_MODELO", "claude-sonnet-5-5")

REGRAS = """Você escreve os posts do Instagram @olhar_.psicopedagogico, da psicopedagoga Michelle Reis.
Público: PAIS E MÃES de crianças em idade escolar. Objetivo: atrair pacientes. Ela atende com hora marcada
em São Paulo (Zona Leste). Contato: WhatsApp (link na bio). Nunca coloque endereço.

Regras obrigatórias (código de ética da ABPp):
- nada de casos de pacientes; nunca prometer diagnóstico, cura ou resultado;
- temas clínicos (TDAH, dislexia, TEA, discalculia) só em linguagem informativa, dizendo que o diagnóstico
  é feito por profissionais e que um sinal sozinho não é diagnóstico;
- nada de política; nenhum nome de pessoa real além da Michelle.

Formato (igual aos exemplos): carrossel de 4 a 6 slides, o primeiro "capa" e o último "cta" com
"botao": "Agende pelo WhatsApp 💜". Modelos de slide: capa (selo, titulo, texto), texto (selo, emoji, titulo,
caixa), lista (selo, titulo, icone "1" ou "♡", itens: 2 a 4 itens curtos), citacao (texto, autor), cta
(titulo, texto, botao). Marcações: *destaque* (dourado) e _cursiva_; use \\n para quebrar linha nos títulos.
TEXTOS CURTOS: título até ~45 caracteres, caixa até ~220, cada item até ~70 — senão a arte estoura.
Legenda: 1ª linha é um gancho falando com o pai/mãe, depois conteúdo prático, depois
"📲 ... WhatsApp — link na bio." e um convite para salvar ou comentar. "hashtags": no máximo 5, sem "#",
sempre com "psicopedagogia". "story": {"selo", "emoji", "titulo", "texto"} com uma pergunta aberta.
Se a Michelle mandou o texto pronto, preserve as palavras e ideias dela, só organizando em slides.
Responda SÓ com o JSON do post: {"tema", "slides", "legenda", "hashtags", "story"}."""


def disponivel() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _claude(pedido: str) -> str:
    corpo = json.dumps({"model": MODELO, "max_tokens": 4000, "system": REGRAS,
                        "messages": [{"role": "user", "content": pedido}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=corpo, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.loads(r.read().decode())
    return "".join(b.get("text", "") for b in resp.get("content", []))


def _validar(p: dict) -> dict:
    slides = p.get("slides") or []
    if not (3 <= len(slides) <= 7) or slides[0].get("modelo") != "capa" or slides[-1].get("modelo") != "cta":
        raise ValueError("post fora do formato (capa ... cta)")
    if not p.get("tema") or not p.get("legenda"):
        raise ValueError("faltou tema ou legenda")
    p["hashtags"] = [h.lstrip("#") for h in (p.get("hashtags") or [])][:5]
    return p


def _proximo_id(pauta: list[dict]) -> str:
    nums = [int(p["id"]) for p in pauta if str(p.get("id", "")).isdigit()]
    return f"{(max(nums) if nums else 0) + 1:03d}"


def criar(pedido: str, pauta: list[dict], base: dict | None = None) -> dict:
    """Devolve o post pronto (status "sugestao"). Com `base`, refaz aquele post mantendo id e data."""
    exemplos = [{k: p[k] for k in ("tema", "slides", "legenda", "hashtags", "story") if k in p}
                for p in pauta if p.get("formato") == "carrossel"][:2]
    msg = "Exemplos de posts deste perfil (siga o formato):\n" + json.dumps(exemplos, ensure_ascii=False)
    if base:
        atual = {k: base[k] for k in ("tema", "slides", "legenda", "hashtags", "story") if k in base}
        msg += ("\n\nPost atual:\n" + json.dumps(atual, ensure_ascii=False) +
                "\n\nRefaça este post seguindo o pedido da Michelle (pode ter vindo de áudio transcrito, "
                "interprete com bom senso):\n" + pedido)
    else:
        msg += ("\n\nCrie um post novo a partir deste pedido da Michelle (pode ter vindo de áudio transcrito, "
                "interprete com bom senso):\n" + pedido)
    texto = _claude(msg)
    novo = _validar(json.loads(texto[texto.index("{"): texto.rindex("}") + 1]))
    post = dict(base) if base else {"id": _proximo_id(pauta), "formato": "carrossel"}
    post.update(novo, status="sugestao", pedido=pedido[:500],
                criado=datetime.now(TZ).isoformat(timespec="minutes"))
    return post
