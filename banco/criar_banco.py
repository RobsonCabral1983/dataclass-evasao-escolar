"""
Cria o banco de dados SQLite do projeto (escola.db), com as três tabelas
que sustentam o dashboard: alunos, avaliacoes_risco, processamentos e acoes_pedagogicas.
Bancos antigos são atualizados automaticamente (função migrar), sem perder dados.

Como rodar:
    python banco/criar_banco.py

É seguro rodar mais de uma vez: usa "CREATE TABLE IF NOT EXISTS", então
não apaga nem duplica dados já existentes.
"""

import sqlite3
import os

CAMINHO_BANCO = os.path.join(os.path.dirname(__file__), "escola.db")


SCHEMA = """
-- Dados de identificação do aluno, separados dos dados de risco.
-- Nenhuma outra tabela guarda nome: elas se referem ao aluno só por id_aluno.
CREATE TABLE IF NOT EXISTS alunos (
    id_aluno INTEGER PRIMARY KEY AUTOINCREMENT,
    matricula TEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    turma TEXT,
    curso TEXT,
    data_cadastro TEXT NOT NULL DEFAULT (datetime('now')),
    anonimizado_em TEXT  -- preenchido quando o aluno é anonimizado pela política de retenção
);

-- Uma linha por avaliação de risco. Nunca sobrescrita: a cada novo
-- processamento de planilha, novas linhas são inseridas, preservando
-- o histórico de cada aluno ao longo do tempo.
CREATE TABLE IF NOT EXISTS avaliacoes_risco (
    id_avaliacao INTEGER PRIMARY KEY AUTOINCREMENT,
    id_aluno INTEGER NOT NULL,
    id_processamento INTEGER,  -- planilha (lote) em que esta avaliação foi gerada
    data_avaliacao TEXT NOT NULL DEFAULT (datetime('now')),
    nota_admissao REAL,
    nota_1sem REAL,
    nota_2sem REAL,
    taxa_aprovacao_1sem REAL,
    taxa_aprovacao_2sem REAL,
    indicador_socioeconomico REAL,
    frequencia_pct REAL,  -- opcional (0 a 100); não entra no modelo, só no alerta de frequência baixa
    risco TEXT NOT NULL CHECK (risco IN ('Risco Alto', 'Risco Médio', 'Risco Baixo')),
    modelo_versao TEXT,
    FOREIGN KEY (id_aluno) REFERENCES alunos (id_aluno)
);

-- Log de auditoria: um registro por lote de CSV processado.
CREATE TABLE IF NOT EXISTS processamentos (
    id_processamento INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL DEFAULT (datetime('now')),
    nome_arquivo_origem TEXT,
    quantidade_alunos INTEGER,
    hash_conteudo TEXT,  -- impressão digital do conteúdo da planilha (detecta envio repetido)
    periodo_referencia TEXT  -- opcional: a que período os dados se referem (ex.: 2026/1)
);

CREATE INDEX IF NOT EXISTS idx_avaliacoes_id_aluno ON avaliacoes_risco (id_aluno);
CREATE INDEX IF NOT EXISTS idx_avaliacoes_data ON avaliacoes_risco (data_avaliacao);
"""

# Ações pedagógicas registradas pela equipe (conversa com a família, reforço etc.). Fica à parte do SCHEMA
# principal para que `migrar` também a crie em bancos de versões anteriores.
# Divergências (aluno ausente da última planilha) que a equipe já conferiu. A resolução vale para UMA ausência: fica ligada
# ao primeiro envio em que o aluno ficou de fora; se ele voltar e sumir de novo, a nova ausência é pendente.
SCHEMA_DIVERGENCIAS = """
CREATE TABLE IF NOT EXISTS divergencias_resolvidas (
    id_resolucao INTEGER PRIMARY KEY AUTOINCREMENT,
    id_aluno INTEGER NOT NULL,
    id_proc_ausencia INTEGER NOT NULL,   -- primeiro envio (processamento) em que o aluno ficou de fora
    motivo TEXT NOT NULL,
    responsavel TEXT NOT NULL,           -- quem registrou (o app não tem login por pessoa)
    resolvido_em TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (id_aluno) REFERENCES alunos (id_aluno)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_resolucao_unica ON divergencias_resolvidas (id_aluno, id_proc_ausencia);
"""

# Valores de nome/turma/curso que um envio SOBRESCREVEU (para o "desfazer" poder restaurá-los).
SCHEMA_ALTERACOES = """
CREATE TABLE IF NOT EXISTS alunos_alteracoes (
    id_alteracao INTEGER PRIMARY KEY AUTOINCREMENT,
    id_processamento INTEGER NOT NULL,
    id_aluno INTEGER NOT NULL,
    nome_anterior TEXT NOT NULL,
    turma_anterior TEXT,
    curso_anterior TEXT,
    FOREIGN KEY (id_aluno) REFERENCES alunos (id_aluno)
);
CREATE INDEX IF NOT EXISTS idx_alteracoes_processamento ON alunos_alteracoes (id_processamento);
"""

