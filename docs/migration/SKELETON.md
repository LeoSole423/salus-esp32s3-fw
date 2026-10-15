# Esqueleto implementado — 2026-10-15

Primera entrega de M1, sin pruebas físicas. Decisión posterior a la planificación:
se avanza entendiendo y portando módulos sin exigir pruebas en placa previas.
La autorización actual contempla placa sin periféricos ni actuadores conectados.

Implementado:

- ESP-IDF fijado a 6.0.2 (instalado localmente y seleccionado en devcontainer).
- Target S3, flash 8 MB DIO y PSRAM Quad; defaults versionados y build separado.
- Mapa GPIO centralizado según PCB `506cada`; funciones UART1 aún sin habilitar.
- Soporte inicial: OE relés alto, puente deshabilitado, servos sin pulsos,
  DIR RS485 bajo, CS IMU altos. Throttle entrada/pull-down solo para banco;
  no reemplaza el stop calibrado del futuro driver.
- Aplicación persistente sin reinicios programados ni inicialización Wi-Fi/BT.
- Consola USB Serial/JTAG bidireccional de texto, comandos ping/status/help.
- Retirados ejemplo hello-world y sus tests ajenos al comportamiento SALUS.

Pendiente de M1: definir particiones/actualización para release, CI y comprobación
USB/flash/JTAG/memoria en placa. Pendiente M2: codec v2 y framing de diagnóstico
compartido sin mezclar texto con el protocolo. El esqueleto no acepta comandos
de control del robot. JTAG puede detener CPU; no es garantía de seguridad local.

El script de build conserva `.vscode/settings.json`, `sdkconfig` y `build/`
preexistentes (usa subdirectorio propio). No se flasheó ni contactó hardware.
Los hashes de `sources.json` corresponden a la planificación anterior al port,
no a una descripción del firmware nuevo.

## Verificación local

`tools/build.sh` terminó con código 0 usando ESP-IDF 6.0.2. Configuración
resultante: target esp32s3, flash 8MB DIO, PSRAM Quad 80MHz, consola primaria
USB Serial/JTAG sin consola secundaria. La lista de componentes del build no
incluye `esp_wifi`, `bt`, `esp_netif` ni `lwip`. Binario de aplicación: 156976
bytes. `git diff --check` y `bash -n tools/build.sh` correctos. No se ejecutó
el firmware en hardware; ping/status y coexistencia JTAG siguen sin validar.
