# -*- coding: utf-8 -*-
"""
Busca em bases academicas GRATUITAS para o Crivo. Cada funcao consulta uma base
real e devolve uma lista de registros NORMALIZADOS (mesmo formato de dict):

    {fonte, doi, titulo, autores[list], ano, revista, resumo, url, keywords[list]}

Bases: PubMed (E-utilities), Europe PMC, Crossref, Semantic Scholar.
Nada de dado inventado — so o que a API devolve. Falha de rede/limite retorna
lista vazia + registra o aviso em `ULTIMO_ERRO` (nao derruba o app).

Boa cidadania: manda tool/email (pool 'polite'), timeout curto, pausa entre
chamadas. Configure o e-mail em EMAIL_CONTATO (usado por PubMed e Crossref).
"""
import html
import re
import time
import xml.etree.ElementTree as ET

import requests

EMAIL_CONTATO = "ame.psiquiatria@example.org"   # troque pelo e-mail institucional
FERRAMENTA = "CrivoAME"
TIMEOUT = 25
ULTIMO_ERRO = {}   # base -> mensagem do ultimo erro


def _limpar(txt) -> str:
    if not txt:
        return ''
    txt = re.sub(r'<[^>]+>', ' ', str(txt))          # tira tags (JATS/HTML)
    txt = html.unescape(txt)
    return re.sub(r'\s+', ' ', txt).strip()


def _norm_titulo(t) -> str:
    return re.sub(r'[^a-z0-9]', '', (t or '').lower())[:80]


def chave_dedup(reg) -> str:
    doi = (reg.get('doi') or '').lower().strip()
    return 'doi:' + doi if doi else 't:' + _norm_titulo(reg.get('titulo'))


# ============================ PubMed ============================
def buscar_pubmed(query, limite=25) -> list:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    comum = {"db": "pubmed", "tool": FERRAMENTA, "email": EMAIL_CONTATO}
    try:
        r = requests.get(f"{base}/esearch.fcgi", timeout=TIMEOUT, params={
            **comum, "term": query, "retmax": limite, "retmode": "json", "sort": "relevance"})
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        time.sleep(0.34)
        rf = requests.get(f"{base}/efetch.fcgi", timeout=TIMEOUT, params={
            **comum, "id": ",".join(ids), "retmode": "xml", "rettype": "abstract"})
        rf.raise_for_status()
        return _parse_pubmed_xml(rf.text)
    except Exception as e:
        ULTIMO_ERRO['pubmed'] = str(e)
        return []


def _parse_pubmed_xml(xml_txt) -> list:
    out = []
    try:
        raiz = ET.fromstring(xml_txt)
    except ET.ParseError as e:
        ULTIMO_ERRO['pubmed'] = f'XML: {e}'
        return out
    for art in raiz.findall('.//PubmedArticle'):
        titulo = _limpar(''.join(art.find('.//ArticleTitle').itertext())) if art.find('.//ArticleTitle') is not None else ''
        partes = [_limpar(''.join(ab.itertext())) for ab in art.findall('.//Abstract/AbstractText')]
        resumo = ' '.join(p for p in partes if p)
        ano = ''
        y = art.find('.//JournalIssue/PubDate/Year')
        if y is not None and y.text:
            ano = y.text
        else:
            md = art.find('.//JournalIssue/PubDate/MedlineDate')
            if md is not None and md.text:
                m = re.search(r'\d{4}', md.text)
                ano = m.group(0) if m else ''
        revista = ''
        jt = art.find('.//Journal/Title')
        if jt is not None and jt.text:
            revista = jt.text
        autores = []
        autores_est = []
        for a in art.findall('.//AuthorList/Author'):
            sob = a.find('LastName'); ini = a.find('Initials')
            if sob is not None and sob.text:
                inic = ini.text if ini is not None and ini.text else ''
                autores.append((sob.text + ' ' + inic).strip())
                autores_est.append({'sn': sob.text, 'in': inic})
        doi = ''
        for aid in art.findall('.//ArticleIdList/ArticleId'):
            if aid.get('IdType') == 'doi' and aid.text:
                doi = aid.text.strip()
        pmid_el = art.find('.//PMID')
        pmid = pmid_el.text if pmid_el is not None else ''
        kws = [_limpar(k.text) for k in art.findall('.//KeywordList/Keyword') if k.text]
        vol = art.findtext('.//JournalIssue/Volume') or ''
        num = art.findtext('.//JournalIssue/Issue') or ''
        pag = art.findtext('.//Pagination/MedlinePgn') or ''
        reg = {'fonte': 'PubMed', 'doi': doi, 'titulo': titulo, 'autores': autores,
               'autores_est': autores_est, 'ano': ano, 'revista': revista, 'resumo': resumo,
               'volume': vol, 'numero': num, 'paginas': pag,
               'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/' if pmid else '',
               'keywords': kws}
        if titulo:
            out.append(reg)
    return out


