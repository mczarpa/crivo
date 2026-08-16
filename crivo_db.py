# -*- coding: utf-8 -*-
"""
Banco do Crivo (revisao de literatura assistida). SQLite proprio, `crivo.db`,
na pasta do projeto. Guarda projetos de revisao, referencias (com decisao de
triagem e ficha de extracao), manuscrito e configuracoes.

So persistencia — a busca fica em crivo_busca.py e a IA local em crivo_ia.py.
"""
import json
import sqlite3
import time
from pathlib import Path

try:
    from project_paths import PASTA_PROJETO
    BANCO_CRIVO = str(Path(PASTA_PROJETO) / "crivo.db")
except Exception:
    BANCO_CRIVO = str(Path(__file__).resolve().parent / "crivo.db")


def _conn():
    con = sqlite3.connect(BANCO_CRIVO)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def inicializar_banco() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS projetos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                tema TEXT DEFAULT '',
                descricao TEXT DEFAULT '',
                pico TEXT DEFAULT '{}',           -- json: populacao/intervencao/comparacao/desfecho/tipo/idioma/periodo
                criterios_inc TEXT DEFAULT '[]',  -- json list
                criterios_exc TEXT DEFAULT '[]',  -- json list
                buscas TEXT DEFAULT '{}',         -- json: string de busca por base
                manuscrito TEXT DEFAULT '{}',     -- json: secao -> texto
                criado_em REAL DEFAULT 0
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS referencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                projeto_id INTEGER NOT NULL,
                fonte TEXT DEFAULT '',
                doi TEXT DEFAULT '',
                titulo TEXT DEFAULT '',
                autores TEXT DEFAULT '[]',        -- json list
                ano TEXT DEFAULT '',
                revista TEXT DEFAULT '',
                resumo TEXT DEFAULT '',
                url TEXT DEFAULT '',
                keywords TEXT DEFAULT '[]',       -- json list
                dup INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pendente',   -- pendente/incluir/excluir/talvez
                motivo TEXT DEFAULT '',
                criterio TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                nota TEXT DEFAULT '',
                estrela INTEGER DEFAULT 0,
                ficha TEXT DEFAULT '{}',          -- json: campos da ficha de extracao
                full_text TEXT DEFAULT '',
                chave_dedup TEXT DEFAULT '',
                criado_em REAL DEFAULT 0,
                UNIQUE(projeto_id, chave_dedup)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS config (
                chave TEXT PRIMARY KEY,
                valor TEXT DEFAULT ''
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS ix_ref_proj ON referencias(projeto_id)")


# ---------------- config ----------------
def get_config(chave, padrao=''):
    with _conn() as con:
        r = con.execute("SELECT valor FROM config WHERE chave=?", (chave,)).fetchone()
    return r['valor'] if r else padrao


def set_config(chave, valor):
    with _conn() as con:
        con.execute("INSERT INTO config(chave,valor) VALUES(?,?) "
                    "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (chave, str(valor)))


# ---------------- projetos ----------------
def criar_projeto(nome, tema='', descricao='') -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO projetos(nome,tema,descricao,criado_em) VALUES(?,?,?,?)",
            (nome, tema, descricao, time.time()))
        return cur.lastrowid


def listar_projetos() -> list:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM projetos ORDER BY criado_em DESC").fetchall()]


def get_projeto(projeto_id) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM projetos WHERE id=?", (projeto_id,)).fetchone()
    return dict(r) if r else None


def atualizar_projeto(projeto_id, **campos) -> None:
    if not campos:
        return
    # campos json sao serializados automaticamente se vier dict/list
    for k, v in list(campos.items()):
        if isinstance(v, (dict, list)):
            campos[k] = json.dumps(v, ensure_ascii=False)
    sets = ", ".join(f"{k}=?" for k in campos)
    with _conn() as con:
        con.execute(f"UPDATE projetos SET {sets} WHERE id=?", (*campos.values(), projeto_id))


def excluir_projeto(projeto_id) -> None:
    with _conn() as con:
        con.execute("DELETE FROM referencias WHERE projeto_id=?", (projeto_id,))
        con.execute("DELETE FROM projetos WHERE id=?", (projeto_id,))


# ---------------- referencias ----------------
def inserir_referencias(projeto_id, registros: list) -> tuple[int, int]:
    """Insere registros normalizados (dicts de crivo_busca). Retorna (novos, duplicatas_ignoradas)."""
    novos = 0
    dups = 0
    with _conn() as con:
        for r in registros:
            try:
                con.execute("""
                    INSERT INTO referencias
                    (projeto_id,fonte,doi,titulo,autores,ano,revista,resumo,url,keywords,
                     dup,status,chave_dedup,criado_em)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    projeto_id, r.get('fonte', ''), r.get('doi', ''), r.get('titulo', ''),
                    json.dumps(r.get('autores', []), ensure_ascii=False), str(r.get('ano', '')),
                    r.get('revista', ''), r.get('resumo', ''), r.get('url', ''),
                    json.dumps(r.get('keywords', []), ensure_ascii=False),
                    int(r.get('dup', 0)), 'pendente', r.get('chave_dedup', ''), time.time()))
                novos += 1
            except sqlite3.IntegrityError:
                dups += 1  # ja existe essa chave_dedup no projeto
    return novos, dups


def listar_referencias(projeto_id, status=None) -> list:
    q = "SELECT * FROM referencias WHERE projeto_id=?"
    args = [projeto_id]
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY estrela DESC, id ASC"
    with _conn() as con:
        out = []
        for r in con.execute(q, args).fetchall():
            d = dict(r)
            for campo in ('autores', 'keywords', 'tags'):
                d[campo] = json.loads(d.get(campo) or '[]')
            d['ficha'] = json.loads(d.get('ficha') or '{}')
            out.append(d)
        return out


def atualizar_referencia(ref_id, **campos) -> None:
    if not campos:
        return
    for k, v in list(campos.items()):
        if isinstance(v, (dict, list)):
            campos[k] = json.dumps(v, ensure_ascii=False)
    sets = ", ".join(f"{k}=?" for k in campos)
    with _conn() as con:
        con.execute(f"UPDATE referencias SET {sets} WHERE id=?", (*campos.values(), ref_id))


def contar_por_status(projeto_id) -> dict:
    with _conn() as con:
        rows = con.execute(
            "SELECT status, COUNT(*) n FROM referencias WHERE projeto_id=? GROUP BY status",
            (projeto_id,)).fetchall()
        tot = con.execute(
            "SELECT COUNT(*) n, SUM(dup) d FROM referencias WHERE projeto_id=?",
            (projeto_id,)).fetchone()
    cont = {r['status']: r['n'] for r in rows}
    cont['total'] = tot['n'] or 0
    cont['duplicatas'] = tot['d'] or 0
    return cont


# ---------------- backup / restaurar (JSON) ----------------
def exportar_projeto(projeto_id) -> dict:
    """Projeto + referencias num dict serializavel (pro disco temporario da nuvem
    nao te fazer perder o trabalho)."""
    p = get_projeto(projeto_id)
    return {'crivo_backup': 2, 'projeto': p, 'referencias': listar_referencias(projeto_id)}


def importar_projeto(dados) -> int:
    p = dados.get('projeto', {}) or {}
    pid = criar_projeto(p.get('nome', 'Projeto importado'), p.get('tema', ''), p.get('descricao', ''))
    atualizar_projeto(pid,
                      pico=p.get('pico', '{}') if isinstance(p.get('pico'), str) else json.dumps(p.get('pico') or {}, ensure_ascii=False),
                      criterios_inc=p.get('criterios_inc', '[]') if isinstance(p.get('criterios_inc'), str) else json.dumps(p.get('criterios_inc') or [], ensure_ascii=False),
                      criterios_exc=p.get('criterios_exc', '[]') if isinstance(p.get('criterios_exc'), str) else json.dumps(p.get('criterios_exc') or [], ensure_ascii=False),
                      buscas=p.get('buscas', '{}') if isinstance(p.get('buscas'), str) else json.dumps(p.get('buscas') or {}, ensure_ascii=False),
                      manuscrito=p.get('manuscrito', '{}') if isinstance(p.get('manuscrito'), str) else json.dumps(p.get('manuscrito') or {}, ensure_ascii=False))
    with _conn() as con:
        for r in dados.get('referencias', []) or []:
            con.execute("""
                INSERT OR IGNORE INTO referencias
                (projeto_id,fonte,doi,titulo,autores,ano,revista,resumo,url,keywords,
                 dup,status,motivo,criterio,tags,nota,estrela,ficha,full_text,chave_dedup,criado_em)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                pid, r.get('fonte', ''), r.get('doi', ''), r.get('titulo', ''),
                json.dumps(r.get('autores', []), ensure_ascii=False), str(r.get('ano', '')),
                r.get('revista', ''), r.get('resumo', ''), r.get('url', ''),
                json.dumps(r.get('keywords', []), ensure_ascii=False), int(r.get('dup', 0)),
                r.get('status', 'pendente'), r.get('motivo', ''), r.get('criterio', ''),
                json.dumps(r.get('tags', []), ensure_ascii=False), r.get('nota', ''),
                int(r.get('estrela', 0)), json.dumps(r.get('ficha', {}), ensure_ascii=False),
                r.get('full_text', ''), r.get('chave_dedup', ''), time.time()))
    return pid


if __name__ == '__main__':
    inicializar_banco()
    print("crivo.db em:", BANCO_CRIVO)
    print("Tabelas criadas. Projetos:", len(listar_projetos()))
