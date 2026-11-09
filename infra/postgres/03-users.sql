
-- SMART FACTORY AIoT
-- Cadastro de usuarios e controle de acesso

CREATE TABLE IF NOT EXISTS app_users (
    id BIGSERIAL PRIMARY KEY,

    username VARCHAR(80)
        UNIQUE NOT NULL,

    password_hash TEXT NOT NULL,

    role VARCHAR(20) NOT NULL,

    active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_user_role
        CHECK (
            role IN (
                'admin',
                'operator',
                'viewer'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_app_users_role
    ON app_users(role);
