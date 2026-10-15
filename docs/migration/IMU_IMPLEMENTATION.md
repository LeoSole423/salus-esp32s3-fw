# BMI088: adquisición en firmware — 2026-10-15

Estado: implementado y compilado; verificado con registros SPI simulados en host.
Sin flasheo, pruebas físicas ni cambio de la fuente inercial del robot.

## Alcance de esta entrega

Driver para la PCB actual `506cada`, **sin sincronización interna**. No cambia
el pedido ni el requisito futuro IMU-SYNC-001. Adquisición independiente con
snapshot de diagnóstico por el mismo USB Serial/JTAG. No es todavía el flujo
continuo multiplexado, sincronización de reloj con Jetson, calibración, TF ni
adaptador ROS del plan de sustitución del Pixhawk. El protocolo v2 de comandos
y telemetría de control conserva su semántica y no habilita actuadores.

## Driver y dependencia

`salus_imu` usa la API oficial de Bosch BMI08x, fijada al commit
`c1ed227e7bb7da1fa600bbd4e5c82d0da1eb416a`. `tools/fetch_bosch.py` descarga
el archivo del fabricante al build y verifica SHA256
`80e315094b3b057f2b43f145f87bb20810c54be92cb3786b8abdcd3007596b1b`.
Solo extrae una lista explícita de archivos regulares, incluida la licencia
BSD-3-Clause. La caché se verifica en cada configuración; la primera requiere
red en el equipo de compilación, no Wi-Fi en el ESP32. No se incorporan fuentes
Bosch como archivos modificables del proyecto.

Configuración de adquisición perfil 1:

| Parámetro | Valor |
| --- | --- |
| SPI | SPI2, modo 0, 4 MHz, sin DMA |
| MOSI / CLOCK / MISO | GPIO11 / GPIO12 / GPIO13 |
| CS acelerómetro / giróscopo | GPIO9 / GPIO10 |
| DRDY acelerómetro / giróscopo | GPIO14 / GPIO15; flanco ascendente |
| Acelerómetro | ±6 g; 400 Hz; OSR4, corte nominal 40 Hz |
| Giróscopo | ±500 °/s; 400 Hz; corte nominal 47 Hz |
| Temperatura | Lectura nominal 1 Hz |

Identifica ambos chips, resetea, respeta esperas Bosch, configura alimentación,
rangos y filtros, relee configuración y comprueba errores del acelerómetro.
Los IDs esperados son 0x1E y 0x0F. El driver Bosch realiza el cambio inicial de
interfaz y descarta el dummy byte adicional de cada lectura del acelerómetro.

En esta entrega una sola tarea accede a los dos dispositivos SPI. HC595 OE
permanece alto y LATCH no se pulsa. **Antes de implementar relés**, centralizar
sus transacciones y latch en el mismo arbitraje: cada lectura IMU también
introduce bits en el shift register que comparte MOSI/CLOCK. No habilitar relés
ni escribir esos GPIO desde otro módulo por fuera del driver SPI.

## Tiempo, validez y recuperación

- ISR solo registra tiempo monotónico MCU y contador por sensor y notifica tarea.
- La tarea lee registros fuera de ISR y conserva raw, SI, secuencia y tiempo de
  cada vector. No hay orientación estimada ni cambio al frame del robot.
- Se descarta una lectura con más de 2 ms desde DRDY o si aparece otro DRDY
  durante la lectura: no asignar un timestamp viejo a registros nuevos.
- Notificaciones agrupadas y lecturas descartadas incrementan contadores.
  Sin FIFO no se recupera el historial perdido.
- Validez expira a 50 ms por sensor; temperatura a 2 s. Valores previos pueden
  seguir presentes como evidencia, pero los flags de validez quedan en false.
- Si falta alguna medición fresca después de 100 ms de arranque, o hay tres
  errores consecutivos de lectura, declara fallo y reintenta inicialización
  después de 1 s. Fallo de asignación/configuración de recursos SPI/GPIO no
  intenta reservarlos repetidamente y requiere reinicio.
- La tarea IMU es independiente de USB. Un sensor ausente no impide diagnóstico
  de comunicación. El estado inicial es STARTING; nunca se simulan mediciones.

Los tiempos son de **DRDY en el MCU**, no del instante físico de medición:
falta compensar retardo de filtros y mapear reloj MCU al ROS de Jetson antes
de una integración operativa. Raw y SI siguen el frame físico Bosch, sin sesgo
corregido, rotación de montaje ni eliminación de gravedad. Los flags saturated
solo indican códigos de extremo ADC; no son un estimador de calidad completo.

Conversión nominal: aceleración `raw * 9.80665 / 5460` m/s²;
giróscopo `raw * (pi / 180) / 65.536` rad/s. Conservar raw para calibración
posterior. Temperatura de sensor no equivale a temperatura ambiente.

## Diagnóstico USB

Con el S3 alimentado externamente y un único consumidor serie:

```bash
python tools/usb_diagnostics.py PUERTO --imu
```

La herramienta no envía comandos de actuadores. Muestra estado, IDs, intentos,
errores, pérdidas, secuencias, raw y SI, tiempos/antigüedad independientes y
temperatura. `valid=false` significa que no debe utilizarse ese valor.

