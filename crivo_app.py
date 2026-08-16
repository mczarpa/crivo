# -*- coding: utf-8 -*-
"""
Crivo — revisao de literatura assistida (Streamlit local, porta 8513).

Pipeline: Pergunta (PICO) -> Busca real (4 bases gratuitas) -> Triagem por IA
-> Ficha de extracao -> Manuscrito ancorado -> Painel/PRISMA -> Exportar.
IA 100% local (Ollama). Buscas reais (PubMed, Europe PMC, Crossref, S. Scholar).
"""
import io
import json

import streamlit as st

import crivo_db as db
import crivo_busca as busca
import crivo_ia as ia

st.set_page_config(page_title="Crivo", page_icon=":material/plagiarism:", layout="wide")

db.inicializar_banco()

SECOES_MS = [('introducao', 'Introdução'), ('metodos', 'Métodos'),
             ('resultados', 'Resultados'), ('discussao', 'Discussão'),
             ('conclusao', 'Conclusão')]
CRIT_EXC_PADRAO = ['Fora do escopo/tema', 'População não elegível',
                   'Desenho de estudo inadequado', 'Sem texto completo',
                   'Duplicata', 'Idioma', 'Desfecho não avaliado']


# ---------------- helpers de estado ----------------
def modelo_atual():
    return db.get_config('modelo_ollama', ia.MODELO_PADRAO)


def projeto_ativo():
    pid = st.session_state.get('projeto_id')
    if pid:
        p = db.get_projeto(pid)
        if p:
            return p
    projs = db.listar_projetos()
    if projs:
        st.session_state.projeto_id = projs[0]['id']
        return projs[0]
    return None


def linhas(txt):
    return [x.strip() for x in (txt or '').splitlines() if x.strip()]


# ==================== SIDEBAR ====================
with st.sidebar:
    st.title(":material/plagiarism: Crivo")
    st.caption("Revisão de literatura assistida")

    projs = db.listar_projetos()
    nomes = {p['id']: p['nome'] for p in projs}
    if projs:
        ids = list(nomes)
        atual = st.session_state.get('projeto_id', ids[0])
        idx = ids.index(atual) if atual in ids else 0
        escolhido = st.selectbox("Projeto (revisão)", ids, index=idx,
                                 format_func=lambda i: nomes[i])
        st.session_state.projeto_id = escolhido
    else:
        st.info("Crie sua primeira revisão abaixo.")

    with st.popover("Nova revisão", width="stretch"):
        novo_nome = st.text_input("Nome da revisão", key="novo_nome")
        if st.button("Criar", type="primary"):
            if novo_nome.strip():
                pid = db.criar_projeto(novo_nome.strip())
                db.atualizar_projeto(pid, criterios_exc=CRIT_EXC_PADRAO)
                st.session_state.projeto_id = pid
                st.rerun()

    st.divider()
    st.subheader("Motor de IA")
    prov, mod_def, ok, info = ia.provedor_ativo()
    if prov == 'groq':
        st.success("IA na nuvem (Groq)")
        st.caption(info)
    elif ok:
        st.success("Ollama local conectado")
        st.caption(f"Modelos: {info}")
    else:
        st.error("Sem IA: rode o Ollama, ou configure a chave GROQ_API_KEY.")
        st.caption(info)
    _chave_modelo = 'modelo_' + prov
    modelo = st.text_input("Modelo", value=db.get_config(_chave_modelo, mod_def),
                           help="Groq: llama-3.3-70b-versatile · Ollama: qwen2.5:3b/7b/14b")
    if modelo != db.get_config(_chave_modelo, mod_def):
        db.set_config(_chave_modelo, modelo)

    with st.expander("E-mail para as APIs (boa prática)"):
        email = st.text_input("E-mail de contato", value=db.get_config('email', busca.EMAIL_CONTATO),
                              label_visibility="collapsed")
        busca.EMAIL_CONTATO = email
        db.set_config('email', email)


