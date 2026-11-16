from sqlalchemy import text
from sqlalchemy.engine import Engine

MIGRATIONS = [
    """
    ALTER TABLE device_commands
    ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP WITH TIME ZONE
    """,
    """
    ALTER TABLE telemetry
    ADD COLUMN IF NOT EXISTS connection_type VARCHAR
    """,
    """
    ALTER TABLE telemetry
    ADD COLUMN IF NOT EXISTS raw_payload BYTEA
    """,
    """
    ALTER TABLE telemetry
    ADD COLUMN IF NOT EXISTS decode_activation_id INTEGER
    REFERENCES decode_schema_activations(id) ON DELETE SET NULL
    """,
    # Revoke Organization Access / Revoke Collaborator
    """
    ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE
    """,
    # Collaborator roles created by admins
    """
    ALTER TABLE collaborator_permissions
    ADD COLUMN IF NOT EXISTS role_id INTEGER
    REFERENCES collaborator_roles(id) ON DELETE RESTRICT
    """,
    # Decoders owned by an organization (NULL = platform decoder).
    """
    ALTER TABLE decode_schemas
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER
    """,
    """
    ALTER TABLE decode_schemas
    DROP CONSTRAINT IF EXISTS uq_decode_schemas_name_version
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_decode_schemas_tenant_name_version
    ON decode_schemas (COALESCE(tenant_id, 0), name, version)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_decode_schemas_tenant_id
    ON decode_schemas (tenant_id)
    """,
    # JavaScript decoders (DecoderDefinition.code) and DecoderMatch
    """
    ALTER TABLE decode_schemas
    ADD COLUMN IF NOT EXISTS kind VARCHAR NOT NULL DEFAULT 'fields'
    """,
    "ALTER TABLE decode_schemas ADD COLUMN IF NOT EXISTS code TEXT",
    "ALTER TABLE decode_schemas ADD COLUMN IF NOT EXISTS match_provider_id VARCHAR",
    "ALTER TABLE decode_schemas ADD COLUMN IF NOT EXISTS match_protocol_id VARCHAR",
    "ALTER TABLE decode_schemas ADD COLUMN IF NOT EXISTS match_device_type_id VARCHAR",
    "ALTER TABLE decode_schemas ADD COLUMN IF NOT EXISTS match_message_type VARCHAR",
    "ALTER TABLE decode_schemas ADD COLUMN IF NOT EXISTS match_version VARCHAR",
    # IncomingMessage attributes kept for reprocessing, and the decoder used
    "ALTER TABLE decoded_messages ADD COLUMN IF NOT EXISTS message_ref VARCHAR",
    "ALTER TABLE decoded_messages ADD COLUMN IF NOT EXISTS remote_port INTEGER",
    "ALTER TABLE decoded_messages ADD COLUMN IF NOT EXISTS protocol_id VARCHAR",
    "ALTER TABLE decoded_messages ADD COLUMN IF NOT EXISTS message_type VARCHAR",
    "ALTER TABLE decoded_messages ADD COLUMN IF NOT EXISTS payload_version VARCHAR",
    """
    ALTER TABLE decoded_messages ADD COLUMN IF NOT EXISTS decode_schema_id INTEGER
    REFERENCES decode_schemas(id) ON DELETE SET NULL
    """,
    "ALTER TABLE decoded_messages ADD COLUMN IF NOT EXISTS decoder_selection VARCHAR",
    """
    ALTER TABLE telemetry ADD COLUMN IF NOT EXISTS decode_schema_id INTEGER
    REFERENCES decode_schemas(id) ON DELETE SET NULL
    """,
    # Network type keys of a device (DevEUI, IMEI, MAC, ...)
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS credentials JSON",
    # Device Types (Each application can have multiple device types)
    """
    CREATE TABLE IF NOT EXISTS device_types (
        id SERIAL PRIMARY KEY,
        application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        code VARCHAR(100) NOT NULL,
        description TEXT,
        network_type VARCHAR(50),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_device_types_app_code ON device_types (application_id, code)",
    "CREATE INDEX IF NOT EXISTS ix_device_types_application_id ON device_types (application_id)",
    # Device Type Decoders (Each device type can have multiple decoders)
    """
    CREATE TABLE IF NOT EXISTS device_type_decoders (
        id SERIAL PRIMARY KEY,
        device_type_id INTEGER NOT NULL REFERENCES device_types(id) ON DELETE CASCADE,
        decode_schema_id INTEGER NOT NULL REFERENCES decode_schemas(id) ON DELETE CASCADE,
        payload_format VARCHAR(50),
        priority INTEGER NOT NULL DEFAULT 0,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_device_type_decoder_format ON device_type_decoders (device_type_id, decode_schema_id, COALESCE(payload_format, ''))",
    "CREATE INDEX IF NOT EXISTS ix_device_type_decoders_type_id ON device_type_decoders (device_type_id)",
    "CREATE INDEX IF NOT EXISTS ix_device_type_decoders_schema_id ON device_type_decoders (decode_schema_id)",
    # Associate device with device_type_id
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_type_id INTEGER REFERENCES device_types(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_devices_device_type_id ON devices (device_type_id)",
    # User email support for dual-identifier login
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email)",
    # Billing & Subscription System
    """
    CREATE TABLE IF NOT EXISTS billing_plans (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        code VARCHAR(50) UNIQUE NOT NULL,
        description TEXT,
        monthly_price FLOAT NOT NULL DEFAULT 0.0,
        annual_price FLOAT NOT NULL DEFAULT 0.0,
        currency VARCHAR(3) NOT NULL DEFAULT 'USD',
        included_devices INTEGER NOT NULL DEFAULT 1,
        included_data_mb FLOAT NOT NULL DEFAULT 500.0,
        overage_rate_per_mb FLOAT NOT NULL DEFAULT 0.05,
        extra_device_price FLOAT NOT NULL DEFAULT 2.00,
        features JSON,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tenant_subscriptions (
        id SERIAL PRIMARY KEY,
        tenant_id INTEGER NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
        plan_id INTEGER NOT NULL REFERENCES billing_plans(id) ON DELETE RESTRICT,
        status VARCHAR(30) NOT NULL DEFAULT 'trialing',
        billing_interval VARCHAR(20) NOT NULL DEFAULT 'monthly',
        current_period_start TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        current_period_end TIMESTAMP WITH TIME ZONE NOT NULL,
        auto_renew BOOLEAN NOT NULL DEFAULT TRUE,
        cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
        odoo_partner_id INTEGER,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS invoices (
        id SERIAL PRIMARY KEY,
        invoice_number VARCHAR(64) UNIQUE NOT NULL,
        tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        subscription_id INTEGER REFERENCES tenant_subscriptions(id) ON DELETE SET NULL,
        period_start TIMESTAMP WITH TIME ZONE NOT NULL,
        period_end TIMESTAMP WITH TIME ZONE NOT NULL,
        due_date TIMESTAMP WITH TIME ZONE NOT NULL,
        amount_subtotal FLOAT NOT NULL DEFAULT 0.0,
        amount_tax FLOAT NOT NULL DEFAULT 0.0,
        amount_total FLOAT NOT NULL DEFAULT 0.0,
        currency VARCHAR(3) NOT NULL DEFAULT 'USD',
        status VARCHAR(30) NOT NULL DEFAULT 'draft',
        odoo_invoice_id INTEGER,
        odoo_move_name VARCHAR(64),
        odoo_payment_state VARCHAR(30) DEFAULT 'not_paid',
        line_items JSON,
        notes TEXT,
        paid_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS network_sim_cards (
        id SERIAL PRIMARY KEY,
        provider VARCHAR(32) NOT NULL DEFAULT '1nce',
        iccid VARCHAR(32) UNIQUE NOT NULL,
        imei VARCHAR(32),
        imsi VARCHAR(32),
        msisdn VARCHAR(32),
        ip_address VARCHAR(64),
        label VARCHAR(128),
        status VARCHAR(32) NOT NULL DEFAULT 'Active',
        imei_lock BOOLEAN NOT NULL DEFAULT FALSE,
        quota_total_mb FLOAT DEFAULT 500.0,
        quota_remaining_mb FLOAT DEFAULT 500.0,
        quota_used_mb FLOAT DEFAULT 0.0,
        sms_total INTEGER DEFAULT 250,
        sms_remaining INTEGER DEFAULT 250,
        tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
        device_id VARCHAR,
        activation_date TIMESTAMP WITH TIME ZONE,
        expiry_date TIMESTAMP WITH TIME ZONE,
        last_sync_at TIMESTAMP WITH TIME ZONE,
        last_connectivity_check JSON,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS billing_usage_records (
        id SERIAL PRIMARY KEY,
        tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        subscription_id INTEGER REFERENCES tenant_subscriptions(id) ON DELETE SET NULL,
        sim_iccid VARCHAR(32),
        device_id VARCHAR,
        usage_date DATE NOT NULL,
        data_bytes BIGINT NOT NULL DEFAULT 0,
        data_mb FLOAT NOT NULL DEFAULT 0.0,
        sms_count INTEGER NOT NULL DEFAULT 0,
        source VARCHAR(32) NOT NULL DEFAULT '1nce_api',
        is_billed BOOLEAN NOT NULL DEFAULT FALSE,
        invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS integration_configs (
        id SERIAL PRIMARY KEY,
        provider VARCHAR(32) UNIQUE NOT NULL,
        base_url VARCHAR(255) NOT NULL,
        api_user VARCHAR(255),
        api_key_encrypted TEXT,
        db_name VARCHAR(100),
        extra_settings JSON,
        is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_network_sim_cards_tenant_id ON network_sim_cards (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_network_sim_cards_iccid ON network_sim_cards (iccid)",
    "CREATE INDEX IF NOT EXISTS ix_invoices_tenant_id ON invoices (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_billing_usage_records_tenant_date ON billing_usage_records (tenant_id, usage_date)",
]


def run_migrations(engine: Engine):
    with engine.begin() as connection:
        for statement in MIGRATIONS:
            try:
                connection.execute(text(statement))
            except Exception:
                pass
