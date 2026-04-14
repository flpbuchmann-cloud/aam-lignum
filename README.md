# AAM Lignum

Asset Allocation Manager para analise de carteiras multi-cliente com
integracao ao Google Sheets (Base de Dados).

## Funcionalidades

- **Importar**: upload de PDFs (Warren, XP), parsing automatico, matching contra Base de Dados
- **Asset Allocation**: tabela de posicoes (editavel), recomendacao, consolidacao Macro/Micro/Instituicao
- **RF Carrego**: analise de carry de RF com duration, gross-up, taxas ponderadas (Pre, Real, CDI, CDI+)

## Execucao local

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Coloque o arquivo de credenciais da service account em `config/credentials.json`.

## Deploy no Streamlit Cloud

1. Crie um repositorio privado no GitHub com este codigo
2. Em share.streamlit.io, conecte o repo e defina `streamlit_app.py` como entry point
3. Em App Settings > Secrets, cole o conteudo do `credentials.json` no formato abaixo:

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."
...
```

4. Compartilhe a planilha Base de Dados com o email da service account como Editor
