"""Usuários, senhas, bloqueio por tentativas e turmas dos professores (banco/usuarios.py)."""
import pytest

from banco import usuarios

SENHA = "senha-forte-123"


def test_senha_nunca_e_guardada_em_texto(caminho):
    uid = usuarios.criar_usuario("maria", "Maria", "coordenacao", SENHA, caminho=caminho)
    from banco.database import conectar
    with conectar(caminho) as c:
        guardado = c.execute("SELECT senha_hash FROM usuarios WHERE id_usuario = ?", (uid,)).fetchone()[0]
    assert SENHA not in guardado and guardado.startswith("scrypt$")
    assert usuarios.verificar_senha(SENHA, guardado) and not usuarios.verificar_senha("outra-senha-1", guardado)
    assert "senha_hash" not in usuarios.obter_usuario(uid, caminho)


def test_hash_tem_sal_aleatorio():
    assert usuarios.hash_senha(SENHA) != usuarios.hash_senha(SENHA)


@pytest.mark.parametrize("login,ok", [("prof.ana", True), ("ana", True), ("ab", False), ("Ana Silva", False),
                                      ("ana@escola", False), ("João", False), ("a" * 41, False)])
def test_login_valido(login, ok):
    assert usuarios.login_valido(login) is ok


@pytest.mark.parametrize("senha,login,trecho", [
    ("curta", None, "pelo menos 10"),
    ("          ", None, "só espaços"),
    ("prof.ana.x1", "prof.ana.x1", "igual ao login"),
    ("aaaaaaaaaaaa", None, "repetitiva"),
])
def test_senhas_fracas_sao_recusadas(senha, login, trecho):
    assert any(trecho in e for e in usuarios.erros_senha(senha, login))


def test_senha_provisoria_gerada_e_aceita():
    s = usuarios.gerar_senha_provisoria()
    assert len(s) == 12 and usuarios.erros_senha(s) == []
    assert s != usuarios.gerar_senha_provisoria()


def test_criar_usuario_valida_os_dados(caminho):
    with pytest.raises(ValueError, match="Login inválido"):
        usuarios.criar_usuario("A B", "X", "professor", SENHA, caminho=caminho)
    with pytest.raises(ValueError, match="nome"):
        usuarios.criar_usuario("ana", " ", "professor", SENHA, caminho=caminho)
    with pytest.raises(ValueError, match="Perfil"):
        usuarios.criar_usuario("ana", "Ana", "diretor", SENHA, caminho=caminho)
    with pytest.raises(ValueError, match="pelo menos"):
        usuarios.criar_usuario("ana", "Ana", "professor", "curta", caminho=caminho)
    usuarios.criar_usuario("ana", "Ana", "professor", SENHA, caminho=caminho)
    with pytest.raises(ValueError, match="Já existe"):
        usuarios.criar_usuario("ANA", "Outra", "professor", SENHA, caminho=caminho)


def test_login_correto_e_incorreto(caminho):
    usuarios.criar_usuario("ana", "Ana", "professor", SENHA, trocar_senha=True, caminho=caminho)
    u, erro = usuarios.autenticar(" ANA ", SENHA, caminho)
    assert erro is None and u["login"] == "ana" and u["trocar_senha"] is True
    assert usuarios.autenticar("ana", "errada-123456", caminho) == (None, usuarios.MENSAGEM_LOGIN_INVALIDO)


def test_mensagem_e_igual_para_login_inexistente(caminho):
    usuarios.criar_usuario("ana", "Ana", "professor", SENHA, caminho=caminho)
    assert usuarios.autenticar("ninguem", SENHA, caminho)[1] == usuarios.autenticar("ana", "errada-123456", caminho)[1]


def test_regras_documentadas_no_relatorio():
    """Valores citados no relatório (Seção 7): 5 tentativas, 15 minutos de bloqueio, senha com 10 caracteres ou mais."""
    assert (usuarios.MAX_FALHAS, usuarios.MINUTOS_BLOQUEIO, usuarios.TAMANHO_MINIMO_SENHA) == (5, 15, 10)


def test_cinco_senhas_erradas_bloqueiam_mesmo_com_a_senha_certa(caminho):
    usuarios.criar_usuario("ana", "Ana", "professor", SENHA, caminho=caminho)
    for _ in range(usuarios.MAX_FALHAS - 1):
        assert usuarios.autenticar("ana", "errada-123456", caminho)[1] == usuarios.MENSAGEM_LOGIN_INVALIDO
    assert "bloqueado" in usuarios.autenticar("ana", "errada-123456", caminho)[1]
    u, erro = usuarios.autenticar("ana", SENHA, caminho)
    assert u is None and "bloqueado" in erro
    uid = usuarios.listar_usuarios(caminho)[0]["id_usuario"]
    assert usuarios.listar_usuarios(caminho)[0]["bloqueado"] is True
    usuarios.desbloquear(uid, caminho)
    assert usuarios.autenticar("ana", SENHA, caminho)[0] is not None


