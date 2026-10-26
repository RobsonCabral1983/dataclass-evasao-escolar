"""
Usuários do app: login e senha próprios, três perfis e bloqueio por tentativas erradas.

- As senhas NUNCA são guardadas em texto: só o hash (scrypt, da biblioteca padrão, com sal aleatório).
- Perfis: admin (tudo, inclusive usuários e configurações), coordenacao (todos os alunos, upload, divergências,
  relatórios) e professor (só os alunos das turmas em que ele aparece na coluna "professores" da planilha).
- 5 senhas erradas seguidas bloqueiam o usuário por 15 minutos (o admin pode desbloquear antes).
- Uma senha provisória (criada ou redefinida pelo admin) obriga a troca no primeiro acesso.

Também funciona como script, para criar o primeiro admin ou redefinir uma senha esquecida:
    python -m banco.usuarios criar <login> "<Nome>" admin
    python -m banco.usuarios redefinir <login>
    python -m banco.usuarios listar
"""
import hashlib
import hmac
import os
import re
import secrets
import sys

try:
    from .database import conectar, CAMINHO_BANCO
except ImportError:  # uso como script dentro da pasta banco/
    from database import conectar, CAMINHO_BANCO

PERFIS = {"admin": "Administrador", "coordenacao": "Coordenação", "professor": "Professor"}
TAMANHO_MINIMO_SENHA = 10
MAX_FALHAS = 5
MINUTOS_BLOQUEIO = 15
_REGEX_LOGIN = re.compile(r"^[a-z0-9._-]{3,40}$")
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
MENSAGEM_LOGIN_INVALIDO = "Login ou senha incorretos."


# ------------------------------------------------------------------------------------------------ senhas
def normalizar_login(login):
    return str(login or "").strip().lower()


def login_valido(login):
    """Login: 3 a 40 caracteres entre letras minúsculas, números, ponto, sublinhado e hífen (sem espaços nem acentos)."""
    return bool(_REGEX_LOGIN.match(normalizar_login(login)))


def hash_senha(senha):
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode("utf-8"), salt=sal, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${sal.hex()}${h.hex()}"


def verificar_senha(senha, guardado):
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calculado = hashlib.scrypt(senha.encode("utf-8"), salt=bytes.fromhex(sal), dklen=32, n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(calculado.hex(), h)
    except Exception:  # noqa: BLE001
        return False


_HASH_FALSO = None


def _gastar_tempo_de_hash(senha):
    """Login inexistente leva o mesmo tempo que um existente (não revela quais logins existem)."""
    global _HASH_FALSO
    if _HASH_FALSO is None:
        _HASH_FALSO = hash_senha("x" * 16)
    verificar_senha(senha, _HASH_FALSO)


def erros_senha(senha, login=None):
    """Lista de problemas da senha (vazia = aceita)."""
    erros = []
    if len(senha or "") < TAMANHO_MINIMO_SENHA:
        erros.append(f"A senha deve ter pelo menos {TAMANHO_MINIMO_SENHA} caracteres.")
    if senha and not senha.strip():
        erros.append("A senha não pode ser só espaços.")
    if login and senha and senha.lower() == normalizar_login(login):
        erros.append("A senha não pode ser igual ao login.")
    if senha and len(set(senha)) < 4:
        erros.append("A senha é muito repetitiva.")
    return erros


def gerar_senha_provisoria():
    """Senha aleatória fácil de ditar (sem caracteres que se confundem), mostrada uma única vez ao admin."""
    alfabeto = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alfabeto) for _ in range(12))


# ------------------------------------------------------------------------------------------------ cadastro
def _publico(linha):
    d = dict(linha)
    d.pop("senha_hash", None)
    d["ativo"] = bool(d["ativo"])
    d["trocar_senha"] = bool(d["trocar_senha"])
    return d


def contar_usuarios(caminho=CAMINHO_BANCO):
    with conectar(caminho) as c:
        return c.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]


def _admins_ativos(c, exceto=None):
    return c.execute("SELECT COUNT(*) FROM usuarios WHERE perfil = 'admin' AND ativo = 1 AND id_usuario IS NOT ?", (exceto,)).fetchone()[0]


def criar_usuario(login, nome, perfil, senha, trocar_senha=True, caminho=CAMINHO_BANCO):
    """Cria o usuário (levanta ValueError com a mensagem a mostrar). Devolve o id."""
    login, nome = normalizar_login(login), str(nome or "").strip()
    if not login_valido(login):
        raise ValueError("Login inválido: use de 3 a 40 letras minúsculas, números, ponto, sublinhado ou hífen, sem espaços.")
    if not nome:
        raise ValueError("Informe o nome da pessoa.")
    if perfil not in PERFIS:
        raise ValueError("Perfil inválido.")
    erros = erros_senha(senha, login)
    if erros:
        raise ValueError(" ".join(erros))
    with conectar(caminho) as c:
        if c.execute("SELECT 1 FROM usuarios WHERE login = ?", (login,)).fetchone():
            raise ValueError(f"Já existe um usuário com o login '{login}'.")
        return c.execute(
            "INSERT INTO usuarios (login, nome, perfil, senha_hash, trocar_senha) VALUES (?, ?, ?, ?, ?)",
            (login, nome, perfil, hash_senha(senha), 1 if trocar_senha else 0)).lastrowid