Solicitud: `AB 10 02 00 00 00 CRC`, con CRC8 clásico sobre los primeros 6 bytes.
No renueva la frescura de control. Respuesta solo bajo solicitud:

| Offset | Tipo / significado |
| --- | --- |
| 0..3 | `5A 10 02 70` (header, versión, tipo IMU, longitud 112) |
| 4 | uint8 estado: 0 STARTING, 1 RUNNING, 2 FAULT |
| 5 | Flags: accel válido bit0, gyro válido bit1, temperatura válida bit2, accel saturado bit3, gyro saturado bit4 |
| 6..7 | IDs accel/gyro |
| 8..11 | int32 LE último error (negativo Bosch o positivo ESP-IDF) |
| 12..27 | Cuatro uint32 LE: intentos init, errores lectura, pérdidas accel y gyro |
| 28..35 | Dos uint32 LE: secuencia accel y gyro |
| 36..59 | Tres uint64 LE: tiempos accel, gyro y temperatura, µs MCU |
| 60..65 | Tres int16 LE: accel raw XYZ |
| 66..71 | Tres int16 LE: gyro raw XYZ |
| 72..83 | Tres float32 LE: accel m/s² XYZ |
| 84..95 | Tres float32 LE: gyro rad/s XYZ |
| 96..99 | int32 LE temperatura en milésimas de °C |
| 100..107 | uint64 LE tiempo MCU de la captura del paquete |
| 108 | uint8 perfil=1, no implica calibración |
| 109..110 | Reservados cero |
| 111 | CRC8 clásico sobre bytes 0..110 |

No pedir este paquete mientras el lector ROS clásico esté activo: no entiende
extensiones ni longitudes. La futura integración continua requiere el perfil
multiplexado acordado en el plan; no emitir IMU espontáneamente entre tramas v2.
El diagnóstico es una captura de último valor, no un registro a 400 Hz.

## Verificación sin placa

```bash
python tools/test_imu.py
python tools/test_protocol.py ../salus_robot/src/salus_control/salus_control/rpy_esp32_comms
./tools/build.sh
```

El primer test compila la API Bosch real con un bus SPI simulado y ASan/UBSan:
identificación correcta/incorrecta, fallo de bus, escritura no aplicada,
configuración y lectura de vuelta, mapeo de interrupciones, dummy del accel,
lectura LE con signo, escalas, saturación, expiración independiente y estado
FAULT. Comprueba también el paquete C contra el decodificador Python y rechazo
de paquetes corruptos/truncados. Las pruebas de protocolo comprueban que la
consulta IMU no renueva control y se conserva compatibilidad clásica.

No cubren ISR ni latencia física SPI, arranque de una placa real, filtros
medidos, ejes de montaje, vibración, JTAG simultáneo ni precisión frente a
Pixhawk. Siguientes entregas: transporte continuo/reloj Jetson, calibración y
adaptador ROS, antes de seleccionar BMI088 como fuente operativa.

Referencias: [API Bosch](https://github.com/boschsensortec/BMI08x_SensorAPI/tree/c1ed227e7bb7da1fa600bbd4e5c82d0da1eb416a),
[datasheet BMI088](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi088-ds001.pdf),
[mejora futura de sincronización](IMU_REQUIREMENTS.md).

Resultado de esta entrega: tests IMU y compatibilidad C/Python correctos,
regresión de protocolo correcta, build ESP-IDF 6.0.2 con código 0 y sin avisos
de compilación. Binario de aplicación: 188560 bytes; incluye `bmi08x` y
`salus_imu`, sin componentes Wi-Fi/BT/red. `git diff --check` y compilación
sintáctica de herramientas Python correctos. No hubo acceso a hardware.

## Actualización: calibración en host

Se implementó la [herramienta de calibración](IMU_CALIBRATION.md) para PC/Jetson:
captura explícita, gyro estacionario y acelerómetro en seis posiciones, perfiles
JSON persistentes y aplicación en diagnóstico/offline. No cambia datos raw ni
registros del BMI088. La calibración física, compensación temporal y adaptación
ROS siguen pendientes; no se cambia la fuente inercial operativa.

## Actualización: observación ROS y temporización USB

Existe un observador/comparador ROS en `salus_robot`, documentado en
`docs/bmi088-ros.md` de ese repositorio. Usa diagnóstico **tipo 03** con token
y cuatro marcas de tiempo; no activa el EKF ni cambia la fuente operativa.

Solicitud: `AB 10 03 token0 token1 token2 CRC`, token uint24 LE. Respuesta de
128 bytes: snapshot tipo 02 hasta byte 110 con header `5A 10 03 80`, token en
111..113, boot ID uint32 LE en 114..117, recepción de petición MCU uint64 µs en
118..125, reservado cero en 126 y CRC8 de 0..126 en 127. El tiempo de captura
conserva offset 100..107. El boot ID es aleatorio por arranque, no identidad
permanente. Las consultas no renuevan freshness de control; 01/02 y v2 no cambian.

El observador ROS es el único lector del puerto S3, solo solicita diagnósticos.
El gateway compartido de control/IMU continuo sigue pendiente; no abrir a la vez
el cliente v2 clásico. Giro y aceleración se publican separados con tiempos
propios y perfil de calibración opcional. Pruebas con USB/Pixhawk virtuales y
cruce de este paquete C con codec ROS pasaron; la comparación física falta.
