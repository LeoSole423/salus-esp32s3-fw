# Evidencia de planificación — 2026-10-15

Inspección local de solo lectura de las fuentes, seguida de edición documental.
No se contactó Jetson, no se construyó ni flasheó firmware, no hubo mediciones,
launches reales, pruebas de actuadores ni nueva revisión ERC/DRC/EMC/SPICE.
Se reutilizó la revisión de hardware indicada por el operador; esta tarea es
planificación de firmware, no aprobación de diseño o fabricación.

## Rutas para reproducir la inspección

- Hardware: `/home/leosole/Desktop/KiCAD/PCB_SALUS_v3`.
- Clásico: `/home/leosole/Desktop/SALUS/ESP32_SALUS`.
- Destino: `/home/leosole/Desktop/SALUS/salus-esp32s3-fw`.
- Jetson (fuentes locales): `/home/leosole/Desktop/SALUS/salus_robot`.

En cada repositorio consultar `git status --short`, `git branch --show-current`
y `git rev-parse HEAD`. Las revisiones iniciales completas y hashes de archivos
relevantes están en `sources.json`; regenerarlos explícitamente en otra ronda,
no interpretar este manifiesto como seguimiento automático del árbol.

## Hallazgos trazables

| Observación | Fuente |
| --- | --- |
| Esqueleto reinicia periódicamente | `salus-esp32s3-fw/main/hello_world_main.c` |
| Defaults de memoria, sin decisión USB reproducible | `sdkconfig.defaults`; contraste con `sdkconfig` local (consola secundaria USB) |
| Calibración throttle/frenos y tareas | `ESP32_SALUS/src/main.cpp` |
| Stop conserva mínimo PWM | `ESP32_SALUS/src/quad_functions.cpp`, `quadThrottleStop` |
| Arbitraje no trivial, rearme RC y tiempos | `quad_functions.cpp`, `pid.cpp`, `fs_ia6.cpp` |
| CRC y tramas actuales | `pi_comms.cpp`; Python `rpy_esp32_comms/protocol.py` |
| UART/control real ya existe | `salus_control/launch/control_real_uart.launch.py`, `transport.py` |
| Resolver prioriza CP2102 | `salus_control/salus_control/serial_port_resolver.py` |
| Solo gyro Z de IMU fusionado localmente | `salus_localization/config/localization_local_real.yaml`, máscara `imu0_config` |
| GNSS direct_usb pendiente | `salus_hardware/salus_hardware/pixhawk_rtk_adapter.py`, error explícito |
| D9 DNP, alimentación externa, sin VBUS sense | PCB `DECISIONES_Y_PENDIENTES.md` |
| Pinout nuevo y bus compartido | PCB nativa U8, símbolo embebido y `REVISION_COMPLETA.md` |

Confianza alta para existencia de código, valores literales y consistencia de
pads/redes; ninguna confianza física asignada sin medición. La revisión PCB
original no cubría extracción tipada completa de datasheets; no elevar sus
estimaciones térmicas/eléctricas a validaciones del robot.

## Estado de migración

Completado: inventario inicial, propuesta de arquitectura, mapa de pines y gates.
Pendiente: caracterización ejecutable M0 y todas las implementaciones M1–M9.
La matriz de entregas en `PLAN.md` es el mapa de estado del firmware. El
`salus_robot/docs/migration-status.yaml` conserva su autoridad para ROS; no fue
alterado porque esta entrega no implementa ni cambia ningún contrato ROS.