# ============================ Europe PMC ============================
def buscar_europepmc(query, limite=25) -> list:
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    try:
        r = requests.get(url, timeout=TIMEOUT, params={
            "query": query, "format": "json", "resultType": "core", "pageSize": limite})
        r.raise_for_status()
        res = r.json().get("resultList", {}).get("result", [])
    except Exception as e:
        ULTIMO_ERRO['europepmc'] = str(e)
        return []
    out = []
    for it in res:
        autores = []
        autores_est = []
        for a in (it.get('authorList', {}) or {}).get('author', []) or []:
            sn = a.get('lastName') or ''
            inic = a.get('initials') or ''
            if not sn:
                fn = a.get('fullName') or ''
                partes = fn.split()
                if partes:
                    sn = partes[0]; inic = inic or ''.join(partes[1:])
            nome = a.get('fullName') or (sn + ' ' + inic).strip()
            if nome:
                autores.append(nome)
            if sn:
                autores_est.append({'sn': sn, 'in': inic})
        kw = (it.get('keywordList', {}) or {}).get('keyword', []) or []
        doi = it.get('doi', '') or ''
        pmid = it.get('pmid', '')
        url_art = ''
        if doi:
            url_art = 'https://doi.org/' + doi
        elif pmid:
            url_art = f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/'
        ji = it.get('journalInfo', {}) or {}
        reg = {'fonte': 'Europe PMC', 'doi': doi, 'titulo': _limpar(it.get('title', '')),
               'autores': autores, 'autores_est': autores_est, 'ano': str(it.get('pubYear', '') or ''),
               'revista': (ji.get('journal', {}) or {}).get('title', '') or it.get('journalTitle', ''),
               'volume': str(ji.get('volume', '') or ''), 'numero': str(ji.get('issue', '') or ''),
               'paginas': it.get('pageInfo', '') or '',
               'resumo': _limpar(it.get('abstractText', '')), 'url': url_art,
               'keywords': [_limpar(k) for k in kw]}
        if reg['titulo']:
            out.append(reg)
    return out


# ============================ Crossref ============================
def buscar_crossref(query, limite=25) -> list:
    url = "https://api.crossref.org/works"
    try:
        r = requests.get(url, timeout=TIMEOUT, params={
            "query": query, "rows": limite, "mailto": EMAIL_CONTATO,
            "select": "DOI,title,author,issued,container-title,abstract,URL,subject,volume,issue,page"})
        r.raise_for_status()
        itens = r.json().get("message", {}).get("items", [])
    except Exception as e:
        ULTIMO_ERRO['crossref'] = str(e)
        return []
    out = []
    for it in itens:
        titulo = _limpar(' '.join(it.get('title', []) or []))
        if not titulo:
            continue
        autores = []
        autores_est = []
        for a in it.get('author', []) or []:
            fam = a.get('family', '') or ''
            giv = a.get('given', '') or ''
            nome = (giv + ' ' + fam).strip()
            if nome:
                autores.append(nome)
            if fam:
                inic = ''.join(w[0] for w in giv.replace('.', ' ').split() if w)
                autores_est.append({'sn': fam, 'in': inic})
        ano = ''
        try:
            ano = str(it['issued']['date-parts'][0][0])
        except Exception:
            ano = ''
        reg = {'fonte': 'Crossref', 'doi': it.get('DOI', '') or '', 'titulo': titulo,
               'autores': autores, 'autores_est': autores_est, 'ano': ano,
               'revista': _limpar(' '.join(it.get('container-title', []) or [])),
               'volume': str(it.get('volume', '') or ''), 'numero': str(it.get('issue', '') or ''),
               'paginas': it.get('page', '') or '',
               'resumo': _limpar(it.get('abstract', '')), 'url': it.get('URL', '') or '',
               'keywords': it.get('subject', []) or []}
        out.append(reg)
    return out


