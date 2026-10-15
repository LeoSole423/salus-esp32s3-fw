# Comunicación USB — entrega inicial 2026-10-15

Estado: implementada y verificada en host/build; no probada en placa ni Jetson.
No incluye actuadores, sensores, RC, arbitraje ni habilitación de movimiento.
No cambia el código o los contratos ROS de `salus_robot`.

## Arquitectura implementada

`salus_protocol` es C puro sin dependencia de ESP-IDF. Conserva el contrato
clásico inspeccionado en `ESP32_SALUS@037c1ed` y el codec de
`salus_robot@5a4c3b7`. `main/salus_main.c` tiene un único propietario del driver
USB Serial/JTAG: RX, parser, TX y diagnóstico. No hay segundo lector, consola
VFS ni texto libre. JTAG conserva su interfaz hardware sobre el mismo cable.

Se deshabilitaron consola y logs de bootloader/aplicación en defaults. No se
quemaron eFuses: mensajes de ROM/reset o fallos excepcionales pueden requerir
resincronización del lector host; no se promete silencio desde power-on.
La depuración de variables/breakpoints sigue disponible por JTAG, pendiente de
prueba física. Los diagnósticos actuales son contadores estructurados, no un
sistema general de logs. Futuras trazas deberán tener framing propio.

## Compatibilidad v2

Comando, 7 bytes:

`AA ver_flags steer_i8 speed_lo speed_hi brake CRC`

Versión alta=2. Flags bajos: ESTOP=1, DRIVE_EN=2, REV_REQ=4, HAZARD=8.
Velocidad es magnitud uint16 LE en cm/s; el signo solicitado se deriva de REV_REQ.
Dirección está en porcentaje int8 y freno en porcentaje uint8. Se preservan
bytes crudos como el receptor clásico: rangos esperados -100..100/0..100, cuya
limitación deberá resolver el futuro dominio de actuadores. No convertir una
magnitud uint16 completa a int16 firmado ni permitir overflow al aplicar signo.

CRC: init 0, polinomio 0x31, MSB-first sobre todos los bytes salvo el CRC. Se
comparó con la implementación efectiva Python; no adoptar otra variante por
coincidir en el nombre Dallas/Maxim.

Cada trama válida renueva el tiempo monotónico de recepción. Fresh hasta
120000 µs inclusive; a 120001 µs es stale. CRC incorrecto, versión errónea,
ruido o diagnóstico no renuevan ese tiempo. El getter devuelve false y comando
cero si está stale. Tramas parciales expiran con pausa entre bytes >120 ms.
El parser recupera headers dentro de candidatos corruptos y no depende de los
límites de las lecturas USB.

Telemetría, 8 bytes:

`55 status FF FF 00 80 00 CRC`

- READY=0, FAILSAFE=1 y CONTROL_SOURCE=NONE siempre en esta entrega.
- PI_FRESH depende de la última trama; ESTOP refleja solicitud fresca, sin
  afirmar que exista freno físico actuado.
- Velocidad `0xFFFF`, dirección `0x8000`: mediciones no disponibles.
- Freno aplicado=0 porque no hay driver implementado, no un acuse de la solicitud.
- No se emite batería `0x56` ni se reintroduce ADC.

El backend Jetson puede interpretar estas tramas, pero no representa paridad
operativa del controlador. No desplegarlo como sustituto del firmware clásico.

## Diagnóstico separado, bajo solicitud

Extensión de mantenimiento **provisional**, sin cambiar el layout v2.
No es una ampliación ya aprobada del consumidor ROS. Se emite solo ante
solicitud explícita; en uso clásico solo hay telemetría `0x55`.

Solicitud fija de 7 bytes: `AB 10 01 00 00 00 CRC`.
Respuesta de 24 bytes:

| Offset | Contenido |
| --- | --- |
| 0 | `5A`, header diagnóstico |
| 1 | `10`, versión 1 / flags 0 |
| 2 | `01`, tipo estado |
| 3 | `18` hex, longitud total 24 |
| 4..7 | Comandos aceptados, uint32 LE |
| 8..11 | Errores CRC, uint32 LE |
| 12..15 | Tramas rechazadas por versión/opcode, uint32 LE |
| 16..19 | Intentos TX sin progreso por backpressure, uint32 LE |
| 20 | Comando fresco, 0/1 |
| 21..22 | Reservados, cero |
| 23 | CRC de bytes 0..22 |

