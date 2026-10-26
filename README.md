# Prevenção de Evasão Escolar no Ensino Médio Técnico

Sistema preditivo para identificação precoce de alunos em risco de evasão, desenvolvido como entrega de **Projetos Integrados II** (curso de Inteligência Artificial e Ciência de Dados — Uniube).

**Equipe:** Róbson de Oliveira Cabral · Sidnário Oliveira Rosa ·Lissa Ferreira Massuda · Nathália Vieira Kamimura
**Professor:** Romualdo Mathias Filho

## O projeto

O objetivo é construir um pipeline de dados e um modelo preditivo de classificação, usando Mineração de Dados Educacionais (Educational Data Mining), integrado a um painel interativo (dashboard) que apoie a coordenação pedagógica a agir de forma proativa — identificando alunos em risco antes do abandono se consolidar.

Fatores analisados: desempenho acadêmico, frequência (absenteísmo) e fatores socioeconômicos. O risco de cada aluno é classificado em três níveis: **Risco Alto**, **Risco Médio** e **Risco Baixo**.

Todo o desenvolvimento usa apenas ferramentas gratuitas: Google Colab, Python (Pandas, Scikit-learn), GitHub e Streamlit Community Cloud.

## Estado atual

**Etapa 1 — Repositório e dataset** (`notebooks/01_exploracao_dataset.ipynb`): criação do repositório e exploração inicial do dataset de prototipagem. Como a base real da escola ainda não está disponível, o pipeline é validado com o dataset público [Predict Students' Dropout and Academic Success](https://archive.ics.uci.edu/dataset/697/predict+students+dropout+and+academic+success) (UCI), de instituições de ensino superior — o modelo será retreinado com dados reais assim que disponíveis.

**Etapa 2 — Pipeline de modelagem** (`notebooks/02_pipeline_modelo.ipynb`): engenharia de atributos final (indicador socioeconômico ponderado), treino da Regressão Logística e da Árvore de Decisão (ambos com `class_weight="balanced"` para o desbalanceamento das classes), avaliação por classe de risco e exportação do modelo vencedor — escolhido pelo recall da classe Risco Alto. O modelo treinado fica em `modelo/modelo_risco.pkl`, com os metadados (atributos usados, métricas) em `modelo/features.json`.

**Banco de dados (preparação para a Etapa 3)** (`banco/`): schema SQLite pensado a partir de uma observação do professor sobre armazenamento e segurança dos dados dos alunos. Três tabelas — `alunos` (identificação, separada do resto), `avaliacoes_risco` (uma linha por avaliação, preservando o histórico de cada aluno) e `processamentos` (log de auditoria de cada planilha processada). Veja a seção "Banco de dados" mais abaixo.

**Etapa 3 — Dashboard Streamlit** (`app/`): painel com login e perfis (Administrador, Coordenação e Professor) e 6 telas principais (Visão geral, Lista priorizada, Ficha do aluno, Relatórios, Upload de dados e Configurações, além de Divergências quando há alunos ausentes), que carrega o modelo treinado, classifica a planilha enviada e grava o resultado no SQLite. Veja a seção "Dashboard" mais abaixo.

## Como rodar os notebooks

**Opção 1 — Google Colab (recomendado):**
1. Acesse [colab.research.google.com](https://colab.research.google.com).
2. Abra o notebook desejado (via GitHub, depois de fazer o push deste repositório, ou por upload direto).
3. Execute as células em ordem — a primeira do notebook 1 instala a biblioteca `ucimlrepo`, que baixa o dataset automaticamente. O notebook 2 depende do CSV gerado pelo notebook 1 (`dados/processado/dataset_explorado.csv`), então rode o 1 antes do 2.

**Opção 2 — local:**
```bash
pip install -r requirements.txt
jupyter notebook notebooks/01_exploracao_dataset.ipynb
jupyter notebook notebooks/02_pipeline_modelo.ipynb
```

## Estrutura do repositório

```
evasao-escolar/
├─ dados/
│  ├─ raw/            # base original (cópia do dataset UCI; a base real da escola entra aqui depois)
│  └─ processado/      # dados limpos, gerados pelo notebook
├─ notebooks/
│  ├─ 01_exploracao_dataset.ipynb   # Etapa 1: carga e análise exploratória
│  └─ 02_pipeline_modelo.ipynb      # Etapa 2: atributos, treino e avaliação dos modelos
├─ modelo/              # modelo_risco.pkl (modelo treinado) e features.json (metadados)
├─ banco/               # schema SQLite (criar_banco.py, database.py) e escola.db (gerado, não versionado)
├─ app/                 # dashboard Streamlit (dashboard.py), pipeline de previsão e requirements do deploy
├─ dados/demo/          # dados FICTÍCIOS de demonstração e planilha-modelo
├─ .streamlit/          # tema e exemplo de segredos (secrets.toml real nunca é versionado)
├─ relatorio/            # relatório técnico final
├─ requirements.txt
└─ README.md
```

Essa organização segue o documento de Arquitetura e Plano Técnico do grupo e separa claramente os três entregáveis do Escopo do Projeto: notebook documentado, relatório técnico e protótipo web funcional.

## Banco de dados

Depois da apresentação da Etapa 1, o professor sugeriu estruturar desde já um banco de dados simples (SQLite), pensando no armazenamento e na segurança dos dados dos alunos — relevante também porque o Ensino Médio Técnico lida majoritariamente com menores de idade, o que pede atenção redobrada sob a LGPD.

Para criar o banco localmente:
```bash
python banco/criar_banco.py
```

Isso gera `banco/escola.db` com cinco tabelas:
- **`alunos`** — identificação do aluno (matrícula, nome, turma, curso). É a única tabela que guarda o nome.
- **`avaliacoes_risco`** — uma linha por avaliação de risco (nunca sobrescrita), com os atributos usados no cálculo e o nível de risco resultante. Referencia o aluno só pelo `id_aluno`, nunca pelo nome.
- **`processamentos`** — log de auditoria: quando cada planilha foi processada, quantos alunos ela cobriu e uma "impressão digital" do conteúdo (usada para avisar quando a mesma planilha é enviada duas vezes). Cada avaliação de `avaliacoes_risco` guarda também de qual planilha veio (`id_processamento`), o que permite saber quem estava ou não em cada envio.
- **`acoes_pedagogicas`** — uma linha por ação registrada pela equipe (data, tipo, descrição e responsável), ligada ao aluno pelo `id_aluno`. O texto livre pode conter dado sensível de menor (LGPD): só a Ficha do aluno o exibe, e cada ação pode ser excluída.
- **`configuracoes`** — regras da instituição ajustáveis no app (hoje, o limite de frequência e a escala da nota de admissão). Não é apagada quando os dados são reiniciados. A frequência de cada aluno fica em `avaliacoes_risco.frequencia_pct` (opcional, fora do modelo).

Bancos criados em versões anteriores são atualizados sozinhos na primeira abertura (colunas novas, sem apagar nada).

As funções prontas para inserir e consultar esses dados estão em `banco/database.py`. O arquivo `escola.db` nunca deve ser versionado no Git (já está no `.gitignore`) — assim que alimentado com dados reais da escola, ele deve ficar só no ambiente que roda o dashboard.

## Dashboard

### Rodar localmente

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # depois edite o administrador inicial (admin_login e admin_senha)
streamlit run app/dashboard.py
```

O acesso é por **login e senha de cada pessoa**. No primeiro uso o banco não tem usuários: o app cria o **administrador inicial** com `admin_login` e `admin_senha` de `.streamlit/secrets.toml` (a senha precisa ter 10 caracteres ou mais e o app pede a troca no primeiro acesso). **Sem nenhum usuário e sem esses dois Secrets o app não abre** (falha fechada). A antiga senha única `senha_app` não é mais usada.

### Usuários e perfis

| Perfil | O que pode |
|---|---|
| **Administrador** | Tudo: Usuários, Auditoria, Configurações, apagar/reiniciar dados, e o que a coordenação faz. |
| **Coordenação** | Todos os alunos; Upload de dados, Desfazer envios, Divergências, Relatórios e ações pedagógicas. Sem Usuários, Configurações nem reiniciar o banco. |
| **Professor** | Só os alunos das **turmas em que o login dele aparece na coluna `professores` da planilha**: Visão geral, Lista, Ficha, Relatórios (PDF e Excel só das suas turmas) e ações pedagógicas. Sem Upload, Divergências nem Configurações. |

- **Cadastro:** o administrador cria os usuários na tela **Usuários** (login, nome, perfil e senha provisória; se deixar em branco, o app gera uma e mostra **uma única vez**). A pessoa troca a senha no primeiro acesso (e depois em *Minha conta*). Também é possível editar nome e perfil, desativar, **redefinir a senha** e **desbloquear**. O app não deixa o sistema sem nenhum administrador ativo.
- **Sessão:** o app encerra a sessão após **15 minutos sem uso** (cliques, digitação, toque ou rolagem), para todos os perfis. No último minuto aparece um aviso com contagem regressiva e o botão **Continuar conectado**; se o tempo acabar, a tela volta ao login com a mensagem de que a sessão foi encerrada por inatividade, e o evento fica na **Auditoria**. Há uma segunda barreira no servidor: se alguém voltar depois do prazo (ou o navegador tiver bloqueado o aviso), a sessão é encerrada na primeira interação. O Secret opcional `inatividade_minutos` muda o prazo (mínimo 1,5).
- **Senhas:** mínimo de 10 caracteres; guardadas só como hash (scrypt com sal), nunca em texto. **5 erros seguidos bloqueiam o usuário por 15 minutos** (o administrador pode desbloquear antes). A mensagem de erro é a mesma para login inexistente e senha errada.
- **Responsável pelas ações:** nas ações pedagógicas e nas divergências resolvidas, o responsável é **preenchido automaticamente** com o nome e o login de quem está logado (`Ana (prof.ana)`). O professor só exclui as ações que ele mesmo registrou; coordenação e administrador excluem qualquer uma.
- **Turmas dos professores:** vêm da coluna opcional `professores` da planilha, com os **logins separados por `;`** (ex.: `ana.silva;joao.souza`), por turma. O **último envio que trouxe a coluna substitui** as atribuições anteriores; um envio sem a coluna não muda nada; **Desfazer envios** restaura as atribuições do envio anterior. O login pode aparecer na planilha antes de o usuário existir (o upload avisa); a atribuição vale assim que o administrador criar o usuário.
- **Sem nenhum administrador (senha esquecida de todos):** use o script `python -m banco.usuarios redefinir <login>` (ou `criar <login> "<Nome>" admin`) no computador onde o app roda; ele pede a senha provisória sem mostrá-la.
- **Demonstração na nuvem** (`demo_automatica = true`): o app cria quatro contas **fictícias** (`demo.admin`, `demo.coord`, `prof.ana` e `prof.bruno`, senha pública `demonstracao-2026`) e a tela de login as mostra. A Ana vê as turmas 1º A, 1º B e 3º A; o Bruno, 2º A, 2º B e 3º A. Nunca use esse modo com dados reais. Os cards e as barras da **Visão geral** são clicáveis (abrem a lista já filtrada) e, na **Lista priorizada**, marcar a caixinha à esquerda de uma linha abre a ficha do aluno. Na aba **Upload de dados** é possível baixar a planilha-modelo, enviar a planilha da escola ou carregar os 4.424 alunos fictícios de demonstração.

### Política de retenção e exclusão de dados (LGPD)

Os dados são de alunos, em boa parte menores de idade, e só ficam enquanto forem necessários para o acompanhamento pedagógico.

| Situação | O que acontece |
|---|---|
| **Aluno ativo** (consta na planilha da escola) | Os dados ficam no sistema, com todo o histórico de avaliações e ações. |
| **Aluno que saiu da escola** (divergência resolvida como *Saiu da escola*) | Os dados pessoais são guardados por **12 meses** a partir dessa confirmação. Depois disso, o administrador pode **anonimizar**: o nome vira "Aluno anonimizado", a matrícula vira `ANON-nnnnnn`, a turma, as **ações pedagógicas** (texto livre) e os nomes antigos guardados para o "desfazer" são apagados, e o nome do aluno some da **Auditoria**. As avaliações (notas, risco e frequência) ficam **sem identificação**, para os números históricos e o retreino do modelo; o curso é mantido. |
| **Aluno ausente sem conferência** | Nada é apagado sozinho. Depois de 12 meses o app avisa, em **Configurações → Retenção de dados**, quantos estão assim, para a equipe conferir em *Divergências*. |
| **Pedido de exclusão de um aluno** (titular ou responsável) | O administrador abre a **Ficha do aluno**, usa *Excluir este aluno*, informa o motivo ou o protocolo (sem dados pessoais) e confirma. Apaga **tudo** do aluno e tira o nome e a matrícula dele da Auditoria. Se ele continuar na planilha da escola, volta no próximo envio: remova-o também da planilha de origem. |
| **Trilha de auditoria** | Guardada por 12 meses; o administrador apaga os registros antigos na tela *Auditoria*. |

- **A limpeza é manual, com prévia e confirmação:** em *Configurações → Retenção de dados* o administrador vê quantos alunos passaram do prazo (só matrícula e curso, nunca o nome), confirma e anonimiza. Cada limpeza e cada exclusão ficam registradas na Auditoria, sem dados do aluno.
- **Quem pode:** só o administrador. A anonimização não tem volta.
- **Fora do app:** a escola deve aplicar a mesma regra às cópias da planilha de origem, a backups do `escola.db` e aos relatórios PDF/Excel já baixados, pois o app não controla esses arquivos.

### O que cada tela mostra

- **Visão geral:** cards e gráficos de risco por nível, curso e turma — todos clicáveis (abrem a lista já filtrada). Os cards ficam em dois grupos: *Situação atual* (alunos avaliados, os três níveis de risco e **Frequência baixa**, o alerta de quem está abaixo do limite de frequência; cinza quando a planilha não tem frequência) e *Mudanças desde a avaliação anterior*, com **Pioraram** e **Melhoraram** (alunos cujo nível subiu ou desceu, por exemplo de Médio para Alto) e **Divergências**.
- **Lista priorizada:** ordenada por nível de risco e, dentro de cada nível, pela **probabilidade de Risco Alto** (os mais críticos primeiro), com a coluna *Prob. Risco Alto* e a coluna *Mudança* (▲ piorou, ▼ melhorou). A coluna *Frequência* aparece quando há dados, e o filtro *Frequência* isola quem está abaixo do limite. Com dados de frequência, a coluna *Alertas seguidos* mostra há quantas avaliações seguidas o aluno está abaixo do limite, o filtro *Faixa de frequência* usa faixas prontas calculadas a partir do limite (com 75%: abaixo de 60%, 60% a menos de 75%, 75% ou mais e sem frequência informada) e o filtro *Situação do alerta* separa **Novo alerta**, **Reincidente (2 ou mais seguidas)** e **Saiu do alerta** (o limite atual vale para todo o histórico). O filtro *Mudança desde a última avaliação* isola quem piorou ou melhorou, e o filtro *Ações pedagógicas* mostra só quem já tem (ou ainda não tem) ação registrada; a coluna *Última ação* traz só a data, nunca o texto. Marcar a caixinha de uma linha abre a ficha do aluno. Os botões **Baixar lista filtrada (CSV)** e **(Excel)** exportam exatamente o que está na tela; o Excel tem cores por nível de risco, filtros e linha de cabeçalho fixa, e uma aba *Informações* com data, limite de frequência e filtros usados (só matrícula, nunca o nome).
- **Ficha do aluno:** nome, probabilidades, fatores que mais pesaram, aviso quando o risco subiu, **alerta de frequência baixa** (faixa vermelha quando a frequência está abaixo do limite, com o histórico de alertas seguidos), **comparação com a média da turma** (nota de admissão, notas, taxas de aprovação do 1º/2º semestre e frequência; a média de cada indicador só considera quem tem o dado), **evolução do risco**, **ações pedagógicas** e histórico de avaliações (data, período, risco, probabilidade de Risco Alto, notas, taxas de aprovação e indicador socioeconômico). A evolução é um gráfico de linha com a probabilidade de Risco Alto em cada avaliação (pontos coloridos pelo nível), seguido de um gráfico da frequência com uma linha tracejada no limite da escola; um losango ◇ em volta do ponto indica ações registradas depois daquela avaliação. Em *Ações pedagógicas* informe data, tipo (conversa com a família, reforço escolar, encaminhamento etc.), descrição e responsável pelo registro (o app não tem login por pessoa, então o nome é digitado). Uma ação errada ou indevida pode ser excluída (com confirmação, sem volta); evite dados de saúde ou da família além do necessário.
- **Divergências:** o card fica sempre visível na Visão geral (cinza e sem clique quando é 0); quando há alunos avaliados antes que **não estão na última planilha**, ele ganha destaque, abre a tela e a tela também passa a aparecer no menu lateral. Lista matrícula, turma, curso, último risco, data da última avaliação e desde quando estão ausentes (sem nome, por privacidade). Depois de conferir com a secretaria, **marque uma ou várias linhas** (a caixa do cabeçalho marca todas), escolha o **motivo** (*Saiu da escola*, *Erro de planilha (conferido)* ou *Outro motivo*), clique em **Marcar como resolvida** (o responsável é você, pelo login): elas saem do card e do menu, mas ficam registradas (motivo, responsável e data) e aparecem ao ligar **Mostrar divergências resolvidas**, onde também dá para **Reabrir**. Quando não há mais pendentes, o card vira cinza com "N já conferida(s)" e continua abrindo o histórico. Se o aluno voltar numa planilha e sumir de novo, a nova ausência aparece como pendente.
- **Relatórios:** gera um **PDF** da escola toda, de um curso ou de uma turma: totais por nível de risco (tabela e barra), pontos de atenção (pioraram, melhoraram, frequência baixa, ações registradas e Risco Alto sem ação), comparativo por curso ou turma e a lista dos 50 alunos de Risco Alto mais críticos (a lista completa está no Excel da Lista priorizada). Só matrícula, nunca o nome, e com aviso de LGPD no rodapé.
- **Configurações:** onde a escola altera o **limite de frequência** (padrão 75%, o mínimo da LDB) e a **escala da nota de admissão** (padrão 0–100). Os valores ficam salvos no banco e não são apagados quando os dados são reiniciados; o limite de frequência vale na hora para todos os alunos. Também traz a seção **Retenção de dados** (veja a política acima).
- **Usuários** (só administrador) e **Minha conta** (todos): veja a seção "Usuários e perfis".
- **Auditoria** (só administrador): trilha de acessos com data e hora (horário de Brasília). Registra **quem abriu a ficha de qual aluno** (matrícula e nome no momento do acesso; um registro por abertura, e mexer na mesma ficha não repete), entradas e saídas do sistema (inclusive tentativas de login sem sucesso, sem a senha digitada, e sessões encerradas por inatividade), envio de planilha e carga de dados, desfazer envios, apagar dados, criação e alteração de usuários, redefinição de senha, desbloqueio e mudança de configurações. Filtros por período (padrão: últimos 30 dias), tipo de evento, usuário e aluno (matrícula ou parte do nome), e botão para baixar o que está na tela em CSV. **Reiniciar os dados dos alunos não apaga a trilha.** O prazo de guarda sugerido é de **12 meses**: a seção *Prazo de guarda* mostra quantos registros passaram do prazo e permite ao administrador apagá-los (a própria limpeza fica registrada). A trilha guarda o nome do aluno, então trate o acesso a ela com o mesmo cuidado das fichas; a regra final de retenção será definida junto com a política de dados.
- **Upload de dados:** planilha-modelo, envio de CSV (com tabela das colunas esperadas, aviso de planilha repetida, aviso de turma/curso ausentes e período de referência opcional), dados de demonstração, log de processamentos e **Desfazer envios** (veja abaixo).

**Para ver os alertas de piora e melhora na demonstração:** carregue os dados de demonstração e, em *Upload de dados*, clique em *Carregar nova avaliação* (`dados/demo/alunos_demo_rodada2.csv`, fictícia: cerca de 8% dos alunos pioram e 6% melhoram). Com dados reais, o alerta aparece quando uma segunda planilha é enviada (veja o passo a passo abaixo). Para ver também a tela *Divergências* na demonstração, apague algumas linhas de `alunos_demo_rodada2.csv` numa cópia do arquivo e envie essa cópia em *Upload de dados*. A probabilidade de Risco Alto é a estimada pelo modelo para o aluno; ela ordena a lista, mas o nível de risco exibido continua sendo o previsto pelo modelo.

### Passo a passo: carregar uma nova avaliação e comparar com a anterior

1. **Prepare a planilha.** Exporte da secretaria a lista atualizada com **todos os alunos matriculados**, nas colunas do modelo de planilha (veja o formato abaixo; os nomes antigos em inglês também funcionam). A **matrícula** de cada aluno precisa ser a mesma da avaliação anterior: é ela que liga o aluno ao seu histórico.
2. **Envie.** Em *Upload de dados*, escolha o CSV e clique em **Processar planilha**. Se o conteúdo for idêntico ao de uma planilha já processada (mesmo com outro nome de arquivo ou linhas em outra ordem), o app avisa e só processa se você marcar *Quero processar mesmo assim*. Isso evita que o alerta de piora desapareça por engano, já que a comparação é sempre entre as duas avaliações mais recentes de cada aluno.
3. **Veja a comparação.** Na *Visão geral*, os cards **Pioraram** e **Melhoraram** mostram quem mudou de nível desde a avaliação anterior; clique no card para abrir a lista já filtrada.
4. **Confira as divergências.** Alunos que estavam na avaliação anterior e **não estão na nova planilha** saem da Visão geral e da Lista priorizada (para não aparecerem com dados desatualizados) e passam a aparecer no card e na tela **Divergências**. Confira com a secretaria:
   - *foi erro de arquivo?* Envie a planilha corrigida e completa: os alunos voltam sozinhos às listas;
   - *o aluno saiu da escola?* Não precisa fazer nada. Ele continua na tela Divergências (com a data desde quando está ausente), e o histórico dele fica guardado no banco.

5. **Se enviou a planilha errada, desfaça antes de corrigir.** Em *Upload de dados*, abra **Desfazer envios** (no fim da página), escolha o envio na lista, confira o resumo do que será apagado, marque a confirmação e clique em **Desfazer**. Ele desfaz **o envio escolhido e todos os posteriores** (do mais novo para o mais antigo): apaga as avaliações desses envios, os alunos que só existiam neles (junto com as ações pedagógicas registradas para eles) e as conferências de divergência ligadas a eles, e **restaura nome, turma e curso** que esses envios tinham sobrescrito (envios feitos em versões antigas do app não guardaram esses valores). A avaliação anterior de cada aluno volta a valer e os alertas e as divergências são recalculados. Só então envie a planilha corrigida. Sem desfazer, quem aparece nas duas planilhas fica com duas avaliações idênticas e o alerta de piora some.

Observações: o envio normal nunca apaga nada; só o botão de desfazer apaga, e não tem volta (para recuperar, envie a planilha de novo). Ele desfaz apenas o último envio e só planilhas processadas a partir desta versão; nome, turma e curso de alunos que já existiam não voltam ao valor antigo. Bancos criados antes desta versão não têm a impressão digital das planilhas antigas, então o aviso de repetição só vale para envios novos.

### Roteiro de demonstração com a turma (4 planilhas fictícias)

Os arquivos `dados/demo/demo_1_...csv` a `demo_4_...csv` (4.424 alunos fictícios, gerados por `dados/demo/gerar_demo.py` com semente fixa) contam uma história completa, na ordem. Comece com o banco vazio: em *Upload de dados*, **Reiniciar o banco → Apagar tudo e começar do zero**. Os números abaixo foram conferidos rodando o roteiro inteiro.

| Passo | Arquivo | O que fazer | O que deve aparecer |
|---|---|---|---|
| 1 | `demo_1_base_inicial.csv` | Enviar e processar | Visão geral com **4.424** alunos. Pioraram e Melhoraram em 0 (só há uma avaliação). |
| 2 | `demo_2_nova_avaliacao.csv` | Enviar e processar | **4.394** alunos; **204 pioraram** e **41 melhoraram**; surge o card **Divergências: 30** (alunos da planilha 1 que não vieram nesta). Abra a tela Divergências e a Lista priorizada com o filtro *Somente quem piorou*. |
| 3 | `demo_3_planilha_com_erro.csv` | Enviar e processar | Simula uma exportação com erro: o curso *Técnico em Logística* inteiro ficou de fora. A Visão geral cai para **3.561** alunos e Divergências sobe para **863**. Algo está errado. |
| 4 | (nenhum) | *Upload de dados → Desfazer envios* (escolha o envio da planilha 3) | Marque a confirmação e desfaça. Tudo volta ao estado do passo 2: **4.394** alunos, 204 pioraram, 41 melhoraram, 30 divergências. |
| 5 | `demo_4_planilha_corrigida.csv` | Enviar e processar | A mesma avaliação do passo 3, agora completa: **4.414** alunos, **223 pioraram**, **46 melhoraram**. Das 30 divergências, 20 alunos reaparecem sozinhos e **10 continuam em Divergências** (os que realmente saíram da escola). |
| 6 | `demo_4_planilha_corrigida.csv` | Enviar de novo | O app avisa que o conteúdo é **idêntico** ao já enviado e só processa após a confirmação. Se processar, Pioraram e Melhoraram caem para 0: é exatamente o que o aviso evita. |

Dica para mostrar por que o desfazer é necessário: faça o roteiro sem o passo 4 (envie o 3 e depois o 4). No fim, só **37** alunos aparecerão como "pioraram" (em vez de 223), porque quem estava nas duas planilhas ficou com avaliações iguais. Para refazer a demonstração, apague tudo e recomece do passo 1.

Extra: depois do passo 2, abra a ficha de um aluno que piorou (card *Pioraram* → marcar uma linha), veja a **evolução do risco** com 2 pontos e registre uma **ação pedagógica**; o losango aparece em volta do último ponto e a lista passa a mostrar a *Última ação* dele.

### Formato da planilha (CSV)

Os nomes das colunas são em português, sem acento e com sublinhado:

| Coluna | Obrigatória? | O que é |
|---|---|---|
| `matricula` | obrigatória | Identificador único do aluno. É ela que liga o aluno ao histórico entre uma planilha e outra. |
| `nome` | obrigatória | Nome do aluno (aparece só na Ficha do aluno). |
| `turma` | recomendada | Ex.: 2º A. Sem ela, os filtros e a comparação com a turma não funcionam. |
| `curso` | recomendada | Ex.: Técnico em Informática. Sem ela, os gráficos por curso não funcionam. |
| `nota_admissao` | obrigatória | Nota do processo seletivo de ingresso. A escala (padrão 0 a 100; ou 0 a 10, 0 a 200...) é definida em Configurações e o app converte para a escala do modelo. |
| `nota_media_1sem` | obrigatória | Média das notas do 1º semestre (0 se nenhuma disciplina foi avaliada). |
| `nota_media_2sem` | obrigatória | Média das notas do 2º semestre (0 se nenhuma disciplina foi avaliada). |
| `disciplinas_aprovadas_1sem` | obrigatória | Número de disciplinas em que o aluno foi aprovado no 1º semestre. |
| `disciplinas_cursadas_1sem` | obrigatória | Número de disciplinas em que o aluno se matriculou no 1º semestre. |
| `disciplinas_aprovadas_2sem` | obrigatória | Número de disciplinas em que o aluno foi aprovado no 2º semestre. |
| `disciplinas_cursadas_2sem` | obrigatória | Número de disciplinas em que o aluno se matriculou no 2º semestre. |
| `inadimplente` | obrigatória | 1 = tem pendência financeira; 0 = não. |
| `mensalidade_em_dia` | obrigatória | 1 = mensalidade em dia; 0 = não. |
| `bolsista` | obrigatória | 1 = recebe bolsa; 0 = não. |
| `frequencia_pct` | opcional | Frequência do aluno de 0 a 100 (%). Não entra no modelo: gera o alerta de frequência baixa, comparada ao limite definido no app (padrão 75%). |
| `professores` | opcional | Logins dos professores da turma, separados por `;` (ex.: `ana.silva;joao.souza`). Define quais turmas cada professor vê. Não entra no modelo. |

- **Nomes antigos em inglês continuam aceitos** (por exemplo `Admission grade`, `Debtor`); maiúsculas, acentos e espaços extras são ignorados. Não misture os dois nomes para a mesma coluna na mesma planilha: o app recusa. Uma planilha em inglês e outra em português com o mesmo conteúdo são tratadas como repetidas.
- `turma` e `curso` não entram no modelo, mas são usadas nos filtros, na comparação com a turma e nos gráficos. Se faltarem (ou estiverem em branco em parte das linhas), o app **avisa antes de processar**. Células em branco **não apagam** a turma/curso já gravados para aquele aluno.
- Na tela de upload há ainda o campo opcional **Período de referência** (ex.: `2026/1`). Ele fica registrado no log de processamentos e, quando todas as avaliações de um aluno têm períodos diferentes, aparece como rótulo do eixo no gráfico de evolução, na lista e no histórico.
- `inadimplente`, `mensalidade_em_dia` e `bolsista` só aceitam 0 ou 1. A planilha é validada antes de gravar (as mensagens de erro usam os nomes em português): se houver erro, nada entra no banco.
- **Escala da `nota_admissao`:** o padrão é **0 a 100**. As opções, em *Configurações → Escala da nota de admissão*, são **0 a 100 (padrão)**, **0 a 10**, **0 a 200** (a escala em que o modelo foi treinado, sem conversão) e uma escala personalizada. O app **converte proporcionalmente** para 0–200 antes de calcular o risco (60 numa escala 0–100 vira 120). A configuração vale para os próximos envios; as notas já gravadas não mudam.
  - **Nota acima do máximo da escala:** a planilha não é gravada automaticamente. Se os valores cabem numa escala conhecida (por exemplo, até 190 com a escala 0–100), o upload avisa que *a planilha parece estar em 0 a 200* e mostra a caixinha **"Processar convertendo da escala de 0 a 200 (só neste envio)"**: marcando-a, a planilha é convertida e gravada, e a configuração não muda. Sem confirmar, o botão fica desabilitado. Valores negativos, ou acima de todas as escalas conhecidas, rejeitam a planilha (erro com as linhas afetadas).
  - Se muitas notas convertidas ficam abaixo de 95 (o mínimo do treino), o upload avisa que o modelo pode superestimar o risco. A conversão corrige a escala, não a distribuição das notas; a solução definitiva é retreinar com dados reais.
- **Frequência (`frequencia_pct`, opcional):** número de 0 a 100 (aceita `85`, `85,5` e `85%`; `frequencia` também funciona como cabeçalho). Ela **não entra no modelo** (que foi treinado sem frequência): serve só para o **alerta de frequência baixa**, uma regra simples que compara com o limite definido em *Configurações*. Sem a coluna, o app avisa e o alerta fica desligado só para aquele envio; planilhas antigas continuam funcionando. Se todos os valores estiverem entre 0 e 1, o app avisa que a coluna provavelmente está em fração. Quando a escola fornecer frequência real e histórica, o passo seguinte é retreinar o modelo incluindo-a.
- Não inclua idade, endereço, contato ou dados de saúde: o modelo não usa e isso só aumenta o risco com a LGPD.

### Dados de demonstração — leia antes de apresentar

Os dados em `dados/demo/` são **100% fictícios** (nomes e matrículas inventados com semente fixa) sobre as colunas numéricas do dataset público UCI (a nota de admissão dos CSVs está em 0–100, que é o dataset original dividido por 2; o app converte de volta). A **frequência também é fictícia** (gerada a partir da taxa de aprovação, com variação aleatória; cerca de 6% dos alunos são "faltosos com notas boas"), não existe no dataset original e serve só para demonstrar o alerta. Como a maior parte dessas linhas foi usada para treinar o modelo (split 80/20), os resultados na demo parecem melhores do que seriam com alunos novos — o desempenho que vale é o medido no conjunto de teste (recall de Risco Alto 0,662; F1-macro 0,638).

### Textos em português

O Streamlit não traz tradução da interface, então `app/traducao.py` injeta um pequeno script que troca no navegador os textos fixos que o app não controla ("Choose options", botão e legenda do envio de arquivo, barra e menus da tabela, menu ⋮). O botão *Deploy* e os itens de desenvolvedor do menu ficam ocultos (`toolbarMode = "viewer"` em `.streamlit/config.toml`). Um texto que não esteja na tabela de `traducao.py` continua em inglês, sem causar erro.

### Deploy no Streamlit Community Cloud

1. Publique o repositório no GitHub (o `escola.db`, o `secrets.toml` e a pasta `.venv` já estão no `.gitignore`).
2. Em [share.streamlit.io](https://share.streamlit.io), entre com a conta do GitHub e clique em **Create app → Deploy a public app from GitHub**. Escolha o repositório e a branch `main`, e em **Main file path** informe `app/dashboard.py`. As dependências vêm de `app/requirements.txt` (na mesma pasta do arquivo principal).
3. Em *Advanced settings*, escolha **Python 3.12** (3.11 ou superior) e cole em **Secrets** o conteúdo abaixo, trocando a senha por uma de 10 caracteres ou mais:

```toml
admin_login = "admin"
admin_senha = "troque-por-uma-senha-forte"
demo_automatica = true
```

4. Clique em **Deploy**. A primeira subida leva alguns minutos. Depois entre com `demo.admin`, `demo.coord`, `prof.ana` ou `prof.bruno` (senha pública `demonstracao-2026`, só dados fictícios).

Os arquivos locais do Streamlit Cloud são apagados quando o app reinicia, então o banco SQLite lá é **temporário**. Por isso o deploy serve só para a **demonstração com dados fictícios** (`demo_automatica = true` recarrega os fictícios sempre que o banco estiver vazio). **Dados reais de alunos devem rodar apenas localmente**, nunca na nuvem pública — são dados sensíveis, muitos de menores de idade (LGPD). A versão do `scikit-learn` precisa ser a mesma usada para salvar o modelo (1.8.0); se o modelo for re-treinado em outro ambiente, atualize `app/requirements.txt`.

## Próximos passos

Ver o cronograma completo no documento de Arquitetura e Plano Técnico. Em resumo, a partir daqui: publicar o repositório no GitHub e fazer o deploy de demonstração → verificar com a escola a disponibilidade de dados reais e retreinar o modelo → relatório técnico final.

## Créditos

Dataset de prototipagem: Realinho, V., Vieira Martins, M., Machado, J., Baptista, L. (2021). *Predict Students' Dropout and Academic Success* [conjunto de dados]. UCI Machine Learning Repository. https://doi.org/10.24432/C5MC89 (licença CC BY 4.0). Os dados de demonstração deste repositório são fictícios e derivados das colunas numéricas desse dataset.
