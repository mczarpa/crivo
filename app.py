# -*- coding: utf-8 -*-
"""
Crivo — servidor do produto (FastAPI). Serve a interface bonita (static/) e
expõe a API que faz a busca real e a expansão de descritores. A IA (triagem,
ficha, manuscrito) entra na etapa 2. Rodar:  python run.py
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

import motor_busca as mb
import motor_ia as mia

BASE = Path(__file__).parent
app = FastAPI(title="Crivo")


class BuscaReq(BaseModel):
    termo: str = ""
    bases: list[str] | None = None
    limite: int = 20
    usar_descritores: bool = True


class TriarReq(BaseModel):
    ref: dict
    criterios_inc: list[str] = []
    criterios_exc: list[str] = []
    pico: dict = {}


@app.get("/api/ia-status")
def ia_status():
    prov, modelo, ok, info = mia.provedor_ativo()
    return {"provedor": prov, "modelo": modelo, "ok": ok, "info": info}


@app.post("/api/triar")
def triar(req: TriarReq):
    pico = req.pico or {"desfecho": req.ref.get("_tema", "")}
    try:
        return mia.triar_referencia(req.ref, req.criterios_inc, req.criterios_exc, pico)
    except Exception as e:
        return {"decisao": "pendente", "motivo": f"erro IA: {e}", "criterio": ""}


@app.get("/api/bases")
def bases():
    return [{"id": k, "nome": v} for k, v in mb.NOMES_BASES.items()]


@app.post("/api/expandir")
def expandir(req: BuscaReq):
    return mb.expandir_descritores(req.termo)


@app.post("/api/buscar")
def buscar(req: BuscaReq):
    termo = (req.termo or "").strip()
    if not termo:
        return {"registros": [], "por_base": {}, "erros": {}, "descritores": {}}

    desc = mb.expandir_descritores(termo) if req.usar_descritores else {"mesh": []}
    mesh = desc.get("mesh", [])[:4]
    # query enriquecida: termo livre OR descritores MeSH (entre aspas)
    if mesh:
        termos = [termo] + [f'"{m}"' for m in mesh]
        query = "(" + " OR ".join(dict.fromkeys(termos)) + ")"
    else:
        query = termo

    bases = req.bases or [b for b in mb.NOMES_BASES if b != "lilacs"]
    alvo = {b: query for b in bases if b in mb.BASES}
    res = mb.buscar_todas(alvo, limite=req.limite)
    res["descritores"] = desc
    res["query"] = query
    return res


@app.get("/")
def index():
    for p in (BASE / "index.html", BASE / "static" / "index.html"):
        if p.exists():
            return FileResponse(str(p))
    return {"erro": "index.html nao encontrado"}
