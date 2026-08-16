# Crivo — revisão de literatura assistida

App para revisão de literatura: você digita o tema, ele **busca de verdade** em 4 bases
acadêmicas gratuitas (PubMed, Europe PMC, Crossref, Semantic Scholar), a IA faz a **triagem**,
a **ficha de extração** e rascunha o **manuscrito ancorado** (só cita o que foi incluído).

- **Na nuvem** (site): usa a IA do **Groq** (chave grátis).
- **Na sua máquina**: usa o **Ollama** local, sem chave.

Só usa literatura pública — nenhum dado de paciente.

---

## Publicar o site (grátis) — passo a passo

Você faz isto uma vez. Não precisa saber programar.

### 1. Crie a chave grátis da IA (Groq)
1. Acesse **https://console.groq.com** e entre (com Google ou e-mail).
2. Menu **API Keys** → **Create API Key** → copie a chave e guarde num lugar seguro.
   (É uma senha — não mande para ninguém.)

### 2. Crie uma conta no GitHub
1. Acesse **https://github.com** → **Sign up**.
2. Depois de entrar, clique em **New** (novo repositório).
   - Nome: `crivo` · deixe **Private** (particular) · clique **Create repository**.

### 3. Suba os arquivos do Crivo
1. No repositório novo, clique em **uploading an existing file** (ou **Add file › Upload files**).
2. **Arraste todos os arquivos desta pasta** (`crivo_app.py`, `crivo_busca.py`, `crivo_ia.py`,
   `crivo_db.py`, `requirements.txt`). Clique **Commit changes**.
   - Não precisa subir este README nem o `.streamlit/secrets.toml.example`.

### 4. Publique no Streamlit Cloud
1. Acesse **https://share.streamlit.io** → **Continue with GitHub**.
2. **Create app** → **Deploy a public app from a repo**.
   - Repository: seu `crivo` · Branch: `main` · **Main file path:** `crivo_app.py`.
3. Antes de finalizar, abra **Advanced settings › Secrets** e cole exatamente:
   ```
   GROQ_API_KEY = "sua-chave-do-groq-aqui"
   ```
4. Clique **Deploy**. Em 1–2 minutos aparece a **URL do seu site**.

### 5. Use no iPhone
Abra a URL no Safari. Para virar um ícone: botão **Compartilhar › Adicionar à Tela de Início**.

---

## Importante
- **Backup:** o site "dorme" quando fica parado e o armazenamento é temporário. Na aba
  **Exportar**, baixe o **backup (JSON)** do seu projeto; quando voltar, use **Restaurar**.
- A busca funciona sem chave; só a IA (triagem/ficha/manuscrito) precisa da chave do Groq.
- O **Semantic Scholar** sem chave às vezes limita (erro 429) — é só tentar de novo.

## Rodar na sua máquina (opcional, com Ollama)
```
pip install -r requirements.txt
streamlit run crivo_app.py
```
Sem `GROQ_API_KEY`, ele usa o Ollama local (precisa do Ollama rodando e um modelo baixado,
ex.: `ollama pull qwen2.5:7b`).