def listar_usuarios(caminho=CAMINHO_BANCO):
    """Todos os usuários (sem o hash), com `bloqueado` (bool) e `turmas` (turmas vigentes dos professores)."""
    with conectar(caminho) as c:
        linhas = c.execute(
            "SELECT *, (bloqueado_ate IS NOT NULL AND bloqueado_ate > datetime('now')) AS bloqueado FROM usuarios ORDER BY perfil, nome"
        ).fetchall()
        vigentes = _atribuicoes_vigentes(c)
    resultado = []
    for l in linhas:
        d = _publico(l)
        d["bloqueado"] = bool(d["bloqueado"])
        d["turmas"] = sorted(t for t, logins in vigentes.items() if d["login"].lower() in logins) if d["perfil"] == "professor" else []
        resultado.append(d)
    return resultado


def obter_usuario(id_usuario, caminho=CAMINHO_BANCO):
    with conectar(caminho) as c:
        l = c.execute("SELECT *, (bloqueado_ate IS NOT NULL AND bloqueado_ate > datetime('now')) AS bloqueado FROM usuarios WHERE id_usuario = ?",
                      (id_usuario,)).fetchone()
        if not l:
            return None
        d = _publico(l)
        d["bloqueado"] = bool(d["bloqueado"])
        d["turmas"] = sorted(t for t, logins in _atribuicoes_vigentes(c).items() if d["login"].lower() in logins) if d["perfil"] == "professor" else []
        return d


def atualizar_usuario(id_usuario, nome, perfil, ativo, caminho=CAMINHO_BANCO):
    """Altera nome, perfil e situação. Não deixa o sistema sem nenhum administrador ativo."""
    nome = str(nome or "").strip()
    if not nome:
        raise ValueError("Informe o nome da pessoa.")
    if perfil not in PERFIS:
        raise ValueError("Perfil inválido.")
    with conectar(caminho) as c:
        if not c.execute("SELECT 1 FROM usuarios WHERE id_usuario = ?", (id_usuario,)).fetchone():
            raise ValueError("Usuário não encontrado.")
        if (perfil != "admin" or not ativo) and _admins_ativos(c, exceto=id_usuario) == 0:
            raise ValueError("É preciso manter pelo menos um administrador ativo.")
        c.execute("UPDATE usuarios SET nome = ?, perfil = ?, ativo = ? WHERE id_usuario = ?", (nome, perfil, 1 if ativo else 0, id_usuario))


def definir_senha(id_usuario, nova_senha, provisoria=True, caminho=CAMINHO_BANCO):
    """Define a senha (e limpa bloqueio). `provisoria=True` obriga a troca no próximo acesso."""
    with conectar(caminho) as c:
        l = c.execute("SELECT login FROM usuarios WHERE id_usuario = ?", (id_usuario,)).fetchone()
        if not l:
            raise ValueError("Usuário não encontrado.")
        erros = erros_senha(nova_senha, l["login"])
        if erros:
            raise ValueError(" ".join(erros))
        c.execute("UPDATE usuarios SET senha_hash = ?, trocar_senha = ?, tentativas_falhas = 0, bloqueado_ate = NULL WHERE id_usuario = ?",
                  (hash_senha(nova_senha), 1 if provisoria else 0, id_usuario))


def trocar_propria_senha(id_usuario, senha_atual, nova_senha, caminho=CAMINHO_BANCO):
    """O próprio usuário troca a senha (precisa da atual). Levanta ValueError com a mensagem a mostrar."""
    with conectar(caminho) as c:
        l = c.execute("SELECT login, senha_hash FROM usuarios WHERE id_usuario = ?", (id_usuario,)).fetchone()
        if not l or not verificar_senha(senha_atual or "", l["senha_hash"]):
            raise ValueError("A senha atual está incorreta.")
        if nova_senha == senha_atual:
            raise ValueError("A nova senha deve ser diferente da atual.")
        erros = erros_senha(nova_senha, l["login"])
        if erros:
            raise ValueError(" ".join(erros))
        c.execute("UPDATE usuarios SET senha_hash = ?, trocar_senha = 0 WHERE id_usuario = ?", (hash_senha(nova_senha), id_usuario))


def desbloquear(id_usuario, caminho=CAMINHO_BANCO):
    with conectar(caminho) as c:
        c.execute("UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = NULL WHERE id_usuario = ?", (id_usuario,))


