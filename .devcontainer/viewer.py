"""Visualizador com zoom e arrastar (roda do rato, botões, duplo clique), em HTML+JS puro.

Não precisa de bibliotecas no PC do técnico: corre no browser. Aceita PNG ou SVG (vetorial,
nítido em qualquer zoom).
"""
from __future__ import annotations

import base64


def renderizar_pagina(pdf_path, pagina: int, zoom: float = 3.0, blocos_traduzidos: list[dict] | None = None,
                      formato: str = "png") -> tuple[bytes, str]:
    """(bytes, mime). Se houver blocos traduzidos, aplica-os numa cópia em memória da página."""
    import fitz
    from . import translate
    with fitz.open(pdf_path) as doc:
        pag = doc.load_page(pagina - 1)
        if blocos_traduzidos:
            translate.aplicar_traducao_na_pagina(pag, blocos_traduzidos)
        if formato == "svg":
            return pag.get_svg_image(text_as_path=True).encode("utf-8"), "image/svg+xml"
        pix = pag.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png"), "image/png"


_TEMPLATE = """
<style>
 html,body{margin:0;height:100%;background:#0b1020;font-family:Segoe UI,Roboto,sans-serif}
 #wrap{position:relative;width:100%;height:__ALTURA__px;overflow:hidden;background:#fff;border:1px solid #334155;
       border-radius:8px;cursor:grab;touch-action:none}
 #wrap.arrasta{cursor:grabbing}
 #img{position:absolute;left:0;top:0;transform-origin:0 0;user-select:none;-webkit-user-drag:none;max-width:none}
 #bar{position:absolute;top:8px;right:8px;display:flex;gap:6px;z-index:5}
 #bar button{background:#0284c7;color:#fff;border:0;border-radius:6px;padding:6px 10px;font-size:15px;cursor:pointer}
 #bar button:hover{background:#0ea5e9}
 #dica{position:absolute;left:8px;bottom:6px;font-size:12px;color:#475569;background:rgba(255,255,255,.8);
       padding:2px 6px;border-radius:4px}
</style>
<div id="wrap">
  <div id="bar"><button id="mais" title="Aproximar">＋</button><button id="menos" title="Afastar">－</button>
  <button id="ajusta" title="Ajustar ao ecrã">⤢</button><button id="cheio" title="Ecrã inteiro">⛶</button></div>
  <img id="img" src="data:__MIME__;base64,__B64__" draggable="false">
  <div id="dica">Roda do rato = zoom · Arrastar = mover · Duplo clique = ajustar</div>
</div>
<script>
(function(){
 const w=document.getElementById('wrap'), im=document.getElementById('img');
 let s=1,x=0,y=0,drag=false,sx=0,sy=0;
 function ap(){im.style.transform='translate('+x+'px,'+y+'px) scale('+s+')';}
 function ajusta(){const iw=im.naturalWidth||1, ih=im.naturalHeight||1;
   s=Math.min(w.clientWidth/iw,w.clientHeight/ih); x=(w.clientWidth-iw*s)/2; y=(w.clientHeight-ih*s)/2; ap();}
 function zoomEm(f,cx,cy){const n=Math.min(Math.max(s*f,0.02),60); const k=n/s;
   x=cx-(cx-x)*k; y=cy-(cy-y)*k; s=n; ap();}
 im.onload=ajusta; if(im.complete) ajusta();
 w.addEventListener('wheel',e=>{e.preventDefault();const r=w.getBoundingClientRect();
   zoomEm(e.deltaY<0?1.2:1/1.2,e.clientX-r.left,e.clientY-r.top);},{passive:false});
 w.addEventListener('pointerdown',e=>{if(e.target.closest('#bar'))return;drag=true;sx=e.clientX-x;sy=e.clientY-y;
   w.classList.add('arrasta');w.setPointerCapture(e.pointerId);});
 w.addEventListener('pointermove',e=>{if(!drag)return;x=e.clientX-sx;y=e.clientY-sy;ap();});
 w.addEventListener('pointerup',()=>{drag=false;w.classList.remove('arrasta');});
 w.addEventListener('dblclick',ajusta);
 document.getElementById('mais').onclick=()=>zoomEm(1.4,w.clientWidth/2,w.clientHeight/2);
 document.getElementById('menos').onclick=()=>zoomEm(1/1.4,w.clientWidth/2,w.clientHeight/2);
 document.getElementById('ajusta').onclick=ajusta;
 document.getElementById('cheio').onclick=()=>{ if(document.fullscreenElement){document.exitFullscreen();}
   else{w.requestFullscreen&&w.requestFullscreen();} setTimeout(ajusta,250);};
 window.addEventListener('resize',ajusta);
})();
</script>
"""


def html_visualizador(imagem: bytes, mime: str, altura: int = 640) -> str:
    return (_TEMPLATE.replace("__ALTURA__", str(altura)).replace("__MIME__", mime)
            .replace("__B64__", base64.b64encode(imagem).decode("ascii")))