No usar un lector clásico para multiplexar esta respuesta: su parser busca
`0x55` dentro del stream y no conoce el framing de diagnóstico. La herramienta
`tools/usb_diagnostics.py` entiende ambas tramas y debe tener acceso exclusivo.
No emitir diagnósticos durante una sesión del cliente clásico ni abrir dos
procesos sobre el puerto. La integración futura deberá usar un solo lector
Jetson que demultiplexe las familias y un contrato versionado acordado.

No hay comandos de calibración, escritura de parámetros ni movimiento en esta
extensión. Un flujo de solicitudes se agrupa en un único diagnóstico pendiente.
La respuesta deja prioridad temporal a la telemetría de control.

## Temporización y desconexión

Tick FreeRTOS=1 ms. RX acotada a 64 bytes por iteración; TX nominal de telemetría
cada 10 ms. Una trama TX parcialmente escrita se termina antes de comenzar la
siguiente; cola local de una trama y buffers de driver acotados. Escrituras sin
espera y sin bucles de reintento bloqueantes. La tasa/jitter real requieren
medición; 100 Hz es objetivo nominal, no garantía temporal.

Al detectar cambio de conexión USB por SOF se reinician buffers del driver,
parser y comando almacenado. La detección física no distingue cerrar/reabrir el
puerto con el cable conectado. En ese caso se depende del timeout de comandos;
no hay handshake de sesión ni rearme implementado. Antes de activar actuadores
se debe cerrar ese contrato: no asumir que el protocolo v2 distingue un comando
retrasado del host de un comando nuevo ni que detecta todos los microcortes.
La presencia USB tampoco indica que la aplicación host esté viva.

Los contadores de RX se reinician al cambiar la conexión; los uint32 pueden
volver a cero por wrap/reset. No son almacenamiento persistente ni auditoría.

## Configuración y evidencia

VS Code y `tools/build.sh` usan ahora `build/usb-v2/` y su propio `sdkconfig`,
para aplicar los defaults nuevos sin heredar la consola USB del esqueleto.
Se conserva `build/skeleton/`, el build raíz y la configuración local anterior.

Pruebas ejecutables en `tests/test_protocol.c` y `tools/test_protocol.py`:
fragmentación, ruido, recuperación, back-to-back, CRC/versión inválidos sin
renovar freshness, bordes del timeout, cancelación de parciales, reset,
ESTOP y sentinelas. Sanitizers en host y comparación de 256 vectores CRC más
16 combinaciones de comandos generadas por Jetson y decodificación de telemetría
contra su codec. No prueban el driver físico,
la reconexión real, JTAG simultáneo ni latencia USB.

Pendiente: prueba de banco sin periféricos cuando haya placa, medición de tasas,
reinicios y recuperación; arbitraje/armado antes de habilitar actuadores;
canal general de logs; IMU y demultiplexor Jetson con integración ROS posterior.

Resultado local: `tools/build.sh` terminó con código 0 en ESP-IDF 6.0.2;
binario de aplicación de 148208 bytes. Se comprobó en configuración generada
consola NONE, USB Serial/JTAG habilitado, tick 1000 Hz, logs de bootloader y
aplicación desactivados, PSRAM Quad y flash 8 MB. Sin componentes Wi-Fi/BT/red.
`git diff --check` y compilación sintáctica de herramientas Python correctos.
No se flasheó ninguna placa ni se ejecutó un launch real.

## Extensión de diagnóstico IMU — 2026-10-15

Se añadió solicitud opcode `02` (`AB 10 02 00 00 00 CRC`) y respuesta tipo `02`
de 112 bytes, solo bajo solicitud. Ver [formato y validez](IMU_IMPLEMENTATION.md).
No altera las tramas v2 ni renueva freshness de control. La herramienta de
inspección acepta longitudes 24 y 112 con tipo y CRC correspondientes; el lector
ROS clásico no debe coexistir con estas consultas. No hay stream IMU continuo.