# ------------------------------------------------------------------------------------------------ entrada
def autenticar(login, senha, caminho=CAMINHO_BANCO):
    """
    Confere login e senha. Devolve (usuario, None) se entrou ou (None, mensagem). Conta as falhas e bloqueia
    por 15 minutos na 5ª seguida. A mensagem de erro é a mesma para login inexistente, senha errada e usuário inativo.
    """
    login = normalizar_login(login)
    with conectar(caminho) as c:
        l = c.execute("SELECT *, (bloqueado_ate IS NOT NULL AND bloqueado_ate > datetime('now')) AS bloqueado FROM usuarios WHERE login = ?",
                      (login,)).fetchone()
        if not l:
            _gastar_tempo_de_hash(senha or "")
            return None, MENSAGEM_LOGIN_INVALIDO
        if l["bloqueado"]:
            return None, f"Usuário bloqueado por tentativas incorretas. Tente de novo em até {MINUTOS_BLOQUEIO} minutos ou peça ao administrador para desbloquear."
        if not verificar_senha(senha or "", l["senha_hash"]):
            falhas = l["tentativas_falhas"] + 1
            if falhas >= MAX_FALHAS:
                c.execute("UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = datetime('now', ?) WHERE id_usuario = ?",
                          (f"+{MINUTOS_BLOQUEIO} minutes", l["id_usuario"]))
                return None, f"Muitas tentativas incorretas: usuário bloqueado por {MINUTOS_BLOQUEIO} minutos."
            c.execute("UPDATE usuarios SET tentativas_falhas = ? WHERE id_usuario = ?", (falhas, l["id_usuario"]))
            return None, MENSAGEM_LOGIN_INVALIDO
        if not l["ativo"]:
            return None, MENSAGEM_LOGIN_INVALIDO
        c.execute("UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = NULL, ultimo_acesso = datetime('now') WHERE id_usuario = ?",
                  (l["id_usuario"],))
    return obter_usuario(l["id_usuario"], caminho), None


def garantir_admin_inicial(login, senha, nome="Administrador", caminho=CAMINHO_BANCO):
    """Se ainda não há nenhum usuário, cria o administrador inicial (a senha dos Secrets, com troca obrigatória). Devolve True se criou."""
    if contar_usuarios(caminho):
        return False
    criar_usuario(login, nome, "admin", senha, trocar_senha=True, caminho=caminho)
    return True


# ------------------------------------------------------------------------------------------------ turmas dos professores
def _atribuicoes_vigentes(c):
    """{turma: {logins em minúsculas}} do último envio que trouxe a coluna de professores."""
    ultimo = c.execute("SELECT MAX(id_processamento) FROM turmas_professores").fetchone()[0]
    if ultimo is None:
        return {}
    vigentes = {}
    for l in c.execute("SELECT turma, login FROM turmas_professores WHERE id_processamento = ?", (ultimo,)):
        vigentes.setdefault(l["turma"], set()).add(l["login"].lower())
    return vigentes


def turmas_do_professor(login, caminho=CAMINHO_BANCO):
    """Turmas vigentes do professor (lista ordenada)."""
    login = normalizar_login(login)
    with conectar(caminho) as c:
        return sorted(t for t, logins in _atribuicoes_vigentes(c).items() if login in logins)


def logins_sem_usuario(caminho=CAMINHO_BANCO):
    """Logins que a planilha vigente atribui a turmas mas que ainda não têm usuário cadastrado."""
    with conectar(caminho) as c:
        usados = {lg for logins in _atribuicoes_vigentes(c).values() for lg in logins}
        existentes = {l[0].lower() for l in c.execute("SELECT login FROM usuarios")}
    return sorted(usados - existentes)


def logins_desconhecidos(logins, caminho=CAMINHO_BANCO):
    """Dos logins informados, os que não têm usuário cadastrado (para avisar no upload)."""
    with conectar(caminho) as c:
        existentes = {l[0].lower() for l in c.execute("SELECT login FROM usuarios")}
    return sorted({normalizar_login(l) for l in logins} - existentes)


# ------------------------------------------------------------------------------------------------ script
def _principal(argv):
    import getpass
    if len(argv) < 2 or argv[1] not in ("criar", "redefinir", "listar"):
        print(__doc__)
        return 1
    if argv[1] == "listar":
        for u in listar_usuarios():
            print(f"{u['login']:<20} {PERFIS[u['perfil']]:<14} {'ativo' if u['ativo'] else 'INATIVO'}{' (bloqueado)' if u['bloqueado'] else ''}")
        return 0
    if argv[1] == "criar":
        if len(argv) != 5:
            print('Uso: python -m banco.usuarios criar <login> "<Nome>" <admin|coordenacao|professor>')
            return 1
        senha = getpass.getpass("Senha provisória: ")
        criar_usuario(argv[2], argv[3], argv[4], senha)
        print("Usuário criado (a troca de senha será pedida no primeiro acesso).")
        return 0
    login = normalizar_login(argv[2] if len(argv) > 2 else "")
    usuario = next((u for u in listar_usuarios() if u["login"] == login), None)
    if not usuario:
        print("Usuário não encontrado.")
        return 1
    definir_senha(usuario["id_usuario"], getpass.getpass("Nova senha provisória: "))
    print("Senha redefinida e usuário desbloqueado (a troca será pedida no próximo acesso).")
    return 0


if __name__ == "__main__":
    sys.exit(_principal(sys.argv))