proj = projeto_ativo()
if not proj:
    st.title("Crivo")
    st.info("Crie uma revisão na barra lateral para começar.")
    st.stop()

pico = json.loads(proj.get('pico') or '{}')
crit_inc = json.loads(proj.get('criterios_inc') or '[]')
crit_exc = json.loads(proj.get('criterios_exc') or '[]')
buscas = json.loads(proj.get('buscas') or '{}')
manuscrito = json.loads(proj.get('manuscrito') or '{}')
cont = db.contar_por_status(proj['id'])

st.title(f":material/plagiarism: {proj['nome']}")

aba_pergunta, aba_busca, aba_triagem, aba_ficha, aba_ms, aba_painel, aba_export = st.tabs(
    ["Pergunta", "Busca", f"Triagem ({cont.get('total',0)})", "Ficha",
     "Manuscrito", "Painel", "Exportar"])


# ==================== 1. PERGUNTA / PICO ====================
with aba_pergunta:
    st.subheader("Pergunta da revisão")
    tema = st.text_input("Tema", value=proj.get('tema', ''))
    desc = st.text_area("Descreva o que você quer revisar", value=proj.get('descricao', ''),
                        height=110, placeholder="Ex.: eficácia e segurança do monitoramento "
                        "hematológico em adultos usando clozapina...")
    c1, c2 = st.columns([1, 1])
    if c1.button(":material/auto_awesome: Estruturar PICO com IA", type="primary"):
        with st.spinner("Pensando (modelo local)..."):
            pico = ia.estruturar_pico(tema, desc, modelo)
            db.atualizar_projeto(proj['id'], tema=tema, descricao=desc, pico=pico)
        st.rerun()
    if c2.button(":material/save: Salvar"):
        db.atualizar_projeto(proj['id'], tema=tema, descricao=desc)
        st.toast("Salvo")

    st.divider()
    st.markdown("**PICO** (edite à vontade)")
    g = st.columns(2)
    campos = [('populacao', 'População'), ('intervencao', 'Intervenção'),
              ('comparacao', 'Comparação'), ('desfecho', 'Desfecho'),
              ('tipo_estudo', 'Tipo de estudo'), ('idioma', 'Idioma'), ('periodo', 'Período')]
    novo_pico = {}
    for i, (k, lbl) in enumerate(campos):
        novo_pico[k] = g[i % 2].text_input(lbl, value=pico.get(k, ''), key=f"pico_{k}")

    st.markdown("**Critérios** (um por linha)")
    ci, ce = st.columns(2)
    inc_txt = ci.text_area("Inclusão", value="\n".join(crit_inc), height=140)
    exc_txt = ce.text_area("Exclusão", value="\n".join(crit_exc), height=140)
    if st.button(":material/save: Salvar PICO e critérios", type="primary"):
        db.atualizar_projeto(proj['id'], pico=novo_pico,
                             criterios_inc=linhas(inc_txt), criterios_exc=linhas(exc_txt))
        st.toast("PICO e critérios salvos")
        st.rerun()