# Usuários do app (login próprio, senha só como hash) e a relação turma -> professores que vem da coluna
# "professores" da planilha. A relação guarda o LOGIN em texto: vale mesmo que o usuário seja criado depois, e cada
# envio é guardado separadamente (a vigente é a do último envio que trouxe a coluna), o que permite desfazer.
SCHEMA_USUARIOS = """
CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nome TEXT NOT NULL,
    perfil TEXT NOT NULL CHECK (perfil IN ('admin', 'coordenacao', 'professor')),
    senha_hash TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1,
    trocar_senha INTEGER NOT NULL DEFAULT 1,
    tentativas_falhas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    ultimo_acesso TEXT
);
CREATE TABLE IF NOT EXISTS turmas_professores (
    id_processamento INTEGER NOT NULL,
    turma TEXT NOT NULL,
    login TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (id_processamento, turma, login)
);
CREATE INDEX IF NOT EXISTS idx_turmas_prof_login ON turmas_professores (login);
"""

SCHEMA_AUDITORIA = """
-- Trilha de auditoria: quem fez o quê e quando (abertura de ficha, login, envio de planilha, exclusões, gestão de usuários).
-- Guarda uma "foto" do usuário e do aluno no momento do evento (login, nome e matrícula em texto), então o registro continua
-- legível mesmo que o usuário seja desativado ou o aluno seja removido. NUNCA é apagada ao reiniciar os dados dos alunos.
-- A data é gravada em UTC (datetime('now')).
CREATE TABLE IF NOT EXISTS auditoria (
    id_evento INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL DEFAULT (datetime('now')),
    id_usuario INTEGER,
    login TEXT,
    nome_usuario TEXT,
    perfil TEXT,
    evento TEXT NOT NULL,
    id_aluno INTEGER,
    matricula TEXT,
    nome_aluno TEXT,
    detalhe TEXT
);
CREATE INDEX IF NOT EXISTS idx_auditoria_data ON auditoria (data_hora);
CREATE INDEX IF NOT EXISTS idx_auditoria_login ON auditoria (login);
CREATE INDEX IF NOT EXISTS idx_auditoria_matricula ON auditoria (matricula);
"""

SCHEMA_CONFIG = """
-- Regras da instituição que o usuário pode alterar no app (hoje: limite de frequência). Não é apagada ao reiniciar os dados.
CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

SCHEMA_ACOES = """
-- Uma linha por ação pedagógica. O texto livre pode conter dado sensível de menor (LGPD):
-- só a ficha do aluno o exibe, e cada ação pode ser excluída.
CREATE TABLE IF NOT EXISTS acoes_pedagogicas (
    id_acao INTEGER PRIMARY KEY AUTOINCREMENT,
    id_aluno INTEGER NOT NULL,
    data_acao TEXT NOT NULL,          -- data em que a ação aconteceu (AAAA-MM-DD)
    tipo TEXT NOT NULL,
    descricao TEXT NOT NULL,
    responsavel TEXT NOT NULL,        -- quem registrou (o app não tem login por pessoa)
    registrado_em TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (id_aluno) REFERENCES alunos (id_aluno)
);
CREATE INDEX IF NOT EXISTS idx_acoes_id_aluno ON acoes_pedagogicas (id_aluno);
"""


def migrar(conexao):
    """
    Atualiza bancos criados por versões anteriores (sem as colunas id_processamento,
    hash_conteudo, periodo_referencia e frequencia_pct, nem as tabelas de ações pedagógicas, configurações, divergências resolvidas, alterações de alunos, usuários, turmas dos professores e trilha de auditoria). Idempotente: só altera o que ainda não existe e nunca apaga dados.
    """
    def colunas(tabela):
        return {linha[1] for linha in conexao.execute(f"PRAGMA table_info({tabela})")}

    if "id_processamento" not in colunas("avaliacoes_risco"):
        conexao.execute("ALTER TABLE avaliacoes_risco ADD COLUMN id_processamento INTEGER")
    if "hash_conteudo" not in colunas("processamentos"):
        conexao.execute("ALTER TABLE processamentos ADD COLUMN hash_conteudo TEXT")
    if "periodo_referencia" not in colunas("processamentos"):
        conexao.execute("ALTER TABLE processamentos ADD COLUMN periodo_referencia TEXT")
    if "anonimizado_em" not in colunas("alunos"):
        conexao.execute("ALTER TABLE alunos ADD COLUMN anonimizado_em TEXT")   # preenchido quando o aluno é anonimizado (política de retenção)
    if "frequencia_pct" not in colunas("avaliacoes_risco"):
        conexao.execute("ALTER TABLE avaliacoes_risco ADD COLUMN frequencia_pct REAL")
    conexao.execute("CREATE INDEX IF NOT EXISTS idx_avaliacoes_processamento ON avaliacoes_risco (id_processamento)")
    conexao.executescript(SCHEMA_ACOES)
    conexao.executescript(SCHEMA_CONFIG)
    conexao.executescript(SCHEMA_DIVERGENCIAS)
    conexao.executescript(SCHEMA_ALTERACOES)
    conexao.executescript(SCHEMA_USUARIOS)
    conexao.executescript(SCHEMA_AUDITORIA)


def criar_banco(caminho=CAMINHO_BANCO):
    conexao = sqlite3.connect(caminho)
    try:
        conexao.executescript(SCHEMA)
        migrar(conexao)
        conexao.commit()
    finally:
        conexao.close()
    print(f"Banco criado/atualizado em: {caminho}")


if __name__ == "__main__":
    criar_banco()
