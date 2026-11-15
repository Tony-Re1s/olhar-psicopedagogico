"""Estúdio do Instagram @olhar_.psicopedagogico (Michelle Reis, psicopedagoga).

Gera as artes (PNG) e os Reels (MP4) a partir da pauta, sempre no mesmo padrão visual.

Uso:
    python instagram/estudio.py 001             # gera o post 001 em instagram/saida/001/
    python instagram/estudio.py 001 --amostra   # Reels: só alguns quadros, para conferir rápido

Padrão visual, tirado do logo:
- cores: fundo creme #FCF9F2, lilás #B597CC, lilás escuro #6E5482 (texto), lilás claro #EFE6F4, dourado #C4A15A;
- letras: Cormorant Garamond nos títulos, Nunito no texto e Great Vibes (cursiva) só em destaques curtos;
- rodapé com o logo, "Michelle Reis · Psicopedagoga" e @olhar_.psicopedagogico;
- tamanhos: feed 1080x1350 (4:5); Reels e Story 1080x1920 (9:16).

Marcações no texto da pauta:
- *assim* vira destaque dourado em itálico;
- _assim_ vira letra cursiva;
- \\n vira quebra de linha.

Regras de conteúdo: nada de fotos de crianças reais nem de casos de pacientes. As artes usam só tipografia, ornamentos e emojis.
"""
from __future__ import annotations

import base64
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

D = Path(__file__).resolve().parent
A = D / "assets"
PAUTA = D / "pauta.json"
SAIDA = D / "saida"
FPS = 30
PERFIL = "@olhar_.psicopedagogico"


