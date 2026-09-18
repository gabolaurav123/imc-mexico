# Biblioteca inicial de excavadoras

Cobertura inicial: Caterpillar 320 **Tier 3** para el mercado MX. La referencia se
tomó el 18 de septiembre de 2026 de la ficha oficial de Caterpillar. Incluye
potencia neta ISO 9249, peso operativo y profundidad máxima; se recupera sólo
cuando la variante Tier 3 y el mercado MX están explícitamente confirmados. Cada cifra es una
especificación del modelo, no una confirmación de la unidad anunciada.

La taxonomía usa familia hidráulica, rodamiento, pluma y brazo/balancín como
dimensiones separadas. Cat distingue excavadoras por tamaño, demolición, largo
alcance y ruedas en su catálogo oficial; sus fichas 320 y 395 documentan que el
largo alcance depende de configuraciones de pluma y brazo. Las referencias se
mantienen con URL, versión y fecha de consulta en cada JSON.

Usa `python manage.py import_technical_knowledge --path knowledge/excavadoras`.
El comando sólo lee archivos locales y deja referencias nuevas o cambiadas como
pendientes e inactivas. Un administrador autenticado debe revisarlas y aprobarlas
antes de que la recuperación exacta pueda usarlas.

## Catálogo técnico ampliado (18 de septiembre de 2026)

`catalogo_tecnico_us_2026-09-18.json` añade ocho modelos y nueve referencias de fabricante (diez referencias totales, incluyendo la 320 MX):

| Marca | Modelo / variante | Mercado de la ficha | Desplazamiento | Cobertura documentada |
| --- | --- | --- | --- | --- |
| Caterpillar | 319 Tier 4 / Stage V | US | Orugas | Potencia neta ISO 9249, peso, profundidad y cucharón GD configurado |
| Caterpillar | M315 Tier 4 / Stage V | US | Ruedas | Potencia ISO 14396, peso máximo, profundidad y cucharón GD configurado |
| Komatsu | PC220LC-12 | US | Orugas LC | Potencia, rango de peso y rango de capacidad de cucharón |
| Komatsu | PC290LC-11 SLF | US | Orugas LC, frente largo | Potencia, rango de peso y capacidad de cucharón SLF |
| John Deere | 160 P-Tier | US | Orugas | Potencia neta ISO 9249, peso, profundidad y cucharón de la configuración publicada |
| John Deere | 210 P-Tier | US | Orugas | Potencia neta ISO 9249, peso, profundidad y cucharón de la configuración publicada |
| Volvo | EW160E Stage IV / Tier 4f | US | Ruedas | Potencia bruta, rango de peso, profundidad y capacidad con configuración publicada |
| Volvo | EC210B, “2009 specifications” | Global, archivo | Orugas | Potencia, rango de peso, capacidad y periodo de producción literal 2003–2009 |

Las fichas US se recuperan solamente cuando se confirma ese mercado en la
unidad. Las referencias de emisiones y la variante histórica también requieren
una coincidencia literal; no se usan para una versión genérica. La EC210B tiene una referencia global independiente para su periodo, utilizable sin conocer la configuración 2009. Es la
única ficha con periodo: el archivo oficial declara 2003–2009, pero los valores
numéricos son los de su especificación 2009. Ninguna referencia permite deducir
el año ni la configuración física de una unidad anunciada.


## Base de datos operativa

El despliegue ejecuta `seed`: instala sólo los archivos incluidos y verificados
por SHA-256 en `knowledge/bundled.json`. Cada registro se guarda en
`TechnicalReference` de PostgreSQL, vinculado a `Category`, `Brand` y
`EquipmentModel`. La carpeta versiona las fuentes iniciales; la consulta del
análisis se realiza contra la base de datos, no contra una carpeta enviada a IA.

La instalación es idempotente: no duplica referencias ni sustituye ediciones o
reactiva datos deshabilitados por el equipo. Los archivos importados por el
comando anterior siguen entrando pendientes; no los aprueba `seed` después.
El panel **Base técnica** permite buscar, consultar cobertura, evidencias y
acceder a la edición existente. Requiere permiso interno y verificación de acceso.

Los intervalos de peso/capacidad no se reducen a una cifra inventada; conservan
su alcance de configuración. La profundidad en pies y pulgadas sí se convierte
exactamente a metros para filtrar. Los años del modelo orientan un intervalo,
no una fecha de fabricación de la unidad. No hay un decodificador universal de
series, ni datos de ubicación deducidos de la apariencia del terreno.