# ============================ Semantic Scholar ============================
def buscar_semanticscholar(query, limite=25) -> list:
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    campos = "title,abstract,year,authors,externalIds,venue,url"
    try:
        r = requests.get(url, timeout=TIMEOUT, params={
            "query": query, "limit": min(limite, 100), "fields": campos})
        if r.status_code == 429:
            ULTIMO_ERRO['semanticscholar'] = 'limite de requisicoes (429) — tente de novo em instantes'
            return []
        r.raise_for_status()
        dados = r.json().get("data", []) or []
    except Exception as e:
        ULTIMO_ERRO['semanticscholar'] = str(e)
        return []
    out = []
    for it in dados:
        autores = [a.get('name', '') for a in (it.get('authors') or []) if a.get('name')]
        autores_est = []
        for nome in autores:
            partes = nome.split()
            if len(partes) >= 2:
                autores_est.append({'sn': partes[-1], 'in': ''.join(w[0] for w in partes[:-1] if w)})
            elif partes:
                autores_est.append({'sn': partes[0], 'in': ''})
        doi = ((it.get('externalIds') or {}).get('DOI') or '')
        reg = {'fonte': 'Semantic Scholar', 'doi': doi, 'titulo': _limpar(it.get('title', '')),
               'autores': autores, 'autores_est': autores_est, 'ano': str(it.get('year', '') or ''),
               'revista': it.get('venue', '') or '', 'resumo': _limpar(it.get('abstract', '')),
               'volume': '', 'numero': '', 'paginas': '',
               'url': it.get('url', '') or (('https://doi.org/' + doi) if doi else ''),
               'keywords': []}
        if reg['titulo']:
            out.append(reg)
    return out


# ============================ LILACS / BVS ============================
def buscar_lilacs(query, limite=25) -> list:
    """Literatura latino-americana em saude (BVS/BIREME). Usa o backend de busca
    do portal da BVS (iAHx). Best-effort: se a API mudar/limitar, retorna [] com
    aviso, sem derrubar o resto."""
    url = "https://pesquisa.bvsalud.org/portal/"
    try:
        r = requests.get(url, timeout=TIMEOUT, params={
            "q": query, "lang": "pt", "output": "json", "count": limite,
            "index": "tw", "format": "json"})
        r.raise_for_status()
        dados = r.json()
    except Exception as e:
        ULTIMO_ERRO['lilacs'] = str(e)
        return []
    # o iAHx devolve {'diaServerResponse':[{'response':{'docs':[...]}}]} ou similar
    docs = []
    try:
        resp = dados.get('diaServerResponse') or []
        if resp:
            docs = resp[0].get('response', {}).get('docs', []) or []
        else:
            docs = dados.get('response', {}).get('docs', []) or []
    except Exception:
        docs = []
    out = []
    for d in docs:
        titulo = _limpar(_primeiro(d.get('ti') or d.get('title')))
        if not titulo:
            continue
        autores = d.get('au') or d.get('authors') or []
        if isinstance(autores, str):
            autores = [autores]
        doi = _primeiro(d.get('doi')) or ''
        ano = str(_primeiro(d.get('da') or d.get('publication_year') or ''))[:4]
        out.append({'fonte': 'LILACS', 'doi': doi, 'titulo': titulo,
                    'autores': [str(a) for a in autores][:20], 'ano': ano,
                    'revista': _limpar(_primeiro(d.get('fo') or d.get('journal'))),
                    'resumo': _limpar(_primeiro(d.get('ab') or d.get('abstract'))),
                    'url': ('https://doi.org/' + doi) if doi else _primeiro(d.get('ur')) or '',
                    'keywords': []})
    return out