# ==================== 2. BUSCA ====================
with aba_busca:
    st.subheader("Busca nas bases")
    st.caption("Gera as strings com IA, você edita, e o Crivo busca de verdade nas 4 bases gratuitas.")
    if st.button(":material/auto_awesome: Montar strings de busca com IA"):
        with st.spinner("Montando strings (modelo local)..."):
            buscas = ia.montar_buscas(pico, proj.get('tema', ''), list(busca.NOMES_BASES), modelo)
            db.atualizar_projeto(proj['id'], buscas=buscas)
        st.rerun()

    sel = {}
    novas = {}
    for chave, nome in busca.NOMES_BASES.items():
        c = st.columns([0.28, 3])
        sel[chave] = c[0].checkbox(nome, value=True, key=f"sel_{chave}")
        novas[chave] = c[1].text_input(nome, value=buscas.get(chave, proj.get('tema', '')),
                                       key=f"q_{chave}", label_visibility="collapsed")
    limite = st.slider("Máx. resultados por base", 5, 100, 25, step=5)

    cb1, cb2 = st.columns([1, 1])
    if cb1.button(":material/travel_explore: Buscar agora", type="primary"):
        db.atualizar_projeto(proj['id'], buscas=novas)
        alvo = {k: novas[k] for k in busca.NOMES_BASES if sel.get(k) and novas.get(k)}
        if not alvo:
            st.warning("Selecione ao menos uma base com string preenchida.")
        else:
            with st.spinner("Buscando nas bases (dados reais)..."):
                res = busca.buscar_todas(alvo, limite=limite)
                novos, dups_ban = db.inserir_referencias(proj['id'], res['registros'])
            st.success(f"{novos} referência(s) novas gravadas · "
                       f"{dups_ban} já existiam no projeto.")
            st.write("Brutos por base:", res['por_base'])
            if res['erros']:
                st.warning("Avisos: " + "; ".join(f"{k}: {v}" for k, v in res['erros'].items()))
            st.rerun()
    cb2.caption(f"No projeto: **{cont.get('total',0)}** referências "
                f"({cont.get('duplicatas',0)} duplicatas marcadas).")


# ==================== 3. TRIAGEM ====================
with aba_triagem:
    st.subheader("Triagem título/resumo")
    refs = db.listar_referencias(proj['id'])
    ca, cb, cc = st.columns([1.4, 1, 1])
    filtro = ca.segmented_control("Filtrar", ["Todas", "pendente", "incluir", "excluir", "talvez"],
                                  default="Todas", key="filtro_triagem")
    busca_txt = cb.text_input("Buscar no título", key="busca_titulo",
                             placeholder="filtrar por palavra...")
    if cc.button(":material/auto_awesome: Triar pendentes com IA", type="primary"):
        pend = [r for r in refs if r['status'] == 'pendente' and not r['dup']]
        if not pend:
            st.toast("Nada pendente para triar.")
        else:
            barra = st.progress(0.0, "Triando...")
            for i, r in enumerate(pend, 1):
                try:
                    d = ia.triar_referencia(r, crit_inc, crit_exc, pico, modelo)
                    db.atualizar_referencia(r['id'], status=d['decisao'],
                                            motivo=d['motivo'], criterio=d['criterio'])
                except Exception as e:
                    db.atualizar_referencia(r['id'], motivo=f'erro IA: {e}')
                barra.progress(i / len(pend), f"Triando {i}/{len(pend)}")
            st.rerun()

    vis = refs
    if filtro and filtro != "Todas":
        vis = [r for r in vis if r['status'] == filtro]
    if busca_txt:
        vis = [r for r in vis if busca_txt.lower() in r['titulo'].lower()]

    st.caption(f"{len(vis)} referência(s)")
    CORES = {'incluir': 'green', 'excluir': 'red', 'talvez': 'orange', 'pendente': 'gray'}
    for r in vis[:200]:
        with st.container(border=True):
            tag = f":{CORES.get(r['status'],'gray')}[{r['status']}]"
            dupflag = " · :gray[duplicata]" if r['dup'] else ""
            st.markdown(f"**{r['titulo']}** {dupflag}")
            meta = " · ".join(x for x in [", ".join(r['autores'][:3]), str(r['ano']),
                                          r['revista'], r['fonte']] if x)
            st.caption(meta)
            if r['resumo']:
                with st.expander("Resumo"):
                    st.write(r['resumo'])
            cols = st.columns([0.9, 0.9, 0.9, 3])
            if cols[0].button("Incluir", key=f"inc_{r['id']}"):
                db.atualizar_referencia(r['id'], status='incluir'); st.rerun()
            if cols[1].button("Excluir", key=f"exc_{r['id']}"):
                db.atualizar_referencia(r['id'], status='excluir'); st.rerun()
            if cols[2].button("Talvez", key=f"myb_{r['id']}"):
                db.atualizar_referencia(r['id'], status='talvez'); st.rerun()
            estado = f"{tag}"
            if r['motivo']:
                estado += f" — {r['motivo']}"
            cols[3].markdown(estado)


