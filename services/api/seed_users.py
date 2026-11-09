
import asyncio
import getpass
import os

import asyncpg
from pwdlib import PasswordHash


USERS = [
    ("admin", "admin"),
    ("operador", "operator"),
    ("visualizador", "viewer"),
]

hasher = PasswordHash.recommended()


async def main():
    database = os.environ.get("POSTGRES_DB")

    if database != "smart_factory_dev":
        raise RuntimeError(
            "Operacao permitida somente no "
            "banco smart_factory_dev."
        )

    print("\nSMART FACTORY - CADASTRO DE USUARIOS")
    print("Banco:", database)
    print("As senhas nao aparecem na tela.\n")

    connection = await asyncpg.connect(
        host=os.environ["POSTGRES_HOST"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=database,
    )

    try:
        for username, role in USERS:
            print(f"\nUsuario: {username}")
            print(f"Perfil: {role}")

            while True:
                password = getpass.getpass(
                    "Digite a senha: "
                )

                confirmation = getpass.getpass(
                    "Confirme a senha: "
                )

                if len(password) < 12:
                    print(
                        "Use pelo menos 12 caracteres."
                    )
                    continue

                if password != confirmation:
                    print(
                        "As senhas nao conferem."
                    )
                    continue

                break

            password_hash = hasher.hash(password)

            await connection.execute(
                """
                INSERT INTO app_users (
                    username,
                    password_hash,
                    role,
                    active
                )
                VALUES ($1, $2, $3, TRUE)
                ON CONFLICT (username)
                DO UPDATE SET
                    password_hash =
                        EXCLUDED.password_hash,
                    role = EXCLUDED.role,
                    active = TRUE
                """,
                username,
                password_hash,
                role,
            )

            print(
                f"Usuario {username} cadastrado!"
            )

        print("\nTodos os usuarios foram cadastrados.")

    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
