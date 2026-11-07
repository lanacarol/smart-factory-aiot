
def atualizar_ventilador(temperatura, ligado):
    if temperatura > 35:
        return True
    elif temperatura < 30:
        return False
    return ligado


cenarios = [
    (32.0, False),
    (36.0, True),
    (33.0, True),
    (29.0, False),
]

estado = False

for temperatura, esperado in cenarios:
    estado = atualizar_ventilador(temperatura, estado)

    print(
        f"Temperatura: {temperatura:.1f} C | "
        f"Ventilador: {'ON' if estado else 'OFF'}"
    )

    assert estado == esperado, (
        f"Erro na temperatura {temperatura}"
    )

print("Todos os testes passaram!")
