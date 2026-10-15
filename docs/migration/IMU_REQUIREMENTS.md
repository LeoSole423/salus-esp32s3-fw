# Requisito futuro de PCB: sincronización del BMI088

ID: **IMU-SYNC-001**. Fecha: 2026-10-15.
Estado: **diferido a una próxima revisión de PCB; no implementado**.

## Decisión del operador

Conservar el diseño enviado a fabricar. No modificar ni cancelar el pedido por
este requisito. Registrar la mejora en firmware y PCB para retomarla al preparar
una revisión futura. No implica que se haya cambiado esquema, ruteo o entrega.

## Motivo y alcance

El BMI088 contiene acelerómetro y giróscopo con adquisición independiente.
La sincronización interna documentada por Bosch requiere conectar externamente
la salida de datos listos del giróscopo a una entrada de interrupción del
acelerómetro. Esta conexión no existe en la PCB v3 base `506cada`.

No bloquea la primera integración: el EKF local real inspeccionado de
`salus_robot` fusiona de la IMU solamente `angular_velocity.z`. El firmware
previsto para la placa actual deberá adquirir ambos sensores por separado,
con marcas de tiempo independientes y sin presentar sus datos como simultáneos.
La equivalencia y precisión físicas aún requieren validación.

## Conexión propuesta para una revisión futura

Números de terminal del BMI088 **U4**, no números GPIO del ESP32:

| Señal | PCB actual, base 506cada | Propuesta futura |
| --- | --- | --- |
| INT3, pad 12 | DR_GIRO → ESP32 GPIO15 | Conservar y unir también a INT1 |
| INT1, pad 16 | DR_ACCEL → ESP32 GPIO14 | Separar de DR_ACCEL y conectar a INT3 |
| INT2, pad 1 | Sin conectar | Conectar a DR_ACCEL → ESP32 GPIO14 |
| INT4, pad 13 | Sin conectar | Sin cambios previstos |

Así se conserva el uso de GPIO14/GPIO15, sin exigir GPIO adicionales ni nuevos
componentes. Es una propuesta de conexionado, no un ruteo ya comprobado por DRC.
INT1 deberá configurarse como entrada de sincronización, no como salida contra
INT3. INT2 será la salida de disponibilidad de datos sincronizados hacia el MCU.

## Trabajo cuando se retome

- Modificar esquema y PCB conjuntamente; retirar el no-connect de INT2 y
  comprobar redes y direcciones de las interrupciones.
- Revisar el ruteo y ejecutar ERC/DRC/paridad; generar una entrega nueva con
  revisión y manifiesto propios, preservando D9 DNP y la entrega histórica.
- Adaptar inicialización y mapa de interrupciones al perfil de hardware nuevo;
  configurar el modo de sincronización con la API Bosch y su configuración
  requerida. La conexión física por sí sola no activa la sincronización.
- Conservar un perfil asíncrono para las placas ya pedidas y comprobar ambos
  perfiles. Verificar tasa, retardos, interrupciones y funcionamiento físico
  antes de declarar disponibles muestras sincronizadas.

## Referencias y trazabilidad

- [Bosch: Data Synchronization for BMI085 & BMI088, secciones Concept y
  Technical Realization](https://www.bosch-sensortec.com/media/boschsensortec/downloads/application_notes_1/bst-mis-an006.pdf).
- Hardware canónico: `PCB_SALUS_v3`, base `506cada`,
  `docs/reviews/2026-10-15/DECISIONES_Y_PENDIENTES.md`, entrada IMU-SYNC-001.
- Registro de firmware: `salus-esp32s3-fw/docs/migration/IMU_REQUIREMENTS.md`.
- Inspección de pads/redes en `PCB_SALUS_v3.kicad_pcb`: INT1/INT3 en redes
  distintas, INT2/INT4 sin conectar. No se hicieron cambios de circuito.
