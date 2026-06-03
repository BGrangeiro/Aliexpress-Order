# AliExpress Orders Sync

Sincroniza pedidos da AliExpress para uma planilha Excel `.xlsx`, criando o arquivo quando ele não existe e atualizando pedidos existentes pelo número do pedido.

## O que este projeto faz

- Abre a página **Meus Pedidos** da AliExpress usando Playwright.
- Usa uma sessão persistente do navegador para evitar login repetido.
- Lê pedidos disponíveis na página e normaliza número do pedido, data, quantidade, valor, moeda e status.
- Cria ou atualiza uma planilha Excel com `openpyxl`.
- Evita duplicidade usando o **Número do Pedido** como chave.
- Atualiza o campo **Status de Entrega** quando ele mudar.
- Cria a coluna **Tipo** com validação de dados do Excel, usando lista suspensa com `Entrada` e `Saída`.

## Estrutura

```text
aliexpress_orders_sync/
  config.py       # Carrega configurações do .env
  excel_sync.py   # Criação/atualização da planilha com openpyxl
  main.py         # CLI: login, sync e watch
  models.py       # Modelo normalizado de pedido
  scraper.py      # Scraping com Playwright
tests/
  test_excel_sync.py
```

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
```

Edite o arquivo `.env`:

```env
EXCEL_PATH=./data/pedidos_aliexpress.xlsx
RESPONSAVEL_PADRAO=Seu Nome
CHECK_INTERVAL_MINUTES=60
ALIEXPRESS_SESSION_DIR=./browser-session
ALIEXPRESS_ORDERS_URL=https://www.aliexpress.com/p/order/index.html
HEADLESS=false
DEFAULT_TIPO=Saída
BROWSER_CHANNEL=chrome
CDP_URL=http://127.0.0.1:9222
BROWSER_EXECUTABLE=
```

## Como usar

### Modo recomendado quando há CAPTCHA

Abra uma janela normal do Chrome/Edge com porta local:

```powershell
python -m aliexpress_orders_sync.main open-browser
```

Faça login na AliExpress nessa janela, resolva o CAPTCHA manualmente e deixe a janela aberta.
Na tela **Meus Pedidos**, o sincronizador clica automaticamente em **View orders** para carregar pedidos antigos até o botão parar de aparecer.

Depois sincronize:

```powershell
python -m aliexpress_orders_sync.main sync
```

Para monitorar periodicamente, mantenha essa janela aberta e rode:

```powershell
python -m aliexpress_orders_sync.main watch
```

### Modo Playwright tradicional

Se a AliExpress não bloquear o CAPTCHA, também é possível salvar a sessão diretamente:

```powershell
python -m aliexpress_orders_sync.main login
```

Faça login na janela aberta, confira que a página **Meus Pedidos** carregou e pressione Enter no terminal.

Para sincronizar uma vez:

```powershell
python -m aliexpress_orders_sync.main sync
```

Para monitorar periodicamente:

```powershell
python -m aliexpress_orders_sync.main watch
```

O intervalo é controlado por `CHECK_INTERVAL_MINUTES`.

Se o CAPTCHA da AliExpress falhar no Chromium do Playwright, mantenha `BROWSER_CHANNEL=chrome` para usar o Google Chrome instalado no Windows. Se você não tiver o Chrome instalado, remova essa linha ou deixe `BROWSER_CHANNEL=` e rode `python -m playwright install chromium`.

## Colunas geradas

1. Data do Pedido
2. Categoria
3. Quantidade
4. Tipo
5. Valor Total
6. Valor Unitário
7. Responsável
8. Status de Entrega
9. Número do Pedido
10. Moeda

A coluna **Número do Pedido** é mantida na planilha para garantir atualização sem duplicar linhas.

## Testes

```powershell
pip install pytest
pytest
```

## Limitações importantes

A AliExpress pode alterar HTML, classes e fluxos de autenticação, além de aplicar proteções anti-bot. Por isso, o scraper usa seletores prováveis e extração textual por regex, mas pode precisar de ajuste depois de verificar a página real da sua conta.

Alternativas viáveis quando o scraping for instável:

- usar API oficial ou endpoint autorizado, se disponível para sua conta;
- criar uma extensão de navegador que leia os dados diretamente da página já autenticada;
- importar manualmente um arquivo/exportação da plataforma e usar apenas o módulo Excel deste projeto para sincronização.
