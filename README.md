# AliExpress Pedidos

Sistema local para monitorar pedidos da AliExpress, armazená-los em um banco SQLite e consultá-los em um dashboard web. O fluxo principal não cria nem atualiza planilhas.

## O Que O Sistema Faz

- permite escolher qual conta AliExpress será verificada;
- abre o Chrome com uma sessão persistente;
- monitora a página **My Orders** sem interferir na aba usada pelo cliente;
- executa uma verificação completa entrando em **Order details**;
- salva pedidos e atualizações no banco `data/pedidos.db`;
- evita duplicidade usando a conta e o número do pedido como chave;
- coleta nome completo, data, quantidade, valor, status e forma de pagamento;
- coleta um ou vários números de rastreio por pedido;
- exibe um dashboard analítico escuro com navegação por abas;
- apresenta gráficos de evolução mensal e distribuição por status;
- compara contas, pagamentos e produtos por volume;
- oferece filtros por conta, status, rastreio, pagamento, moeda, data, valor e busca;
- ignora pedidos anteriores a **01/01/2026**.

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

Se o PowerShell bloquear a ativação do ambiente virtual, execute:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## Executar Localmente

```powershell
cd C:\Users\User\Desktop\150
.\.venv\Scripts\Activate.ps1
python run_web.py
```

O painel abre automaticamente em:

```text
http://127.0.0.1:8787
```

Para encerrar, volte ao terminal e pressione `Ctrl+C`.

## Como Usar

1. Escolha o **Responsável**: Jeferson, Riquelme ou Neto.
2. Escolha o **E-mail de acesso** vinculado à pessoa.
3. Clique em **Abrir AliExpress**.
4. Faça login ou resolva a verificação da AliExpress, se necessário.
5. Clique em **Monitorar** para acompanhar novos pedidos.
6. Use **Verificação completa** para atualizar rastreios e formas de pagamento.
7. Consulte os pedidos e indicadores diretamente no dashboard.

O monitoramento leve lê os cartões de **My Orders**. A verificação completa entra nos detalhes de cada pedido e pode levar mais tempo.

Ao trocar o responsável, gráficos e tabelas passam a mostrar somente os pedidos daquela pessoa. O filtro **E-mail** permite restringir ainda mais o resultado a uma conta específica.

## Dashboard E Abas

O painel é dividido em:

- **Visão geral:** indicadores financeiros e operacionais, gráfico mensal, status, contas, pagamentos e produtos;
- **Pedidos:** tabela completa com valores, conta, status, pagamento e rastreios;
- **Rastreios:** visão logística com pedidos de um ou vários pacotes;
- **Atividade:** estado do agente, horários das verificações e histórico de eventos.

Filtros disponíveis:

- conta;
- status;
- todos, múltiplos, único ou nenhum rastreio;
- método de pagamento;
- moeda;
- data inicial e final, além de períodos rápidos;
- valor mínimo e máximo;
- busca por produto, número do pedido, responsável, pagamento ou rastreio.

Todos os indicadores, gráficos e tabelas respondem aos filtros globais.

Quando um pedido possui vários pacotes, todos os códigos ficam associados ao mesmo pedido e aparecem juntos na coluna **Rastreio**.

## Configuração

Edite o arquivo `.env`:

```env
DATABASE_PATH=./data/pedidos.db
RESPONSAVEL_PADRAO=Seu Nome
ACCOUNT_ID=auto
ASK_ACCOUNT=true
ACCOUNT_PROFILES_PATH=./contas.txt
CHECK_INTERVAL_MINUTES=1
ALIEXPRESS_SESSION_DIR=%LOCALAPPDATA%\AliExpressPedidos\chrome-profile
ALIEXPRESS_ORDERS_URL=https://www.aliexpress.com/p/order/index.html
HEADLESS=false
BROWSER_CHANNEL=chrome
CDP_URL=http://127.0.0.1:9222
BROWSER_EXECUTABLE=
WEB_HOST=127.0.0.1
WEB_PORT=8787
WEB_OPEN_BROWSER=true
```

`DATABASE_PATH` define onde os pedidos são armazenados. O SQLite cria o arquivo automaticamente.

`CHECK_INTERVAL_MINUTES` define o intervalo do monitoramento automático.

## Contas

Clique na engrenagem no canto superior direito para:

- abrir a central de configurações e entrar em **Contas de compra**;
- consultar as contas cadastradas;
- escolher o responsável;
- informar o nome de exibição;
- cadastrar um novo e-mail.
- editar nome, e-mail ou responsável;
- excluir uma conta sem apagar seu histórico de pedidos.

O cadastro é salvo automaticamente em `contas.txt`. Reiniciar o sistema não apaga as contas.

O projeto começa com três contas de teste para Jeferson, três para Riquelme e três para Neto. Endereços que terminam em `example.com` são apenas placeholders.

Para trocar um placeholder manualmente, feche o sistema e edite a linha correspondente em `contas.txt`:

```text
id|email|responsavel|pasta_de_sessao|nome_da_conta
```

Exemplo:

```text
riquelme-2|emailreal@gmail.com|Riquelme|%LOCALAPPDATA%\AliExpressPedidos\chrome-profile|Conta de compras
```

Salve o arquivo e execute novamente `python run_web.py`.

## Sessão E Login

O sistema não armazena senhas. O perfil configurado em `ALIEXPRESS_SESSION_DIR` guarda cookies e contas do Google, como um Chrome comum.

Não apague a pasta de sessão se quiser manter os logins. A AliExpress ainda pode solicitar nova autenticação por segurança.

## Dados

O banco principal é:

```text
data\pedidos.db
```

Para começar com um banco vazio, feche o sistema e remova `data\pedidos.db`.

O sistema não importa mais automaticamente a planilha antiga e não gera novos arquivos Excel.

Cada pedido salvo no sistema mantém os mesmos dados usados anteriormente na planilha:

- data do pedido;
- nome completo do produto;
- quantidade;
- valor total e valor unitário;
- responsável e conta;
- status de entrega;
- número do pedido;
- um ou vários números de rastreio;
- forma de pagamento.

O número de rastreio só aparece quando a AliExpress já o disponibilizou. Pedidos sem código ficam como **Ainda não disponível** e podem ser completados por uma verificação posterior.

## Testes

```powershell
python -m pytest
```

## Limitações

A AliExpress pode alterar layout, textos, CAPTCHA ou fluxo de login. O scraper reconhece os principais textos em português e inglês, mas mudanças no site podem exigir novos seletores.

Para uso remoto no futuro, o dashboard e o agente precisam de autenticação e de uma estratégia para executar o Chrome no computador que mantém a sessão AliExpress.