def _primeiro(v):
    if isinstance(v, list):
        return v[0] if v else ''
    return v or ''


# ============================ DESCRITORES (DeCS / MeSH) ============================
def _mesh_lookup(termo) -> list:
    """Descritores MeSH oficiais (NLM) que casam com o termo. Confiavel e gratis."""
    url = "https://id.nlm.nih.gov/mesh/lookup/descriptor"
    r = requests.get(url, timeout=15, params={"label": termo, "match": "contains", "limit": 8})
    r.raise_for_status()
    return [d.get("label", "") for d in r.json() if d.get("label")]


def expandir_descritores(termo) -> dict:
    """Expande um termo livre nos descritores controlados. MeSH (EN) via NLM é
    confiavel; DeCS (PT/ES) fica para a etapa 2 (API da BIREME a confirmar).
    Retorna {'termo', 'mesh':[...], 'aviso':''}."""
    mesh = []
    try:
        mesh = _mesh_lookup(termo)
    except Exception as e:
        ULTIMO_ERRO['mesh'] = str(e)
    return {'termo': termo, 'mesh': mesh}


BASES = {
    'pubmed': buscar_pubmed,
    'lilacs': buscar_lilacs,
    'europepmc': buscar_europepmc,
    'crossref': buscar_crossref,
    'semanticscholar': buscar_semanticscholar,
}
NOMES_BASES = {'pubmed': 'PubMed', 'lilacs': 'LILACS / BVS', 'europepmc': 'Europe PMC',
               'crossref': 'Crossref', 'semanticscholar': 'Semantic Scholar'}


def buscar_todas(query_por_base: dict, limite=25) -> dict:
    """query_por_base: {'pubmed': 'string', ...}. Roda as bases pedidas, deduplica
    (por DOI ou titulo normalizado) e marca `dup=1` a partir da 2a ocorrencia.
    Retorna {'registros': [...], 'por_base': {base: n_brutos}, 'erros': {...}}."""
    ULTIMO_ERRO.clear()
    vistos = set()
    registros = []
    por_base = {}
    for base, query in query_por_base.items():
        if not query or base not in BASES:
            continue
        brutos = BASES[base](query, limite)
        por_base[base] = len(brutos)
        for reg in brutos:
            ch = chave_dedup(reg)
            reg['chave_dedup'] = ch
            reg['dup'] = 1 if ch in vistos else 0
            vistos.add(ch)
            registros.append(reg)
        time.sleep(0.34)
    return {'registros': registros, 'por_base': por_base, 'erros': dict(ULTIMO_ERRO)}


if __name__ == '__main__':
    # smoke test rapido contra as APIs reais
    q = "clozapine AND agranulocytosis monitoring"
    qs = {
        'pubmed': q,
        'europepmc': q,
        'crossref': "clozapine agranulocytosis monitoring",
        'semanticscholar': "clozapine agranulocytosis monitoring",
    }
    res = buscar_todas(qs, limite=5)
    print("por_base (brutos):", res['por_base'])
    print("erros:", res['erros'])
    print("total registros:", len(res['registros']),
          "| unicos:", sum(1 for r in res['registros'] if not r['dup']))
    for r in res['registros'][:6]:
        print(f"  [{r['fonte']}] {r['ano']} | doi={r['doi'][:40]!r} dup={r['dup']}")
        print(f"      {r['titulo'][:90]}")
        print(f"      resumo: {len(r['resumo'])} chars | autores: {len(r['autores'])}")
