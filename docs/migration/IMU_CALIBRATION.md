# Calibración BMI088 en banco y con el vehículo inmóvil

Implementación de host (PC o Jetson), 2026-10-15. Sin mediciones físicas todavía.
Las herramientas solicitan snapshots USB: no envían comandos de movimiento,
no escriben registros de calibración del sensor y no modifican NVS/firmware.
El perfil JSON se guarda fuera del S3 y puede copiarse a la Jetson.

## Qué se calibra y cuándo

- Acelerómetro: seis posiciones en banco antes de instalar. Corrige offset y
  escala por eje; no estima desalineamiento cruzado ni elimina la gravedad.
- Giróscopo: diez segundos estacionarios. Se puede repetir posteriormente con
  el vehículo quieto, sin levantarlo ni desmontar la placa. No es automático al
  encender. El ajuste conserva la calibración de acelerómetro del perfil base.
- Montaje respecto del vehículo: queda fuera de esta calibración intrínseca.
  Se realizará mediante TF; los perfiles actuales siguen el frame físico Bosch.

Guardar el perfil y las capturas originales. No es necesario repetir las seis
posiciones al encender; revisar la calibración si se cambia el sensor o aparecen
errores. Los coeficientes son constantes, sin un modelo térmico de compensación.

## Preparación

Activar Python con `pyserial` para captura en vivo. Los cálculos offline y tests
solo usan la biblioteca estándar. Requiere el firmware con diagnóstico IMU tipo
02 y adquisición perfil 1 (±6 g / ±500 °/s, 400 Hz).

Identificar el puerto del S3 y liberar otros consumidores del mismo puerto.
Usar alimentación externa. **Las instrucciones siguientes son para ejecución
posterior del operador; no se ejecutaron sobre hardware en esta entrega.**

Elegir una etiqueta única para la placa (ejemplo `SALUS-V3-001`) y marcarla
físicamente. `--device-id` debe mantenerse entre capturas y aplicación del perfil.
Es una identificación declarada por el operador: los chip IDs 0x1E/0x0F no son
números de serie únicos y el protocolo actual aún no transmite identidad MCU.
Por eso no hay comprobación automática de que la etiqueta corresponda al USB.

Dejar la placa o vehículo completamente inmóvil. La captura espera por defecto
60 s antes de registrar, luego recoge diez segundos mediante consultas nominales
a 50 Hz. La espera es una ayuda para calentamiento, no una garantía de equilibrio
térmico. En capturas posteriores sin cortar alimentación se puede usar
`--warmup 0`, si la temperatura ya está estable.

La detección estadística ayuda a rechazar vibración/movimientos; no demuestra
inmovilidad absoluta: una rotación constante suave podría confundirse con sesgo.
El operador debe asegurar que la placa o vehículo están realmente quietos.

## Giróscopo: calibración inicial

Sustituir `PUERTO` por la identidad del puerto serie del S3:

```bash
python tools/imu_calibration.py capture PUERTO \
  --device-id SALUS-V3-001 --output calibrations/stationary.json

python tools/imu_calibration.py gyro \
  --capture calibrations/stationary.json --output calibrations/gyro-v1.json
```

No hace falta una orientación particular para el giróscopo. Se utiliza el
promedio de cada eje como sesgo: `gyro_corregido = gyro_original - sesgo`.
No se resta nada del acelerómetro en esta operación.

## Acelerómetro: seis posiciones antes de instalar

Apuntar sucesivamente cada eje físico del sensor hacia arriba y hacia abajo.
`x+` significa que el eje +X apunta arriba y debe medir aproximadamente +g;
`x-`, que apunta abajo y debe medir -g. Lo mismo para Y/Z. No interpretar las
caras del encapsulado como ejes del vehículo: comprobar orientación Bosch en
el dibujo y con el diagnóstico raw. Mantener la placa quieta en cada posición.

Para cada pose `x+`, `x-`, `y+`, `y-`, `z+`, `z-`, ejecutar por separado (reemplazar
`POSE` en ambos lugares):

```bash
python tools/imu_calibration.py capture PUERTO \
  --device-id SALUS-V3-001 --pose POSE --warmup 0 \
  --output calibrations/POSE.json
```

Después calcular el perfil completo, conservando la calibración del giróscopo:

```bash
python tools/imu_calibration.py accel \
  --captures calibrations/x+.json calibrations/x-.json \
             calibrations/y+.json calibrations/y-.json \
             calibrations/z+.json calibrations/z-.json \
  --base calibrations/gyro-v1.json --output calibrations/full-v1.json
```

Por eje: `offset = (media_positiva + media_negativa) / 2`,
`escala = 2g / (media_positiva - media_negativa)`, con `g=9.80665 m/s²`.
La corrección es `(valor_original - offset) * escala`. La gravedad se conserva:
no se obliga a que el acelerómetro quieto entregue cero en todos los ejes.

