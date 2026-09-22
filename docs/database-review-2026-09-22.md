# Revisión técnica de datos — 22 de septiembre de 2026

## Datos y utilización

El catálogo técnico y los anuncios de mercado siguen siendo tablas relacionadas,
no inventario ficticio. Las referencias se vinculan a categoría, marca y modelo.
Cada especificación conserva unidad, evidencia, documento y alcance regional;
los periodos documentados no se convierten en años exactos de otra unidad.

| Cobertura del paquete | Total |
| --- | ---: |
| Referencias técnicas | 34 (antes: 19) |
| Modelos distintos | 32 |
| Marcas | 9 |
| Referencias de excavadoras / compactadores / montacargas | 18 / 10 / 6 |
| Valores técnicos documentados | 112 |
| Modelos con periodo documentado | 5 |
| Anuncios individuales de mercado / modelos cubiertos | 4 / 2 |

La ampliación y sus fuentes se detallan en
[catálogo revisado](catalogue-expansion-2026-09-22.md). Se añadieron excavadoras
Caterpillar y Volvo, compactadores Wacker Neuson y montacargas Toyota. Los
anuncios individuales de Toyota complementan los de Caterpillar 320D L.
Son precios solicitados, sin conversión de moneda ni ajuste inventado por horas.

El catálogo local revisado puede resolver consultas compatibles sin nuevas
llamadas de pago. Si la identidad o el alcance no coinciden, se conserva la
investigación externa existente; no se atribuyen datos de otro modelo.

## Administración

- La base técnica muestra número de campos, periodos, rangos observados,
  moneda, país, tipo de precio y número de unidades independientes.
- Filtros por disponibilidad de periodos y anuncios recientes, junto con los
  filtros de categoría, marca/modelo, estado y mercado.
- El detalle reúne documentación del mismo modelo sin mezclar variantes ni
  convertir una ficha regional en una especificación universal.
- Las referencias antiguas siguen disponibles como historial. Las de mercado
  salen del cálculo vigente después de 30 días desde su consulta.
- Las acciones de aprobación y desactivación son atómicas y auditadas:
  si una aprobación falla, se revierte toda la selección. Requieren permiso
  de edición. Se puede desactivar un registro antiguo con contenido inválido.

## Integridad y estimaciones

La migración `0015_reference_integrity` incorpora restricciones en la base:
referencias activas sólo si están aprobadas, periodos en orden y precios mayores
que cero. La validación de formularios e importadores también rechaza fechas de
consulta futuras y años posteriores al siguiente año calendario.

Los importadores mantienen las ediciones administrativas del paquete instalado,
validan los manifiestos SHA-256 y rechazan identidades duplicadas en una misma
importación. Los bloqueos de categoría serializan importaciones concurrentes;
los anuncios conservan su URL única. Un vínculo ambiguo entre marcas o modelos
queda sin asignar para evitar fusiones incorrectas.

La investigación y el panel utilizan la observación más reciente de cada unidad.
La clave normaliza espacios y mayúsculas; las URLs sin identificador de unidad
se comparan sin rastreadores y con sus parámetros ordenados, conservando los
identificadores funcionales. Elegir primero la observación reciente impide que
una publicación antigua reaparezca porque su reemplazo tenga otra condición.

Los rangos separan país, moneda, precio anunciado/venta, condición y configuración
documentada. No se promedian anuncios con combustibles o configuraciones
contradictorias. Los valores «Unknown», «N/A» o «Por confirmar» no se envían como
restricciones reales a una búsqueda de pago.

El reconocedor de modelos admite puntos internos, como `307.5`, manteniendo
el rechazo de modelos distintos (`307`, `307.50`, `307.5D`).

## Validación y límites

La revisión final pasó 951 pruebas de servidor y 1.298 subpruebas, además de la
batería DOM de interfaz (catálogo, selección de categoría, inicio guiado,
formulario rápido, contraseñas y notificaciones). `manage.py check`,
`makemigrations --check --dry-run` y `git diff --check` finalizaron sin errores.

Las pruebas de servidor usan SQLite aislado; no escriben en Neon. La revisión
previa de PostgreSQL se realizó en una transacción de sólo lectura y no encontró
precios no positivos, periodos invertidos ni referencias activas sin aprobación.
El despliegue aplica la migración y el paquete mediante el procedimiento
idempotente existente. No cambia fichas ni correcciones de anunciantes.

El catálogo todavía cubre una selección de modelos, no todas las máquinas del
mundo. Sólo algunos tienen periodos históricos o suficientes comparables de
precio. La ampliación no incorpora reconocimiento por comparación con una
biblioteca propia de imágenes ni conecta la base maestra MySQL, cuyo esquema
y acceso siguen pendientes. No se han cambiado proveedores ni presupuestos de IA.
