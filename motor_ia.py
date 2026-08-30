# -*- coding: utf-8 -*-
"""
Camada de IA do Crivo. Funciona com DOIS motores:

  • Groq (NUVEM)  — usado quando existe a chave GROQ_API_KEY (env ou st.secrets).
                    É o modo do site publicado. Modelo padrao llama-3.3-70b.
  • Ollama (LOCAL)— usado quando NAO ha chave Groq e o Ollama esta rodando.
                    Modo de quando voce roda na sua maquina.

Faz: estruturar PICO, montar strings de busca, triar titulo/resumo, preencher a
ficha e rascunhar o manuscrito. REGRA DE OURO: o rascunho e ANCORADO — so usa/cita
as referencias incluidas. Nada de referencia inventada.
"""
import json
import os
import re

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
MODELO_OLLAMA = "qwen2.5:3b"
MODELO_GROQ = "llama-3.3-70b-versatile"
MODELO_GEMINI = "gemini-flash-latest"
MODELO_PADRAO = MODELO_OLLAMA  # compatibilidade
TIMEOUT = 180


def _ler_chave(nome) -> str:
    """Le uma chave de env var OU de st.secrets (no Streamlit Cloud)."""
    k = os.environ.get(nome, "").strip()
    if k:
        return k
    try:
        import streamlit as st
        return str(st.secrets.get(nome, "")).strip()
    except Exception:
        return ""


def _groq_key() -> str:
    return _ler_chave("GROQ_API_KEY")


def _google_key() -> str:
    return _ler_chave("GOOGLE_API_KEY")


# Descobre a LISTA de modelos Gemini que a chave aceita, em ordem de preferencia.
# Assim, se um modelo der 404 (aposentado) ou 429/503 (limite/sobrecarga), o app
# tenta o proximo — e como cada modelo tem cota gratuita SEPARADA, isso multiplica
# o quanto da pra usar de graca. Resultado fica em cache.
_GEMINI_CACHE = None
_GEMINI_BOM = None  # ultimo modelo que respondeu OK (tenta ele primeiro = mais rapido)


def _gemini_candidatos() -> list:
    """Lista ordenada de modelos Gemini a tentar (melhores primeiro)."""
    global _GEMINI_CACHE
    if _GEMINI_CACHE:
        return _GEMINI_CACHE
    nomes = []
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         params={"key": _google_key()}, timeout=30)
        r.raise_for_status()
        for m in r.json().get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                nomes.append(m.get("name", "").split("/")[-1])
    except Exception:
        nomes = []

    def score(n):
        n = n.lower()
        s = 0
        if "flash" in n:
            s += 20
        elif "pro" in n:
            s += 8
        if "2.5" in n:
            s += 6
        elif "2.0" in n:
            s += 5
        elif "1.5" in n:
            s += 3
        if "lite" in n:
            s -= 1
        if "latest" in n:
            s -= 1
        if any(x in n for x in ("exp", "preview", "thinking", "vision", "tts",
                                "embedding", "image", "learnlm", "aqa", "gemma")):
            s -= 50
        return s

    nomes = sorted({n for n in nomes if score(n) > -40}, key=score, reverse=True)
    # garante alguns nomes conhecidos no fim (caso o ListModels venha vazio/limitado)
    for fb in ("gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-flash",
               "gemini-2.0-flash-001", "gemini-flash-latest"):
        if fb not in nomes:
            nomes.append(fb)
    _GEMINI_CACHE = nomes
    return nomes


def ollama_disponivel() -> tuple[bool, str]:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        r.raise_for_status()
        modelos = [m.get('name', '') for m in r.json().get('models', [])]
        return True, ', '.join(modelos) if modelos else '(nenhum modelo baixado)'
    except Exception as e:
        return False, str(e)


def provedor_ativo() -> tuple[str, str, bool, str]:
    """Retorna (provedor, modelo_padrao, disponivel, info). Prioridade:
    Google Gemini > Groq > Ollama local, conforme a chave presente."""
    if _google_key():
        cands = _gemini_candidatos()
        m = cands[0] if cands else MODELO_GEMINI
        return ('gemini', m, True, f'Google Gemini (nuvem) · {m}')
    if _groq_key():
        return ('groq', MODELO_GROQ, True, f'Groq (nuvem) · {MODELO_GROQ}')
    ok, info = ollama_disponivel()
    return ('ollama', MODELO_OLLAMA, ok, info)


