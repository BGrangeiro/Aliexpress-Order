# AliExpress Orders Sync

Sincroniza pedidos da AliExpress para uma planilha Excel `.xlsx` fixa, usando o número do pedido como chave para evitar duplicidade.

O projeto foi pensado para usar várias contas AliExpress compartilhando a mesma planilha. Antes de rodar, ele pergunta qual conta será usada; a conta escolhida define a pasta de sessão do navegador e o texto da coluna **Responsável**.

## O Que Faz

- Abre a página **Meus Pedidos** da AliExpress.
- Usa uma sessão persistente do Chrome/Edge para manter cookies e login por conta.
- Carrega pedidos antigos clicando em **View orders** até acabar o histórico disponível.
- Entra em **Order details** de cada pedido.
- Extrai o campo **Payment method** e salva na coluna **Forma de Pagamento**.
- Abre a área de rastreio, como **Package collected by carrier** ou **View tracking info**.
- Extrai o **Tracking number** e salva na coluna **Nº Rastreio**.
- Cria ou atualiza a planilha Excel com `openpyxl`.
- Atualiza pedidos existentes sem duplicar linhas.
- Pode ficar monitorando automaticamente em segundo plano enquanto o app estiver aberto, sem abrir item por item.
- Remove pedidos anteriores a **01/01/2026**.
- Ordena a planilha por **Data do Pedido**, com os pedidos mais recentes em cima.
- Mistura pedidos de contas diferentes pela data, em vez de separar por responsável.

## Instalação

No PowerShell:

```powershell
cd C:\Users\User\Desktop\150
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
```

## Configuração

O arquivo principal de configuração é:

```text
.env
```

Exemplo:

```env
EXCEL_PATH=./data/pedidos_aliexpress.xlsx
RESPONSAVEL_PADRAO=Seu Nome
ACCOUNT_ID=auto
ASK_ACCOUNT=true
ACCOUNT_PROFILES_PATH=./contas.txt
CHECK_INTERVAL_MINUTES=60
ALIEXPRESS_SESSION_DIR=./chrome-session
ALIEXPRESS_ORDERS_URL=https://www.aliexpress.com/p/order/index.html
HEADLESS=false
DEFAULT_TIPO=Entrada
BROWSER_CHANNEL=chrome
CDP_URL=http://127.0.0.1:9222
BROWSER_EXECUTABLE=
```

`EXCEL_PATH` é a planilha fixa. Todas as contas gravam no mesmo arquivo quando esse caminho é igual.

## Contas

As contas ficam no arquivo:

```text
contas.txt
```

Formato:

```text
id|email|responsavel_na_planilha|pasta_de_sessao
```

Exemplo atual:

```text
conta1|riquelmesenna577@gmail.com|riquelme|./chrome-session-conta-1
conta2|riquelmestayler@gmail.com|neto|./chrome-session-conta-2
```

Ao rodar o programa, ele mostra um menu:

```text
1. riquelmesenna577@gmail.com -> Responsável: riquelme
2. riquelmestayler@gmail.com -> Responsável: neto
```

Se escolher a conta 1, a coluna **Responsável** fica `riquelme`.

Se escolher a conta 2, fica `neto`.

Cada conta precisa ter uma pasta de sessão diferente. Não apague essas pastas, porque elas guardam cookies e login.

Para adicionar uma nova conta, adicione uma linha:

```text
conta3|emaildeterceiraconta@gmail.com|nome_na_planilha|./chrome-session-conta-3
```

## Como Usar

### Aplicativo `.exe`

O jeito recomendado para entregar ao cliente e usar sem VS Code e sem terminal e abrir:

```text
dist\AliExpressPedidos\AliExpressPedidos.exe
```

Na janela do app:

1. Escolha a conta em **Conta logada**.
2. Clique no botão **?** para ver as contas cadastradas, o responsável e a pasta de sessão.
3. Clique em **Abrir navegador / login** se precisar autenticar a conta na AliExpress.
4. Deixe a janela do navegador aberta.
5. Clique em **Verificar pedidos** para rodar uma vez, ou em **Iniciar monitoramento** para deixar automático.

O botão **Verificar pedidos** executa a sincronização completa do comando `sync`: carrega os pedidos, entra em **Order details**, busca rastreio, forma de pagamento e atualiza a planilha fixa configurada em `EXCEL_PATH`.