def test_acerto_zera_a_contagem_de_falhas(caminho):
    usuarios.criar_usuario("ana", "Ana", "professor", SENHA, caminho=caminho)
    for _ in range(usuarios.MAX_FALHAS - 1):
        usuarios.autenticar("ana", "errada-123456", caminho)
    assert usuarios.autenticar("ana", SENHA, caminho)[0] is not None
    for _ in range(usuarios.MAX_FALHAS - 1):
        usuarios.autenticar("ana", "errada-123456", caminho)
    assert usuarios.autenticar("ana", SENHA, caminho)[0] is not None   # ainda não bloqueou


def test_usuario_inativo_nao_entra(caminho):
    uid = usuarios.criar_usuario("ana", "Ana", "professor", SENHA, caminho=caminho)
    usuarios.criar_usuario("adm", "Adm", "admin", SENHA, caminho=caminho)
    usuarios.atualizar_usuario(uid, "Ana", "professor", False, caminho)
    assert usuarios.autenticar("ana", SENHA, caminho) == (None, usuarios.MENSAGEM_LOGIN_INVALIDO)


def test_sempre_sobra_um_administrador_ativo(caminho):
    adm = usuarios.criar_usuario("adm", "Adm", "admin", SENHA, caminho=caminho)
    with pytest.raises(ValueError, match="administrador ativo"):
        usuarios.atualizar_usuario(adm, "Adm", "coordenacao", True, caminho)
    with pytest.raises(ValueError, match="administrador ativo"):
        usuarios.atualizar_usuario(adm, "Adm", "admin", False, caminho)
    outro = usuarios.criar_usuario("adm2", "Adm 2", "admin", SENHA, caminho=caminho)
    usuarios.atualizar_usuario(adm, "Adm", "coordenacao", True, caminho)   # agora pode
    assert usuarios.obter_usuario(outro, caminho)["perfil"] == "admin"


def test_senha_provisoria_obriga_troca_e_a_troca_exige_a_senha_atual(caminho):
    uid = usuarios.criar_usuario("ana", "Ana", "professor", SENHA, caminho=caminho)
    usuarios.definir_senha(uid, "nova-senha-456", provisoria=True, caminho=caminho)
    assert usuarios.autenticar("ana", "nova-senha-456", caminho)[0]["trocar_senha"] is True
    with pytest.raises(ValueError, match="atual está incorreta"):
        usuarios.trocar_propria_senha(uid, "errada", "outra-senha-789", caminho)
    with pytest.raises(ValueError, match="diferente da atual"):
        usuarios.trocar_propria_senha(uid, "nova-senha-456", "nova-senha-456", caminho)
    usuarios.trocar_propria_senha(uid, "nova-senha-456", "outra-senha-789", caminho)
    u, _ = usuarios.autenticar("ana", "outra-senha-789", caminho)
    assert u["trocar_senha"] is False
    assert usuarios.autenticar("ana", "nova-senha-456", caminho)[0] is None


def test_definir_senha_desbloqueia(caminho):
    uid = usuarios.criar_usuario("ana", "Ana", "professor", SENHA, caminho=caminho)
    for _ in range(usuarios.MAX_FALHAS):
        usuarios.autenticar("ana", "errada-123456", caminho)
    usuarios.definir_senha(uid, "nova-senha-456", caminho=caminho)
    assert usuarios.autenticar("ana", "nova-senha-456", caminho)[0] is not None


def test_admin_inicial_so_e_criado_uma_vez(caminho):
    assert usuarios.garantir_admin_inicial("admin.escola", SENHA, caminho=caminho) is True
    assert usuarios.garantir_admin_inicial("outro.admin", SENHA, caminho=caminho) is False
    assert usuarios.contar_usuarios(caminho) == 1
    u = usuarios.autenticar("admin.escola", SENHA, caminho)[0]
    assert u["perfil"] == "admin" and u["trocar_senha"] is True


def test_turmas_do_professor_vem_da_planilha(banco_com_envio):
    caminho = banco_com_envio
    assert usuarios.turmas_do_professor("prof.ana", caminho) == ["1º A"]
    assert usuarios.turmas_do_professor("PROF.BRUNO", caminho) == ["1º A", "2º B"]   # 1º A tem os dois professores
    assert usuarios.turmas_do_professor("prof.zeca", caminho) == []
    usuarios.criar_usuario("prof.ana", "Ana", "professor", SENHA, caminho=caminho)
    assert usuarios.autenticar("prof.ana", SENHA, caminho)[0]["turmas"] == ["1º A"]


def test_logins_da_planilha_sem_usuario(banco_com_envio):
    caminho = banco_com_envio
    assert usuarios.logins_sem_usuario(caminho) == ["prof.ana", "prof.bruno"]
    usuarios.criar_usuario("prof.ana", "Ana", "professor", SENHA, caminho=caminho)
    assert usuarios.logins_sem_usuario(caminho) == ["prof.bruno"]
    assert usuarios.logins_desconhecidos(["PROF.ANA", "prof.x"], caminho) == ["prof.x"]
