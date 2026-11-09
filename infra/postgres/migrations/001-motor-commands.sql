-- Permite os comandos do motor (injecao de falha e manutencao)
-- em bancos criados antes desta alteracao. Bancos novos ja
-- recebem a regra pelo schema.sql.
ALTER TABLE public.command_history
    DROP CONSTRAINT IF EXISTS chk_command_action;

ALTER TABLE public.command_history
    ADD CONSTRAINT chk_command_action CHECK (
        action IN ('ON', 'OFF', 'INJECT_FAULT', 'MAINTENANCE')
    );