O botão **Iniciar monitoramento** faz uma verificação leve automaticamente no intervalo definido por:

```env
CHECK_INTERVAL_MINUTES=60
```

Esse monitoramento leve recarrega **My Orders**, lê apenas os pedidos visíveis da lista e atualiza pedido novo ou status básico. Ele não entra em **Order details** e não pesquisa produto por produto. Se precisar completar rastreio e forma de pagamento, use **Verificar pedidos**.

Enquanto o monitoramento estiver ativo, o app mostra:

- conta monitorada;
- última verificação;
- próxima verificação;
- logs do que foi lido, criado ou atualizado.

Para trocar de conta:

1. Clique em **Parar monitoramento**.
2. Feche o navegador da conta atual.
3. Escolha outra conta no app.
4. Clique em **Abrir navegador / login** se precisar.
5. Clique em **Iniciar monitoramento** novamente.

Para gerar o `.exe` novamente depois de alterar o código:

```powershell
.\build_exe.ps1
```

O cliente deve receber a pasta inteira:

```text
dist\AliExpressPedidos
```

Não envie apenas o `.exe` sozinho, porque a pasta também leva `.env`, `contas.txt`, dependências internas e a pasta `data`.

### Terminal

Primeiro abra o navegador da conta:

```powershell
python -m aliexpress_orders_sync.main open-browser
```

Escolha a conta no menu, faça login na AliExpress e deixe a janela aberta.

Depois sincronize:

```powershell
python -m aliexpress_orders_sync.main sync
```

Para monitorar periodicamente:

```powershell
python -m aliexpress_orders_sync.main watch
```

O intervalo do `watch` é definido por:

```env
CHECK_INTERVAL_MINUTES=60
```

## Colunas Da Planilha

1. Data do Pedido
2. Descrição do Item
3. Quantidade
4. Valor Total
5. Valor Unitário
6. Responsável
7. Status de Entrega
8. Número do Pedido
9. Nº Rastreio
10. Forma de Pagamento

Observações:

- **Valor Unitário** é calculado por fórmula: `Valor Total / Quantidade`.
- **Número do Pedido** é a chave usada para atualizar sem duplicar.
- **Nº Rastreio** vem do campo `Tracking number` dentro de **Order details**.
- **Forma de Pagamento** vem do campo `Payment method` dentro de **Order details**.
- Pedidos anteriores a **01/01/2026** são removidos.

## Fluxo Dos Detalhes

Para cada pedido, o scraper tenta:

1. Clicar em **Order details**.
2. Clicar no bloco abaixo de **Estimated delivery date**.
3. Também tenta textos como **Package collected by carrier** e **View tracking info**.
4. Extrair o valor de **Payment method**.
5. Extrair o valor de **Tracking number**.
6. Fechar a página/aba de detalhes quando ela for aberta separadamente.

Durante a execução, o terminal mostra:

```text
Buscando detalhes 1/50 - pedido ...
  Rastreio encontrado: ...
  Pagamento encontrado: ...
```

ou:

```text
  Rastreio não encontrado.
  Pagamento não encontrado.
```

## Sessão E Login

O projeto não salva senha e não faz login automático. Ele usa o Chrome/Edge com uma pasta de perfil por conta.

Exemplo:

```text
./chrome-session-conta-1
./chrome-session-conta-2
```

Essas pastas guardam cookies e login, parecido com um Chrome normal. Mesmo assim, a AliExpress pode expirar a sessão e pedir autenticação novamente.

Para reduzir relogin:

- use sempre a mesma pasta de sessão para a mesma conta;
- não apague as pastas `chrome-session-*`;
- deixe a janela aberta quando for rodar `sync`;
- feche a janela antes de trocar para outra conta, porque todas usam a porta local `9222`.

## Testes

```powershell
python -m pytest
```

## Limitações

A AliExpress pode mudar HTML, fluxo de login, CAPTCHA ou layout dos pedidos. Se isso acontecer, pode ser necessário ajustar os seletores do scraper.

Alternativas caso o scraping fique instável:

- usar API oficial ou endpoint autorizado, se disponível;
- criar uma extensão de navegador para ler a página autenticada;
- importar dados manualmente e usar apenas o módulo Excel para consolidar a planilha.
