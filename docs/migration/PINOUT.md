# Mapa de pines PCB v3 para el port

Base: PCB `506cada`. Consistencia de archivos, confianza alta en asignación
pad/red; sin medición ni validación de niveles/actuadores. Se cruzó el símbolo
U8 de `ESP32.kicad_sch` con pads U8 de `PCB_SALUS_v3.kicad_pcb`, usando el parser
S-expression de la guía KiCad. No es revisión de fabricación ni de datasheets.
Los números de pad del módulo no son números GPIO.

| Función/red en U8 | Pad U8 | GPIO S3 | Destino / condición |
| --- | --- | --- | --- |
| R_PWM | 4 | 4 | J6; confirmar sentido físico |
| L_PWM | 5 | 5 | J6 |
| HBRIDGE_EN | 6 | 6 | J6, iniciar deshabilitado |
| I2C_SDA | 7 | 7 | J2/J12/J13; pull-ups externos por verificar |
| DR_GIRO | 8 | 15 | Interrupción BMI088 |
| RF_PPM | 9 | 16 | J15 vía adaptación; medir amplitud |
| Net-(U8-IO17) | 10 | 17 | Ruta UART1; seguir resistencias hacia J4/RS485 antes de habilitar |
| Net-(U8-IO18) | 11 | 18 | Ruta UART1; comparte bus externo |
| I2C_SCL | 12 | 8 | J2/J12/J13 |
| USB_D- | 13 | 19 | J16 por resistencias; reservado USB |
| USB_D+ | 14 | 20 | J16 por resistencias; reservado USB |
| IO3 | 15 | 3 | J22; strapping |
| IO46 | 16 | 46 | J22; strapping y restricciones de dirección a revisar |
| CS_ACCEL | 17 | 9 | BMI088 acelerómetro |
| CS_GIRO | 18 | 10 | BMI088 giróscopo |
| SPI_MOSI | 19 | 11 | BMI088 y datos HC595 compartidos |
| SPI_CLOCK | 20 | 12 | BMI088 y reloj HC595 compartidos |
| SPI_MISO | 21 | 13 | BMI088 |
| DR_ACCEL | 22 | 14 | Interrupción BMI088 |
| THROTTLE_PWM | 23 | 21 | Filtro/LM358 → J11; clásico usaba GPIO13 |
| IO47 / IO48 | 24 / 25 | 47 / 48 | J22 auxiliares; no asignar función todavía |
| IO45 | 26 | 45 | J22; strapping |
| BOOT | 27 | 0 | Reservar recuperación |
| Net-(U8-IO35/36/37) | 28 / 29 / 30 | 35 / 36 / 37 | Hall A/B/C vía 1 kΩ; nivel eléctrico pendiente |
| RELAY_LATCH | 31 | 38 | HC595; mantener inactivo durante tráfico IMU |
| RELAY_OE | 32 | 39 | HC595; deshabilitar, cargar/latchear estado definido, habilitar |
| SERVO1_PWM | 33 | 40 | J18; no inferir equivalencia con servo A clásico |
| SERVO2_PWM | 34 | 41 | J17; no inferir equivalencia con servo B clásico |
| RS485_DIR | 35 | 42 | Transceptor compartido J3/J21; J4 no independiente |
| U0RX / U0TX | 36 / 37 | 44 / 43 | J1 Debug_U0; acceso auxiliar, sin dependencia para operación/debug normal |
| FC_RIGHT | 38 | 2 | J8, contacto a GND |
| FC_LEFT | 39 | 1 | J7, contacto a GND |

Pad 2 es 3.3 V; pad 3 EN/reset; 1/40/41 GND. J22 no tolera 5 V.
El uso de 35–37 corresponde al módulo N8R2 de esta placa; no generalizar a otras
variantes de memoria. Ver decisiones de hardware para esa restricción.

El bus compartido IMU/HC595 necesita un único árbitro de transacciones: tráfico
SPI puede desplazar bits del registro aunque LATCH no cambie. Cada actualización
de relés debe cargar el patrón completo correcto antes del pulso LATCH. No
latchear datos de una lectura IMU. La asignación de los siete bits a cargas reales
queda pendiente; no adoptar sin prueba la polaridad GPIO del firmware clásico.

Pendiente antes del primer driver: cotejar rutas completas de UART/Hall detrás
de resistencias, confirmar pinout con continuidad en placa y crear una tabla de
recursos LEDC/timers/RMT/SPI/IRQ compatible con la versión IDF elegida. Los
canales LEDC clásicos 8/9 y resoluciones no se copian automáticamente al S3.