# ==================== 4. FICHA ====================
with aba_ficha:
    st.subheader("Ficha de extração")
    inc = db.listar_referencias(proj['id'], status='incluir')
    st.caption(f"{len(inc)} artigo(s) incluído(s).")
    if inc and st.button(":material/auto_awesome: Preencher fichas vazias com IA", type="primary"):
        vazias = [r for r in inc if not r['ficha']]
        barra = st.progress(0.0, "Extraindo...")
        for i, r in enumerate(vazias, 1):
            try:
                db.atualizar_referencia(r['id'], ficha=ia.extrair_ficha(r, modelo))
            except Exception as e:
                st.warning(f"Falha em {r['titulo'][:40]}: {e}")
            barra.progress(i / max(len(vazias), 1), f"Ficha {i}/{len(vazias)}")
        st.rerun()

    for r in inc:
        with st.expander(f"{r['titulo'][:90]}  ·  {r['ano']}"):
            f = r['ficha'] or {}
            nova = {}
            for c in ia.CAMPOS_FICHA:
                nova[c] = st.text_area(c.capitalize(), value=f.get(c, ''),
                                       key=f"ficha_{r['id']}_{c}", height=68)
            if st.button("Salvar ficha", key=f"savef_{r['id']}"):
                db.atualizar_referencia(r['id'], ficha=nova); st.toast("Ficha salva")


# ==================== 5. MANUSCRITO ====================
with aba_ms:
    st.subheader("Manuscrito")
    st.caption("O rascunho é ancorado: a IA só usa os artigos incluídos e cita por [n]. "
               "Nada de referência inventada.")
    inc = db.listar_referencias(proj['id'], status='incluir')
    st.info(f"{len(inc)} artigo(s) incluído(s) servem de base para o texto.")
    mudou = False
    for chave, titulo in SECOES_MS:
        with st.container(border=True):
            texto = manuscrito.get(chave, '')
            cabec = st.columns([3, 1])
            cabec[0].markdown(f"**{titulo}**")
            palavras = len((texto or '').split())
            cabec[1].caption(f"{palavras} palavras")
            if st.button(f":material/auto_awesome: Rascunhar {titulo} com IA", key=f"draft_{chave}"):
                if not inc:
                    st.warning("Inclua artigos antes de rascunhar.")
                else:
                    with st.spinner(f"Escrevendo {titulo} (modelo local)..."):
                        texto = ia.rascunhar_secao(titulo, pico, inc, modelo=modelo)
                        manuscrito[chave] = texto
                        db.atualizar_projeto(proj['id'], manuscrito=manuscrito)
                    st.rerun()
            novo = st.text_area(titulo, value=texto, height=200, key=f"ms_{chave}",
                               label_visibility="collapsed")
            if novo != texto:
                manuscrito[chave] = novo
                mudou = True
    if mudou and st.button(":material/save: Salvar manuscrito", type="primary"):
        db.atualizar_projeto(proj['id'], manuscrito=manuscrito)
        st.toast("Manuscrito salvo")


# ==================== 6. PAINEL / PRISMA ====================
with aba_painel:
    st.subheader("Painel")
    cont = db.contar_por_status(proj['id'])
    total = cont.get('total', 0)
    dup = cont.get('duplicatas', 0)
    inc_n = cont.get('incluir', 0)
    exc_n = cont.get('excluir', 0)
    myb_n = cont.get('talvez', 0)
    pend_n = cont.get('pendente', 0)
    m = st.columns(5)
    m[0].metric("Encontradas", total)
    m[1].metric("Duplicatas", dup)
    m[2].metric("Incluídas", inc_n)
    m[3].metric("Excluídas", exc_n)
    m[4].metric("Pendentes", pend_n)

    st.markdown("**Fluxo PRISMA (simplificado)**")
    triadas = total - dup
    st.markdown(f"""
- Registros identificados nas bases: **{total}**
- Removidas duplicatas: **{dup}**
- Registros triados (título/resumo): **{triadas}**
- Excluídas na triagem: **{exc_n}**  ·  Em dúvida: **{myb_n}**
- **Incluídas na síntese: {inc_n}**
""")
    if triadas:
        st.progress(inc_n / triadas, f"{inc_n} incluídas de {triadas} triadas")