Las seis capturas deben corresponder a la misma etiqueta y configuración.
Se comprueban orientación, signo y residuales del ajuste. No se admite repetir
una pose como sustituto de otra. Esta versión implementa un modelo diagonal;
si hay desalineamiento importante el ajuste se rechaza en lugar de inventar
una matriz que no puede estimarse con las suposiciones actuales.

## Ver los datos corregidos

```bash
python tools/usb_diagnostics.py PUERTO --imu \
  --device-id SALUS-V3-001 --calibration calibrations/full-v1.json
```

Mantiene `raw` y añade `uncorrected_m_s2` / `uncorrected_rad_s`. Los campos SI
principales muestran valores corregidos solo si el vector es válido y no está
saturado. `calibration.gyro_applied` y `calibration.accel_applied` indican qué se
aplicó. `calibrated` solo es true si se aplicaron ambas correcciones.

Un perfil solo de giróscopo es válido: no afirma calibración del acelerómetro.
No se admiten datos ya corregidos como entrada para recalcular o aplicar un
perfil por segunda vez. Perfil de otra etiqueta, frame/configuración incorrectos
o coeficientes inválidos se rechazan. La herramienta no rota ejes ni calcula
orientación o rumbo.

También puede procesarse un snapshot JSON guardado, sin puerto serie:

```bash
python tools/imu_calibration.py apply --device-id SALUS-V3-001 \
  --profile calibrations/full-v1.json --snapshot snapshot-raw.json
```

## Reajustar el giróscopo ya instalado

Dejar el vehículo inmóvil, esperar estabilización y registrar una captura nueva
con la misma etiqueta, como en la calibración inicial. Calcular después:

```bash
python tools/imu_calibration.py gyro \
  --capture calibrations/stationary-new.json \
  --base calibrations/full-v1.json --output calibrations/full-v2.json
```

Se actualiza solo el sesgo/estadística del giróscopo. El perfil anterior queda
intacto; el nuevo referencia su identificador y conserva el acelerómetro.
No es necesario inclinar, levantar ni desmontar el vehículo.

## Calidad y persistencia

Límites iniciales de aceptación, sujetos a validación física, no garantía de
precisión del robot:

| Comprobación | Criterio |
| --- | --- |
| Captura | 100..20000 snapshots únicos; ambos sensores con al menos 9 s de datos |
| Tiempos | Estrictamente crecientes, sin reinicio de sensor ni saltos mayores a 100 ms |
| Validez | Sin datos inválidos/saturados; antigüedad máxima 50 ms |
| Ruido estacionario | Desvío estándar por eje: accel ≤0.1 m/s², gyro ≤0.005 rad/s |
| Magnitud accel | Dentro de 1.5 m/s² de g |
| Sesgo gyro | Norma ≤0.05 rad/s |
| Temperatura | Entre -40 y 85 °C; cambio ≤2 °C en una captura; diferencia de medias entre poses ≤5 °C |
| Seis posiciones | Componente principal a ≤1.5 m/s² del ±g esperado; componentes restantes ≤1.5 m/s² |
| Ajuste | Residual vectorial por pose ≤0.35 m/s²; offset por eje ≤1.5 m/s², escalas 0.8..1.2 |

Si falla calidad no se publica un archivo de captura/perfil como exitoso.
No hay opción para forzar aceptación de movimiento. Las varianzas guardadas
representan dispersión de esta captura, no la incertidumbre total para un EKF.
Una temperatura de uso a más de 10 °C de la de calibración genera aviso, sin
recalibrar ni extrapolar coeficientes automáticamente.

Archivos JSON schema_version=1: etiqueta, IDs/modelo de adquisición, frame,
ID UUID de perfil, fecha UTC, métodos, coeficientes, estadísticas y temperatura.
Se rechazan NaN/Infinity y claves JSON duplicadas. Escritura con archivo temporal,
fsync y publicación atómica create-only: nunca se reemplaza un archivo existente.
Usar un nombre nuevo por ajuste y respaldar perfiles/capturas antes de despliegues.
No hay activación automática de la fuente operativa. El observador ROS de
`salus_robot` ya acepta este esquema v1 y aplica correcciones compatibles;
la selección para el EKF permanece pendiente de validación física.

## Verificación realizada

```bash
python -m unittest discover -s tests -p test_calibration.py -v
python tools/test_imu.py
python tools/test_protocol.py ../salus_robot/src/salus_control/salus_control/rpy_esp32_comms
```

Doce tests de calibración con datos sintéticos de errores conocidos, captura
con reloj virtual, recuperación de USB fragmentado/corrupto, preservación de raw,
actualización parcial, rechazo de fallos y CLI offline. Pasaron también las
regresiones del driver Bosch simulado y del protocolo. No se calibró ninguna
placa física. El firmware y el formato USB no se modificaron en esta entrega.
