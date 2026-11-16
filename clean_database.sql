BEGIN;

-- 0. Billing & Network Provider Tables
DELETE FROM billing_usage_records;
DELETE FROM invoices;
DELETE FROM network_sim_cards;
DELETE FROM tenant_subscriptions;
DELETE FROM billing_plans;
DELETE FROM integration_configs;

-- 1. Deliveries and Webhooks
DELETE FROM webhook_deliveries;
DELETE FROM webhooks;

-- 2. Telemetry and Decoded Messages
DELETE FROM telemetry;
DELETE FROM decoded_messages;
DELETE FROM decoded_messages_store;

-- 3. Device Commands, Events and Configurations
DELETE FROM device_command_events;
DELETE FROM device_commands;
DELETE FROM device_configurations;
DELETE FROM devices;

-- 4. Applications
DELETE FROM applications;

-- 5. Decoder schemas and versions
DELETE FROM decode_schema_activations;
DELETE FROM decode_schemas;
DELETE FROM decoder_versions;
DELETE FROM decoder_definitions;

-- 6. Collaborator permissions and roles
DELETE FROM collaborator_permissions;
DELETE FROM collaborator_roles;
DELETE FROM iam_user_roles;
DELETE FROM iam_role_permissions;
DELETE FROM iam_attribute_values;
DELETE FROM iam_audit_logs;
DELETE FROM iam_abac_policies WHERE name NOT IN ('Satellite Command Clearance Enforcement', 'Regional Device Maintenance Scope', 'Night Shift Destructive Deletion Guard');

-- 7. Notifications
DELETE FROM notifications;

-- 8. Remove all users EXCEPT admin
DELETE FROM users WHERE role != 'admin';

-- 9. Remove all dummy tenants
DELETE FROM tenants;

-- 10. Reset auto-increment sequences for clean IDs
DO $$
DECLARE
    seq RECORD;
BEGIN
    FOR seq IN 
        SELECT sequence_name 
        FROM information_schema.sequences 
        WHERE sequence_schema = 'public' 
          AND sequence_name NOT LIKE '%users%'
    LOOP
        EXECUTE format('ALTER SEQUENCE %I RESTART WITH 1', seq.sequence_name);
    END LOOP;
END $$;

-- Reset users sequence to next after current admin
SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1), true);

COMMIT;
