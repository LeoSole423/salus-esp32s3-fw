# SALUS ESP32-S3 Firmware

Base ESP-IDF **6.0.2** para PCB SALUS v3 `506cada`, módulo
ESP32-S3-WROOM-1-N8R2: flash 8 MB DIO y PSRAM Quad 2 MB a 80 MHz.
No inicializa Wi-Fi, Bluetooth, OTA ni Telnet.

## Estado

El ejemplo fue reemplazado por una aplicación persistente de mantenimiento.
El mapa GPIO está centralizado en `components/salus_board/include/salus_board.h`.
El BMI088 tiene adquisición asíncrona y diagnóstico bajo solicitud; todavía no
hay control de actuadores. `salus_robot` dispone de salida ROS de observación
y comparación, sin cambiar todavía la fuente operativa. El protocolo binario Jetson
está implementado como recepción/telemetría sin actuación.

Un único USB Serial/JTAG sirve para control, telemetría, diagnóstico, JTAG y
flasheo. Se reemplazó la consola de texto por un driver binario dedicado:
comandos clásicos v2 de 7 bytes y telemetría de 8 bytes. No admite `ping`,
`status`, `help` ni texto libre. Ver [contrato USB](docs/migration/USB_PROTOCOL.md).
El firmware recibe comandos pero todavía no controla actuadores ni reporta
mediciones reales: READY=0, FAILSAFE=1, source=NONE y sensores N/A.

La PCB necesita alimentación externa incluso al programar: D9 es DNP.
Los flasheos remotos se ejecutarán desde Jetson; no requieren Wi-Fi en el S3.
La placa estará sin periféricos/actuadores durante esta etapa, según el operador.

## Compilar

Activar el entorno ESP-IDF 6.0.2 (mediante EIM o `export.sh`, según instalación),
con `IDF_PATH` e `IDF_PYTHON_ENV_PATH` definidos, y ejecutar:

```bash
./tools/build.sh
```

El script genera `build/usb-v2/` y su propio `sdkconfig` a partir de
`sdkconfig.defaults`, sin reutilizar la configuración local anterior de la raíz.
Para repetir desde defaults limpios se puede usar otra carpeta vacía:

```bash
python "$IDF_PATH/tools/idf.py" -B build/clean-check \
  -D SDKCONFIG="$PWD/build/clean-check/sdkconfig" build
```

El devcontainer usa `espressif/idf:v6.0.2`. La extensión de VS Code usa también `build/usb-v2/` y su `sdkconfig`;
clangd consulta los comandos de compilación de esa misma carpeta. Los artefactos generados no son fuentes versionadas.

## Banco USB — pendiente de ejecutar

Con la placa alimentada externamente y sin actuadores, seleccionar el puerto
por identidad; no asumir `/dev/ttyACM0` si hay GNSS u otros dispositivos.
Desde un entorno ESP-IDF 6.0.2 activo:

```bash
python "$IDF_PATH/tools/idf.py" -B build/usb-v2 \
  -D SDKCONFIG="$PWD/build/usb-v2/sdkconfig" -p PUERTO flash monitor
```

`PUERTO` es un marcador que debe reemplazarse por el dispositivo identificado.
La consola `monitor` no interpreta las tramas binarias. Para diagnóstico,
liberar primero cualquier consumidor del puerto y ejecutar:

```bash
python tools/usb_diagnostics.py PUERTO
```

Requiere `pyserial` y devuelve contadores; no envía comandos de actuadores.
El diagnóstico se solicita solo con esta herramienta o un consumidor que
entienda la extensión. No usarla a la vez que el consumidor ROS clásico.
Flashear o detener CPU mediante JTAG interrumpe la aplicación.
Para JTAG usar OpenOCD con `board/esp32s3-builtin.cfg`, mediante el mismo USB;
la conexión física y herramientas desde Jetson todavía requieren comprobación.

## Estado inicial de pines

- HC595 OE alto: salidas deshabilitadas; LATCH bajo, sin cargar relés.
- Puente H deshabilitado y PWM bajo; servos sin pulsos; RS485 DIR bajo.
- CS IMU altos durante soporte de placa; la tarea BMI088 inicializa después SPI e interrupciones.
- Throttle como entrada con pull-down: **estado de banco, no parada calibrada**.
  El futuro driver deberá preservar 20 kHz y duty clásico 62..228 hasta validar.
- USB y strapping no se reconfiguran desde el soporte de placa.

Estas configuraciones solo se aplican al ejecutar la aplicación; no garantizan
estados durante reset, fallo o pérdida de alimentación. No conectar actuadores
asumiendo que este es un firmware operativo.

## Migración

- [Plan de acción y arquitectura](docs/migration/PLAN.md).
- [Mapa de pines y restricciones](docs/migration/PINOUT.md).
- [Evidencia histórica de planificación](docs/migration/EVIDENCIA.md).
- [Entrega del esqueleto](docs/migration/SKELETON.md).
- [Entrega de comunicación USB](docs/migration/USB_PROTOCOL.md).

## Pruebas sin placa

```bash
python tools/test_protocol.py ../salus_robot/src/salus_control/salus_control/rpy_esp32_comms
```

Requiere compilador C del host y Python. Ejecuta tests de parser/temporización
con AddressSanitizer/UBSan y contraste contra el codec Python de Jetson.

## BMI088

[Implementación, configuración y límites](docs/migration/IMU_IMPLEMENTATION.md).
Consulta de snapshot por USB (acceso exclusivo; no abrir el cliente ROS a la vez):

```bash
python tools/usb_diagnostics.py PUERTO --imu
```

Pruebas de driver sin placa: `python tools/test_imu.py`. Se utiliza la API Bosch
fijada y verificada, descargada en el build durante la configuración inicial.
Los datos están sin calibrar y en el frame físico del sensor; no sustituyen aún
la entrada IMU del robot.

## Calibración en host

[Procedimiento y herramientas](docs/migration/IMU_CALIBRATION.md): acelerómetro
en seis posiciones antes de instalar, y ajuste del giróscopo con vehículo inmóvil.
Perfiles JSON versionados, sin sobrescribir resultados previos ni modificar raw.
No se ejecuta automáticamente al encender. El observador de `salus_robot` puede leer estos perfiles; el cutover operativo sigue pendiente.

Pruebas sin placa:

```bash
python -m unittest discover -s tests -p test_calibration.py -v
```

La consulta temporizada tipo 03 habilita la observación ROS documentada en
`salus_robot/docs/bmi088-ros.md`. No usar dos lectores sobre el mismo USB ni
confundir el observador con el futuro gateway de control/IMU continuo.