def b64(p: Path, mime="image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def _fonte(familia: str, arquivo: str, peso: int, estilo="normal") -> str:
    return (f"@font-face{{font-family:'{familia}';font-weight:{peso};font-style:{estilo};"
            f"src:url({b64(A / 'fontes' / arquivo, 'font/woff2')})}}")


FONTES = "".join([
    *(_fonte("Cormorant", f"cormorant-garamond-latin-{w}-normal.woff2", w) for w in (500, 600, 700)),
    _fonte("Cormorant", "cormorant-garamond-latin-500-italic.woff2", 500, "italic"),
    *(_fonte("Nunito", f"nunito-latin-{w}-normal.woff2", w) for w in (500, 600, 700, 800)),
    _fonte("Vibes", "great-vibes-latin-400-normal.woff2", 400),
])
LOGO = b64(A / "logo.png")

CSS = FONTES + """
:root{--creme:#FCF9F2;--lil:#B597CC;--lil2:#6E5482;--lil3:#EFE6F4;--ouro:#C4A15A;--ouro2:#A8873F;--ameixa:#4E3961}
*{box-sizing:border-box;margin:0;padding:0}
body{width:var(--w);height:var(--h);font-family:Nunito,sans-serif;color:var(--lil2);overflow:hidden;position:relative}
.creme{background:var(--creme)}
.lilas{background:linear-gradient(160deg,#F3ECF8 0%,#E6D8F0 60%,#DCCAEA 100%)}
.ameixa{background:linear-gradient(160deg,#5A4270 0%,#4E3961 100%);color:#FCF9F2}
.pad{position:absolute;inset:0;padding:130px 100px 170px}
.centro{display:flex;flex-direction:column;justify-content:center;padding-bottom:220px}
.centro>*{flex-shrink:0}
.h1{font-family:Cormorant,serif;font-weight:700;font-size:104px;line-height:1.0;letter-spacing:-.5px}
.h2{font-family:Cormorant,serif;font-weight:700;font-size:80px;line-height:1.04}
.h3{font-family:Nunito,sans-serif;font-weight:700;font-size:42px;line-height:1.28}
.txt{font-weight:600;font-size:38px;line-height:1.45}
.mark{font-family:Cormorant,serif;font-style:italic;font-weight:500;color:var(--ouro2)}
.txt .mark,.h3 .mark{font-size:1.18em}
.ameixa .mark{color:#E2C88A}
.script{font-family:Vibes,cursive;font-weight:400;color:var(--ouro);font-size:1.25em;line-height:.8}
.ameixa .script{color:#E2C88A}
.selo{display:inline-flex;align-self:flex-start;align-items:center;gap:14px;font-weight:800;font-size:26px;letter-spacing:3px;
      text-transform:uppercase;color:var(--ouro2)}
.selo:before{content:'';width:46px;height:2px;background:var(--ouro)}
.ameixa .selo{color:#E2C88A}
.ameixa .selo:before{background:#E2C88A}
.moldura{position:absolute;inset:40px;border:2px solid rgba(196,161,90,.55);border-radius:34px;pointer-events:none}
.ameixa .moldura{border-color:rgba(226,200,138,.35)}
.rodape{position:absolute;left:100px;right:100px;bottom:70px;display:flex;align-items:center;justify-content:space-between;
        font-weight:700;font-size:26px;color:var(--lil2)}
.ameixa .rodape{color:#EDE3F3}
.marca{display:flex;align-items:center;gap:16px}
.marca img{width:66px;height:66px;border-radius:50%;box-shadow:0 4px 14px rgba(78,57,97,.18)}
.marca b{font-family:Cormorant,serif;font-weight:700;font-size:32px}
.pag{position:absolute;top:74px;right:100px;font-weight:800;font-size:26px;color:var(--ouro2);letter-spacing:2px}
.ameixa .pag{color:#E2C88A}
.arrasta{position:absolute;right:100px;bottom:170px;font-family:Cormorant,serif;font-style:italic;font-weight:500;font-size:40px;color:var(--ouro2)}
.item{display:flex;gap:28px;align-items:flex-start;margin:30px 0}
.item .b{flex:0 0 64px;height:64px;border-radius:50%;display:flex;align-items:center;justify-content:center;
         font-family:Cormorant,serif;font-size:38px;font-weight:700;background:var(--lil3);color:var(--lil2);border:2px solid var(--ouro);margin-top:2px}
.ameixa .item .b{background:rgba(255,255,255,.1);color:#E2C88A}
.cartao{background:#fff;color:var(--lil2);border-radius:30px;box-shadow:0 18px 50px rgba(78,57,97,.10);padding:42px 46px;border:1.5px solid rgba(196,161,90,.4)}
.cta{display:inline-block;background:var(--lil2);color:#fff;font-weight:800;font-size:38px;padding:26px 56px;border-radius:999px;
     box-shadow:0 14px 30px rgba(110,84,130,.30)}
.ameixa .cta{background:var(--ouro);color:var(--ameixa)}
.emoji{font-size:130px;line-height:1}
.ramo{position:absolute;opacity:.18;font-size:280px;line-height:1;color:var(--lil)}
.ornamento{display:flex;align-items:center;gap:18px;color:var(--ouro);font-size:30px}
.ornamento:before,.ornamento:after{content:'';flex:0 0 90px;height:2px;background:var(--ouro);opacity:.7}
.bolha{position:absolute;border-radius:50%;background:var(--lil);opacity:.10}
.ameixa .bolha{background:#fff;opacity:.05}
"""


def fmt(t: str | None) -> str:
    """Texto da pauta -> HTML: escapa; *destaque* (dourado itálico); _cursiva_; \\n vira quebra."""
    t = html.escape(t or "")
    t = re.sub(r"\*(.+?)\*", r"<span class='mark'>\1</span>", t)
    t = re.sub(r"(?<![\w/])_(.+?)_(?!\w)", r"<span class='script'>\1</span>", t)
    return t.replace("\n", "<br>")


def rodape(bottom=70) -> str:
    return (f"<div class='rodape' style='bottom:{bottom}px'><div class='marca'><img src='{LOGO}'>"
            f"<div><b>Michelle Reis</b><div style='font-size:20px;letter-spacing:3px;font-weight:800;color:var(--ouro2)'>PSICOPEDAGOGA</div></div></div>"
            f"<div>{PERFIL}</div></div>")


def enfeites() -> str:
    return ("<div class='bolha' style='width:560px;height:560px;right:-220px;top:-200px'></div>"
            "<div class='bolha' style='width:320px;height:320px;left:-140px;bottom:240px'></div><div class='moldura'></div>")


def pagina(corpo: str, fundo: str, w=1080, h=1350) -> str:
    return (f"<html><head><meta charset='utf-8'><style>{CSS}</style></head>"
            f"<body class='{fundo}' style='--w:{w}px;--h:{h}px'>{corpo}</body></html>")


# ---------------------------------------------------------------- modelos de slide (feed 4:5)
def slide(s: dict, i: int, n: int) -> str:
    m = s.get("modelo", "texto")
    fundo = s.get("fundo") or {"capa": "lilas", "cta": "ameixa", "citacao": "ameixa"}.get(m, "creme")
    pag = f"<div class='pag'>{i:02d} / {n:02d}</div>" if n > 1 else ""
    selo = f"<div class='selo'>{fmt(s['selo'])}</div>" if s.get("selo") else ""
    arrasta = "<div class='arrasta'>arraste →</div>" if (m == "capa" and n > 1) else ""
    if m == "capa":
        emoji = f"<div class='emoji' style='margin-top:40px'>{s['emoji']}</div>" if s.get("emoji") else ""
        corpo = f"""<div class='pad' style='display:flex;flex-direction:column;justify-content:center;padding-bottom:240px'>{selo}{emoji}
          <div class='h1' style='margin-top:{40 if emoji else 56}px;font-size:{s.get('tamanho') or 112}px'>{fmt(s.get('titulo'))}</div>
          <div class='txt' style='margin-top:44px;max-width:860px;font-size:40px'>{fmt(s.get('texto'))}</div>{arrasta}</div>"""
    elif m == "lista":
        marca = s.get("icone", "1")
        itens = "".join(
            f"<div class='item'><div class='b'>{(k + 1) if marca == '1' else marca}</div>"
            f"<div class='h3'>{fmt(t)}</div></div>" for k, t in enumerate(s.get("itens") or []))
        corpo = f"""<div class='pad centro'>{selo}<div class='h2' style='margin-top:{30 if selo else 0}px'>{fmt(s.get('titulo'))}</div>
          <div style='margin-top:34px'>{itens}</div>
          <div class='txt' style='margin-top:18px;font-size:34px;opacity:.9'>{fmt(s.get('texto'))}</div></div>"""
    elif m == "citacao":
        corpo = f"""<div class='pad' style='display:flex;flex-direction:column;justify-content:center;padding-bottom:240px'>{selo}
          <div style='font-family:Cormorant,serif;font-weight:700;font-size:240px;line-height:.55;color:#E2C88A;margin-top:50px'>“</div>
          <div class='h2' style='margin-top:20px;font-weight:600'>{fmt(s.get('texto'))}</div>
          <div class='ornamento' style='margin-top:56px'>♡</div>
          <div class='h3' style='margin-top:26px;opacity:.9;font-weight:600'>{fmt(s.get('autor'))}</div></div>"""
    elif m == "cta":
        corpo = f"""<div class='pad' style='text-align:center;padding-top:180px'>
          <img src='{LOGO}' style='width:250px;height:250px;border-radius:50%;box-shadow:0 20px 50px rgba(0,0,0,.25)'>
          <div class='h1' style='margin-top:56px;font-size:88px'>{fmt(s.get('titulo'))}</div>
          <div class='txt' style='margin-top:30px'>{fmt(s.get('texto'))}</div>
          <div style='margin-top:54px'><span class='cta'>{fmt(s.get('botao') or 'Agende pelo WhatsApp 💜')}</span></div></div>"""
    else:  # texto
        emoji = f"<div class='emoji' style='margin-top:{30 if selo else 0}px'>{s['emoji']}</div>" if s.get("emoji") else ""
        caixa = (f"<div class='cartao' style='margin-top:50px'><div class='txt' style='font-size:40px'>{fmt(s.get('caixa'))}</div></div>"
                 if s.get("caixa") else "")
        corpo = f"""<div class='pad centro'>{selo}{emoji}<div class='h2' style='margin-top:{36 if (selo or emoji) else 0}px'>{fmt(s.get('titulo'))}</div>
          <div class='txt' style='margin-top:40px;max-width:880px'>{fmt(s.get('texto'))}</div>{caixa}</div>"""
    return pagina(enfeites() + pag + corpo + rodape(), fundo)


# ---------------------------------------------------------------- story (9:16)
def story(s: dict) -> str:
    fundo = s.get("fundo") or "lilas"
    pergunta = (f"<div class='cartao' style='margin-top:80px;text-align:center'><div class='h3'>{fmt(s.get('pergunta'))}</div>"
                f"<div class='txt' style='margin-top:20px;font-size:34px;color:var(--ouro2)'>Me conta por mensagem 💬</div></div>"
                if s.get("pergunta") else "")
    corpo = f"""{enfeites()}<div style='position:absolute;left:100px;right:100px;top:300px'>
      {f"<div class='selo'>{fmt(s['selo'])}</div>" if s.get('selo') else ''}
      {f"<div class='emoji' style='margin-top:40px'>{s['emoji']}</div>" if s.get('emoji') else ''}
      <div class='h1' style='margin-top:40px;font-size:100px'>{fmt(s.get('titulo'))}</div>
      <div class='txt' style='margin-top:36px;font-size:42px'>{fmt(s.get('texto'))}</div>{pergunta}</div>{rodape(220)}"""
    return pagina(corpo, fundo, h=1920)


# ---------------------------------------------------------------- Reels (9:16): texto animado, cena a cena
REELS_HTML = """<html><head><meta charset='utf-8'><style>""" + CSS + """
body{width:1080px;height:1920px}
.cena{position:absolute;inset:0;display:none;overflow:hidden}
.bloco{position:absolute;left:100px;right:100px;top:560px}
.barra{position:absolute;left:100px;right:100px;top:130px;height:6px;border-radius:6px;background:rgba(110,84,130,.15);overflow:hidden}
.ameixa .barra{background:rgba(255,255,255,.2)}
.barra i{display:block;height:100%;background:var(--ouro);border-radius:6px}
.lin{display:block;opacity:0}
</style></head><body>__CENAS__
<script>
const cl=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const ease=x=>{x=cl(x);return 1-Math.pow(1-x,3)};
function render(c,t,dur,total,ini){
  document.querySelectorAll('.cena').forEach(e=>e.style.display='none');
  const s=document.getElementById('c'+c); s.style.display='block';
  const bar=s.querySelector('.barra i'); if(bar) bar.style.width=(100*(ini+t)/total)+'%';
  const em=s.querySelector('.emoji'); if(em){const k=ease(t/0.6); em.style.transform=`scale(${0.6+0.4*k})`; em.style.opacity=k;}
  s.querySelectorAll('.lin').forEach((l,i)=>{const k=ease((t-0.2-i*0.18)/0.6); l.style.opacity=k; l.style.transform=`translateY(${(1-k)*40}px)`;});
  const sub=s.querySelector('.sub'); if(sub){const k=ease((t-0.3-0.18*s.querySelectorAll('.lin').length)/0.6); sub.style.opacity=k;}
  const lg=s.querySelector('.logofinal'); if(lg){const k=ease(t/0.8); lg.style.opacity=k; lg.style.transform=`scale(${0.85+0.15*k})`;}
}
</script></body></html>"""


def _cena_html(k: int, c: dict) -> str:
    fundo = c.get("fundo") or ("lilas" if k % 2 else "creme")
    linhas = "".join(f"<span class='lin'>{fmt(x)}</span>" for x in (c.get("titulo") or "").split("\n"))
    emoji = f"<div class='emoji' style='margin-bottom:50px'>{c['emoji']}</div>" if c.get("emoji") else ""
    sub = f"<div class='txt sub' style='margin-top:50px;font-size:48px;opacity:0'>{fmt(c.get('sub'))}</div>" if c.get("sub") else ""
    return (f"<div class='cena {fundo}' id='c{k}'>{enfeites()}<div class='barra'><i></i></div>"
            f"<div class='bloco'>{emoji}<div class='h1' style='font-size:{c.get('tamanho') or 116}px'>{linhas}</div>{sub}</div>"
            f"{rodape(220)}</div>")


def _cena_final(k: int, fim: dict) -> str:
    return (f"<div class='cena ameixa' id='c{k}'>{enfeites()}<div style='position:absolute;left:100px;right:100px;top:420px;text-align:center'>"
            f"<img class='logofinal' src='{LOGO}' style='width:360px;height:360px;border-radius:50%'>"
            f"<div class='h1' style='margin-top:70px;font-size:96px'>{fmt(fim.get('titulo') or 'Michelle Reis')}</div>"
            f"<div class='txt' style='margin-top:30px;font-size:46px'>{fmt(fim.get('sub') or 'Um olhar atento para cada aprendizagem')}</div>"
            f"<div style='margin-top:70px'><span class='cta' style='font-size:48px'>{fmt(fim.get('botao') or 'Agende pelo WhatsApp 💜')}</span></div>"
            f"</div></div>")


def reels(post: dict, pasta: Path, amostra=False):
    from playwright.sync_api import sync_playwright
    cenas = post["cenas"]
    fim = post.get("fim") or {}
    roteiro = [(k + 1, float(c.get("dur") or 2.8)) for k, c in enumerate(cenas)] + [(len(cenas) + 1, float(fim.get("dur") or 3.2))]
    total = sum(d for _, d in roteiro)
    doc = REELS_HTML.replace("__CENAS__", "".join(_cena_html(k + 1, c) for k, c in enumerate(cenas))
                             + _cena_final(len(cenas) + 1, fim))
    arq = pasta / "_reels.html"
    arq.write_text(doc)
    quadros = pasta / "_quadros"
    shutil.rmtree(quadros, ignore_errors=True)
    quadros.mkdir()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1080, "height": 1920})
        pg.goto(arq.as_uri())
        pg.wait_for_timeout(800)
        n, ini = 0, 0.0
        for c, dur in roteiro:
            passos = [dur * 0.7] if amostra else [i / FPS for i in range(round(dur * FPS))]
            for t in passos:
                pg.evaluate(f"render({c},{t},{dur},{total},{ini})")
                pg.screenshot(path=str(quadros / f"{n:05d}.jpg"), type="jpeg", quality=92)
                n += 1
            ini += dur
        pg.evaluate(f"render(1,{min(roteiro[0][1] - 0.2, 1.8)},{roteiro[0][1]},{total},0)")
        pg.screenshot(path=str(pasta / "capa.jpg"), type="jpeg", quality=92)
        b.close()
    if amostra:
        return
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(quadros / "%05d.jpg"),
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-shortest",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high", "-level", "4.1",
                    "-g", str(FPS * 2), "-r", str(FPS),
                    "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                    "-movflags", "+faststart", str(pasta / "reels.mp4")], check=True)
    shutil.rmtree(quadros, ignore_errors=True)
    arq.unlink(missing_ok=True)