# ---------------- motor de chat (despacha p/ o provedor ativo) ----------------
def _chat_groq(system, prompt, modelo, json_mode, temperatura) -> str:
    corpo = {
        "model": modelo or MODELO_GROQ,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "temperature": temperatura,
    }
    if json_mode:
        corpo["response_format"] = {"type": "json_object"}
    r = requests.post(GROQ_URL, timeout=TIMEOUT, json=corpo, headers={
        "Authorization": "Bearer " + _groq_key(), "Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _chat_ollama(system, prompt, modelo, json_mode, temperatura) -> str:
    corpo = {
        "model": modelo or MODELO_OLLAMA,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": temperatura},
    }
    if json_mode:
        corpo["format"] = "json"
    r = requests.post(OLLAMA_URL, json=corpo, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "").strip()


def _chat_gemini(system, prompt, modelo, json_mode, temperatura) -> str:
    import time
    url = GEMINI_URL.format(modelo=modelo or MODELO_GEMINI)
    corpo = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperatura},
    }
    if json_mode:
        corpo["generationConfig"]["responseMimeType"] = "application/json"
    ultimo = 0
    for tent in range(3):
        r = requests.post(url, timeout=TIMEOUT, params={"key": _google_key()},
                          json=corpo, headers={"Content-Type": "application/json"})
        if r.status_code == 200:
            dados = r.json()
            try:
                return dados["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception:
                raise RuntimeError("Gemini: resposta sem texto (pode ser filtro de conteudo)")
        ultimo = r.status_code
        # 500/503 = sobrecarga passageira -> espera pouco e tenta de novo o mesmo.
        # 429 (limite) NAO adianta repetir: a camada de cima troca de modelo na hora
        # (cada modelo tem cota separada), o que e bem mais rapido.
        if r.status_code in (500, 503) and tent < 2:
            time.sleep(1.0 * (tent + 1))  # 1s, 2s
            continue
        # 404 e outros -> definitivo (a camada acima troca de modelo no 404).
        # NAO vaza a chave (que ia no ?key= da URL) na mensagem.
        raise RuntimeError(f"Gemini HTTP {r.status_code} ({modelo or MODELO_GEMINI})")
    raise RuntimeError(f"Gemini HTTP {ultimo} sobrecarga ({modelo or MODELO_GEMINI})")


def _chat(system, prompt, modelo=None, json_mode=False, temperatura=0.2) -> str:
    prov, _mod_def, _ok, _info = provedor_ativo()
    if prov == 'gemini':
        if modelo and 'gemini' in str(modelo).lower():
            return _chat_gemini(system, prompt, str(modelo), json_mode, temperatura)
        global _GEMINI_BOM
        cands = _gemini_candidatos()
        # comeca pelo modelo que funcionou por ultimo (evita re-testar os lotados)
        if _GEMINI_BOM and _GEMINI_BOM in cands:
            cands = [_GEMINI_BOM] + [c for c in cands if c != _GEMINI_BOM]
        # tenta cada candidato; pula os indisponiveis (404) ou no limite (429/500/503)
        erro = None
        for m in cands:
            try:
                r = _chat_gemini(system, prompt, m, json_mode, temperatura)
                _GEMINI_BOM = m  # lembra o que funcionou p/ acelerar as proximas
                return r
            except RuntimeError as e:
                erro = e
                if any(c in str(e) for c in ('404', '429', '500', '503', 'sobrecarga')):
                    continue
                raise
        raise erro or RuntimeError("Gemini: nenhum modelo disponivel no momento")
    if prov == 'groq':
        m = modelo if (modelo and 'llama' in str(modelo).lower()) else MODELO_GROQ
        return _chat_groq(system, prompt, m, json_mode, temperatura)
    m = modelo if (modelo and ':' in str(modelo)) else MODELO_OLLAMA
    return _chat_ollama(system, prompt, m, json_mode, temperatura)


def _json_seguro(txt, padrao):
    if not txt:
        return padrao
    try:
        return json.loads(txt)
    except Exception:
        pass
    m = re.search(r'(\{.*\}|\[.*\])', txt, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return padrao
    return padrao


# ---------------- 1. PICO ----------------
def estruturar_pico(tema, descricao, modelo=None) -> dict:
    system = ("Voce e um bibliotecario de revisoes sistematicas. Extraia o PICO da "
              "pergunta de pesquisa. Responda SO em JSON com as chaves: populacao, "
              "intervencao, comparacao, desfecho, tipo_estudo, idioma, periodo. "
              "Se algo nao se aplica, use string vazia. Em portugues.")
    prompt = f"Tema: {tema}\nDescricao: {descricao}\n\nMonte o PICO em JSON."
    d = _json_seguro(_chat(system, prompt, modelo, json_mode=True), {})
    base = {k: '' for k in ('populacao', 'intervencao', 'comparacao', 'desfecho',
                            'tipo_estudo', 'idioma', 'periodo')}
    if isinstance(d, dict):
        base.update({k: str(d.get(k, '') or '') for k in base})
    return base


# ---------------- 2. Strings de busca ----------------
def montar_buscas(pico, tema, bases, modelo=None) -> dict:
    system = ("Voce monta strings de busca booleanas para bases academicas. "
              "Use termos em INGLES, operadores AND/OR e parenteses. Para o PubMed, "
              "pode usar termos MeSH. Responda SO em JSON: uma chave por base pedida, "
              "valor = a string de busca. Sem explicacoes.")
    prompt = (f"Tema: {tema}\nPICO: {json.dumps(pico, ensure_ascii=False)}\n"
              f"Bases: {', '.join(bases)}\n\nGere uma string por base (chaves: {', '.join(bases)}).")
    d = _json_seguro(_chat(system, prompt, modelo, json_mode=True), {})
    return {b: str((d.get(b) if isinstance(d, dict) else '') or '').strip() for b in bases}


# ---------------- 3. Triagem titulo/resumo ----------------
def triar_referencia(ref, criterios_inc, criterios_exc, pico, modelo=None) -> dict:
    system = ("Voce faz triagem de titulo/resumo para revisao sistematica. Decida se "
              "o estudo deve ENTRAR (incluir), SAIR (excluir) ou ficar em duvida (talvez), "
              "comparando SO com o resumo dado e os criterios. Nao invente dados que nao "
              "estao no resumo. Responda SO em JSON: {decisao: 'incluir'|'excluir'|'talvez', "
              "motivo: '<curto>', criterio: '<qual criterio pesou>'}. Em portugues.")
    prompt = (
        f"PICO: {json.dumps(pico, ensure_ascii=False)}\n"
        f"Criterios de inclusao: {criterios_inc}\n"
        f"Criterios de exclusao: {criterios_exc}\n\n"
        f"TITULO: {ref.get('titulo','')}\n"
        f"RESUMO: {ref.get('resumo','') or '(sem resumo disponivel)'}\n\n"
        "Decida e justifique em 1 frase.")
    d = _json_seguro(_chat(system, prompt, modelo, json_mode=True), {})
    dec = str((d or {}).get('decisao', '')).lower()
    if dec not in ('incluir', 'excluir', 'talvez'):
        dec = 'talvez'
    return {'decisao': dec, 'motivo': str((d or {}).get('motivo', '') or ''),
            'criterio': str((d or {}).get('criterio', '') or '')}


# ---------------- 4. Ficha de extracao ----------------
CAMPOS_FICHA = ['objetivo', 'desenho', 'amostra', 'intervencao', 'desfechos',
                'resultados', 'conclusao', 'vies', 'relevancia']


def extrair_ficha(ref, modelo=None) -> dict:
    system = ("Voce extrai dados de um estudo para uma ficha de revisao. Use SO o que "
              "esta no titulo/resumo/texto fornecido; se um campo nao aparece, escreva "
              "'nao informado'. Responda SO em JSON com as chaves: "
              + ', '.join(CAMPOS_FICHA) + ". Em portugues, frases curtas.")
    corpo = ref.get('full_text') or ref.get('resumo') or ''
    prompt = f"TITULO: {ref.get('titulo','')}\nTEXTO: {corpo or '(sem resumo)'}\n\nPreencha a ficha."
    d = _json_seguro(_chat(system, prompt, modelo, json_mode=True), {})
    return {c: str((d or {}).get(c, '') or 'nao informado') for c in CAMPOS_FICHA}


# ---------------- 5. Rascunho do manuscrito (ANCORADO) ----------------
def rascunhar_secao(secao, pico, refs_incluidas, texto_extra='', modelo=None) -> str:
    fontes = []
    for i, r in enumerate(refs_incluidas, 1):
        aut = (r.get('autores') or ['(sem autor)'])
        primeiro = aut[0].split()[-1] if aut and aut[0] else 's/autor'
        ficha = r.get('ficha') or {}
        resumo_ficha = '; '.join(f"{k}: {v}" for k, v in ficha.items() if v and v != 'nao informado')
        fontes.append(f"[{i}] {primeiro} {r.get('ano','')} — {r.get('titulo','')}. "
                      f"{resumo_ficha or (r.get('resumo','')[:400])}")
    bloco = "\n".join(fontes) if fontes else "(nenhuma referencia incluida ainda)"
    system = (
        "Voce escreve secoes de um artigo de revisao em portugues cientifico. "
        "REGRA ABSOLUTA: use APENAS as referencias numeradas fornecidas e cite como [n]. "
        "NUNCA invente referencias, dados, numeros ou autores que nao estejam nas fontes. "
        "Se faltar base para uma afirmacao, escreva '[LACUNA: falta evidencia]'. "
        "Nao repita a lista de referencias; escreva o texto corrido da secao.")
    prompt = (
        f"Secao a escrever: {secao}\n"
        f"PICO da revisao: {json.dumps(pico, ensure_ascii=False)}\n"
        f"{('Instrucoes extras: ' + texto_extra) if texto_extra else ''}\n\n"
        f"FONTES (so pode usar estas, citando por [n]):\n{bloco}\n\n"
        f"Escreva a secao '{secao}'.")
    return _chat(system, prompt, modelo, json_mode=False, temperatura=0.35)


if __name__ == '__main__':
    prov, mod, ok, info = provedor_ativo()
    print(f"Provedor ativo: {prov} | modelo {mod} | {'OK' if ok else 'INDISPONIVEL'} | {info}")
    if ok:
        pico = estruturar_pico("Monitoramento hematologico da clozapina",
                               "Adultos em uso de clozapina; monitoramento de leucocitos p/ prevenir agranulocitose.")
        print("PICO:", json.dumps(pico, ensure_ascii=False))
