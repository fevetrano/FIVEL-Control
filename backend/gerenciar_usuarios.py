"""Cadastro de usuários do FIVEL Control pelo terminal.

Exemplos (rodar dentro da pasta backend):
    python gerenciar_usuarios.py criar --nome "Fernando" --login fernando --perfil admin
    python gerenciar_usuarios.py criar --nome "Escritório" --login escritorio --perfil vendas
    python gerenciar_usuarios.py senha --login escritorio
    python gerenciar_usuarios.py desativar --login escritorio
    python gerenciar_usuarios.py ativar --login escritorio
    python gerenciar_usuarios.py listar

A senha é pedida sem aparecer na tela.
"""
import argparse
import getpass
import sys

import auth


def pedir_senha():
    senha = getpass.getpass("Senha: ")
    if senha != getpass.getpass("Repita a senha: "):
        sys.exit("As senhas não conferem.")
    return senha


def main():
    parser = argparse.ArgumentParser(description="Usuários do FIVEL Control")
    sub = parser.add_subparsers(dest="comando", required=True)

    criar = sub.add_parser("criar", help="Cria um usuário")
    criar.add_argument("--nome", required=True)
    criar.add_argument("--login", required=True)
    criar.add_argument("--perfil", required=True, choices=auth.PERFIS)

    for comando, ajuda in (("senha", "Troca a senha"), ("desativar", "Bloqueia o acesso"), ("ativar", "Libera o acesso")):
        p = sub.add_parser(comando, help=ajuda)
        p.add_argument("--login", required=True)

    sub.add_parser("listar", help="Lista os usuários")

    args = parser.parse_args()
    auth.init_tabelas()

    try:
        if args.comando == "criar":
            auth.criar_usuario(args.nome, args.login, pedir_senha(), args.perfil)
            auth.registrar_auditoria("terminal", "usuario_criado", {"login": args.login, "perfil": args.perfil})
            print(f"Usuário '{args.login}' criado com perfil {args.perfil}.")
        elif args.comando == "senha":
            auth.alterar_senha(args.login, pedir_senha())
            auth.registrar_auditoria("terminal", "senha_alterada", {"login": args.login})
            print(f"Senha de '{args.login}' alterada. As sessões abertas foram encerradas.")
        elif args.comando in ("desativar", "ativar"):
            auth.definir_ativo(args.login, args.comando == "ativar")
            auth.registrar_auditoria("terminal", f"usuario_{args.comando}", {"login": args.login})
            print(f"Usuário '{args.login}' {'ativado' if args.comando == 'ativar' else 'desativado'}.")
        else:
            usuarios = auth.listar_usuarios()
            if not usuarios:
                print("Nenhum usuário cadastrado.")
            for u in usuarios:
                print(f"{u['login']:<20} {u['perfil']:<8} {'ativo' if u['ativo'] else 'INATIVO':<8} {u['nome']}")
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
