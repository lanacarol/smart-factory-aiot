INSERT INTO devices (
    device_id,
    name,
    device_type,
    location,
    active
)
VALUES
    (
        'motor-01',
        'Motor Industrial 01',
        'motor',
        'Linha de Producao 01',
        TRUE
    ),
    (
        'environment-01',
        'Sensor Ambiental 01',
        'environment_sensor',
        'Area de Producao',
        TRUE
    ),
    (
        'conveyor-01',
        'Esteira Transportadora 01',
        'conveyor',
        'Linha de Producao 01',
        TRUE
    ),
    (
        'fan-01',
        'Ventilador Industrial 01',
        'fan',
        'Area de Producao',
        TRUE
    )
ON CONFLICT (device_id) DO NOTHING;