# ---------------------------------------------------------------- gerar um post
def legenda(post: dict) -> str:
    tags = " ".join("#" + h.lstrip("#") for h in (post.get("hashtags") or [])[:5])   # no máximo 5 hashtags
    return (post.get("legenda") or "").strip() + ("\n\n" + tags if tags else "")


def gerar(post: dict, amostra=False) -> Path:
    from playwright.sync_api import sync_playwright
    pasta = SAIDA / post["id"]
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True)
    if post["formato"] == "reels":
        reels(post, pasta, amostra)
    else:
        slides = post.get("slides") or []
        with sync_playwright() as p:
            b = p.chromium.launch()
            for i, s in enumerate(slides, start=1):
                pg = b.new_page(viewport={"width": 1080, "height": 1350})
                pg.set_content(slide(s, i, len(slides)))
                pg.wait_for_timeout(300)
                pg.screenshot(path=str(pasta / f"{i:02d}.png"))
                pg.close()
            b.close()
    if post.get("story"):
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1080, "height": 1920})
            pg.set_content(story(post["story"]))
            pg.wait_for_timeout(300)
            pg.screenshot(path=str(pasta / "story.png"))
            b.close()
    (pasta / "legenda.txt").write_text(legenda(post))
    return pasta


def carregar() -> list[dict]:
    return json.loads(PAUTA.read_text())


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pauta = carregar()
    alvo = next(p for p in pauta if p["id"] == args[0])
    out = gerar(alvo, amostra="--amostra" in sys.argv)
    print(alvo["id"], alvo["formato"], "->", out)
    for f in sorted(out.iterdir()):
        print("  ", f.name)