# ==================== 7. EXPORTAR ====================
with aba_export:
    st.subheader("Exportar")
    inc = db.listar_referencias(proj['id'], status='incluir')

    # RIS dos incluidos
    def gerar_ris(refs):
        buf = io.StringIO()
        for r in refs:
            buf.write("TY  - JOUR\n")
            buf.write(f"TI  - {r['titulo']}\n")
            for a in r['autores']:
                buf.write(f"AU  - {a}\n")
            if r['ano']:
                buf.write(f"PY  - {r['ano']}\n")
            if r['revista']:
                buf.write(f"JO  - {r['revista']}\n")
            if r['resumo']:
                buf.write(f"AB  - {r['resumo']}\n")
            if r['doi']:
                buf.write(f"DO  - {r['doi']}\n")
            if r['url']:
                buf.write(f"UR  - {r['url']}\n")
            buf.write("ER  - \n\n")
        return buf.getvalue()

    def gerar_md():
        out = f"# {proj['nome']}\n\n"
        for chave, titulo in SECOES_MS:
            t = manuscrito.get(chave, '').strip()
            if t:
                out += f"## {titulo}\n\n{t}\n\n"
        if inc:
            out += "## Referências\n\n"
            for i, r in enumerate(inc, 1):
                aut = ", ".join(r['autores'][:6])
                out += f"{i}. {aut} ({r['ano']}). {r['titulo']}. *{r['revista']}*. " \
                       f"{('doi:'+r['doi']) if r['doi'] else ''}\n"
        return out

    c = st.columns(3)
    c[0].download_button(":material/download: RIS (incluídos)", gerar_ris(inc),
                         file_name="crivo_incluidos.ris", mime="application/x-research-info-systems",
                         disabled=not inc, width="stretch")
    import csv as _csv
    sb = io.StringIO()
    w = _csv.writer(sb)
    w.writerow(['titulo', 'autores', 'ano', 'revista', 'doi', 'url'])
    for r in inc:
        w.writerow([r['titulo'], "; ".join(r['autores']), r['ano'], r['revista'], r['doi'], r['url']])
    c[1].download_button(":material/download: CSV (incluídos)", sb.getvalue(),
                         file_name="crivo_incluidos.csv", mime="text/csv",
                         disabled=not inc, width="stretch")
    c[2].download_button(":material/download: Manuscrito (.md)", gerar_md(),
                         file_name="crivo_manuscrito.md", mime="text/markdown", width="stretch")

    st.divider()
    st.markdown("**Backup do projeto** — no site, o disco é temporário; baixe o backup "
                "para não perder o trabalho e restaure quando voltar.")
    cbk = st.columns(2)
    cbk[0].download_button(":material/save: Baixar backup (JSON)",
                           json.dumps(db.exportar_projeto(proj['id']), ensure_ascii=False, indent=2),
                           file_name=f"crivo_backup_{proj['nome']}.json",
                           mime="application/json", width="stretch")
    up = cbk[1].file_uploader("Restaurar de um backup (.json)", type=['json'])
    if up is not None and st.button(":material/restore: Restaurar como novo projeto", type="primary"):
        try:
            novo = db.importar_projeto(json.load(up))
            st.session_state.projeto_id = novo
            st.success("Backup restaurado.")
            st.rerun()
        except Exception as e:
            st.error(f"Falha ao restaurar: {e}")
