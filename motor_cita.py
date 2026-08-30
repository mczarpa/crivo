# -*- coding: utf-8 -*-
"""
Formata as referencias dos artigos INCLUIDOS em estilos de publicacao:
Vancouver, ABNT (NBR 6023) e APA (7a ed.). Usa so os metadados reais do artigo
(autores estruturados, ano, titulo, revista, volume, numero, paginas, DOI) —
nada inventado. Campos ausentes sao simplesmente omitidos.
"""

ESTILOS = ['vancouver', 'abnt', 'apa']
NOMES = {'vancouver': 'Vancouver', 'abnt': 'ABNT (NBR 6023)', 'apa': 'APA 7'}


def _letras(inic) -> list:
    return [c.upper() for c in (inic or '') if c.isalpha()]


def _autores_vancouver(autores) -> str:
    """Sobrenome IN, ... ; ate 6 autores, depois 'et al.'"""
    partes = []
    for a in autores[:6]:
        sn = (a.get('sn') or '').strip()
        ini = ''.join(_letras(a.get('in')))
        partes.append((sn + ' ' + ini).strip())
    txt = ', '.join(p for p in partes if p)
    if len(autores) > 6:
        txt += ', et al.'
    return txt


def _autores_abnt(autores) -> str:
    """SOBRENOME, I. I.; ... ; mais de 3 -> primeiro + et al."""
    def um(a):
        sn = (a.get('sn') or '').strip().upper()
        ini = ' '.join(l + '.' for l in _letras(a.get('in')))
        return (sn + ', ' + ini).strip().rstrip(',') if ini else sn
    if not autores:
        return ''
    if len(autores) > 3:
        return um(autores[0]) + ' et al.'
    return '; '.join(um(a) for a in autores)


def _autores_apa(autores) -> str:
    """Sobrenome, I. I., & Sobrenome, I. I. ; ate 20."""
    def um(a):
        sn = (a.get('sn') or '').strip()
        ini = ' '.join(l + '.' for l in _letras(a.get('in')))
        return (sn + ', ' + ini).strip().rstrip(',') if ini else sn
    lista = [um(a) for a in autores[:20] if a.get('sn')]
    if not lista:
        return ''
    if len(lista) == 1:
        return lista[0]
    return ', '.join(lista[:-1]) + ', & ' + lista[-1]


def _tem(v) -> bool:
    return bool(str(v or '').strip())


def formatar(reg, estilo='vancouver') -> str:
    estilo = (estilo or 'vancouver').lower()
    autores = reg.get('autores_est') or []
    # fallback: se nao veio estruturado, usa os nomes crus como sobrenome
    if not autores and reg.get('autores'):
        autores = [{'sn': n, 'in': ''} for n in reg['autores']]
    titulo = (reg.get('titulo') or '').strip().rstrip('.')
    rev = (reg.get('revista') or '').strip()
    ano = str(reg.get('ano') or '').strip()
    vol = str(reg.get('volume') or '').strip()
    num = str(reg.get('numero') or '').strip()
    pag = str(reg.get('paginas') or '').strip()
    doi = (reg.get('doi') or '').strip()

    if estilo == 'abnt':
        aut = _autores_abnt(autores)
        s = ((aut.rstrip('.') + '. ') if aut else '') + titulo + '. '
        if rev:
            s += rev
            det = []
            if vol: det.append('v. ' + vol)
            if num: det.append('n. ' + num)
            if pag: det.append('p. ' + pag)
            if ano: det.append(ano)
            s += ((', ' + ', '.join(det)) if det else '') + '. '
        elif ano:
            s += ano + '. '
        if doi:
            s += 'DOI: ' + doi + '.'
        return s.strip()

    if estilo == 'apa':
        aut = _autores_apa(autores)
        s = (aut + ' ' if aut else '')
        s += ('(' + ano + '). ') if ano else ''
        s += titulo + '. '
        if rev:
            s += rev
            if vol:
                s += ', ' + vol + (('(' + num + ')') if num else '')
            if pag:
                s += ', ' + pag
            s += '. '
        if doi:
            s += 'https://doi.org/' + doi
        return s.strip()

    # vancouver (padrao)
    aut = _autores_vancouver(autores)
    s = (aut + '. ' if aut else '') + titulo + '. '
    if rev:
        s += rev + '. '
    if ano:
        s += ano
        if vol:
            s += ';' + vol + (('(' + num + ')') if num else '')
        if pag:
            s += ':' + pag
        s += '. '
    if doi:
        s += 'doi:' + doi
    return s.strip()


def formatar_lista(refs, estilo='vancouver', numerar=True) -> str:
    itens = []
    for i, r in enumerate(refs, 1):
        txt = formatar(r, estilo)
        itens.append((f'{i}. ' if numerar else '') + txt)
    return '\n\n'.join(itens)


if __name__ == '__main__':
    demo = {'autores_est': [{'sn': 'Mijovic', 'in': 'A'}, {'sn': 'MacCabe', 'in': 'JH'}],
            'titulo': 'Clozapine-induced agranulocytosis',
            'revista': 'Annals of Hematology', 'ano': '2020',
            'volume': '99', 'numero': '11', 'paginas': '2477-2482',
            'doi': '10.1007/s00277-020-04215-y'}
    for e in ESTILOS:
        print(f'--- {NOMES[e]} ---')
        print(formatar(demo, e))
        print()
