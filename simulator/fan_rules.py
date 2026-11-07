
def atualizar_ventilador(temperatura: float, ligado: bool) -> bool:
    if temperatura > 35:
        return True
    if temperatura < 30:
        return False
    return ligado
