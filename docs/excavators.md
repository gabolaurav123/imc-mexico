# Recorrido especializado de excavadoras

Implementación sobre el módulo existente, 18 de septiembre de 2026. No se añade
un sistema de cuentas ni se sustituye la arquitectura de Django/PostgreSQL.

## Del tipo de máquina al borrador

`category_profiles.py` publica el catálogo local y el perfil de excavadoras.
La búsqueda inicial no llama a Internet ni a un modelo. La selección se guarda
como declaración del propietario. «No estoy seguro» conserva la categoría vacía.
Las categorías existentes mantienen sus campos; la especialización no las
convierte en excavadoras.

El perfil separa familia, rodamiento, pluma, brazo/balancín, tamaño y aplicación.
La potencia neta/bruta/nominal es independiente del combustible. Placa y serie
son opcionales. Se puede añadir una placa después y preparar otra revisión.

## Lectura, conocimiento y búsqueda

`processing.py` conserva el worker, los presupuestos y los modelos configurados.
Cada fotografía tiene su lectura, relevancia, calidad y evidencia. Las lecturas
se consolidan antes de la investigación. Si hay varias máquinas o contradicción
con la categoría elegida, no se mezclan sus campos ni se inicia investigación
de una identidad arbitraria. El propietario puede retirar fotos o corregir el
tipo y volver a preparar la ficha.

Una lectura ya completada puede reutilizarse en otro trabajo del mismo equipo y
propietario cuando coinciden archivo/hash, propósito, categoría/perfil, modelo,
versión de instrucciones y datos declarados. No se reutilizan lecturas de un
resultado bloqueado por varias máquinas. Se contabilizan únicamente nuevas
llamadas. La admisión mantiene las reservas conservadoras y límites anteriores.

La biblioteca `TechnicalReference` conserva categoría, marca, modelo, variante,
generación, mercado, periodo documentado, especificaciones, fuente, fecha,
versión y revisión. La recuperación exige coincidencia exacta compatible y
referencia aprobada/activa. Sus valores atraviesan el normalizador y manifiesto
firmado existentes. Una especificación de modelo sigue pendiente de comprobar
en la unidad. Ninguna corrección del propietario modifica la biblioteca global.

Cobertura inicial de la biblioteca: **una referencia Caterpillar 320 Tier 3,
mercado MX**, con potencia neta, peso y profundidad de excavación. No se presenta
como una base universal de series. La investigación externa existente permanece
como respaldo cuando no hay una referencia local aplicable. `knowledge/excavadoras`
documenta las fuentes oficiales y el alcance exacto.

`seed` instala esa referencia inicial sin sobrescribir cambios administrativos.
`import_technical_knowledge --path ...` importa archivos locales; los nuevos o
modificados quedan pendientes/inactivos hasta revisión. Administración permite
editar, aprobar y desactivar referencias con auditoría.

## Datos, cambios y estimaciones

`Machine.data` continúa siendo el borrador editable. Se validan números finitos,
años e intervalos; desconocido se guarda como null. Los separadores ambiguos de
miles se rechazan en campos numéricos. Las medidas históricas libres se conservan,
pero sólo una cantidad con unidad reconocida se normaliza para búsqueda. Por
ejemplo, `21.5 t` se proyecta como `21500` kg; un texto sin unidad no se adivina.

Las horas requieren lectura o declaración; no se calculan por desgaste. Se
conservan base y fecha. Condición de uso, conservación y funcionamiento siguen
separados. El origen de fabricación requiere evidencia; no deriva de la sede del
fabricante ni de la ubicación de la conexión.

Cada instantánea añade una proyección `structured` y columnas indexadas en
`MachineVersion`: categoría, identidad, rodamiento, horas, años, precio/moneda,
ubicación, conservación, peso en kg y profundidad en m. Las migraciones 0011 y
0012 proyectan exclusivamente los snapshots históricos; no toman los valores
actuales del borrador ni cambian decisiones de aprobación.

La estimación conserva rango, moneda, mercado, fecha y precio sugerido. Su
evidencia y comparables siguen privados. Se mantiene el mínimo de dos unidades
independientes y comparables compatibles, sin conversiones ni depreciaciones
inventadas. El país declarado prioriza el mercado. Si no alcanza la evidencia,
se mantiene la ficha y una indicación privada para afinarla.

El precio solicitado se establece por el propietario, incluso si usa el botón
«Usar precio sugerido». El análisis no lo rellena por sí mismo. El valor de
referencia continúa identificado como «Estimación orientativa, editable y sujeta
a confirmación».

Los cambios manuales y borrados intencionales se protegen. Las propuestas que
contradicen lo guardado pueden revisarse conjuntamente. La aplicación exige una
revisión vigente; no permite reutilizar un análisis tras otra edición. Cambiar
identidad invalida referencias y valoraciones automáticas incompatibles. Los
datos publicados permanecen en su versión aprobada hasta la revisión siguiente.

## Publicación, buscador y MySQL

`public_data.py` aplica una proyección permitida desde el servidor para fichas,
PDF, tarjetas y exportación. Oculta vacíos, identificadores privados y material
interno. No se publican listados de fuentes ni comparables. Los defectos descritos
con valor sí se conservan. El rango de año no se transforma en un año exacto.

`/maquinaria/` consulta columnas tipadas de versiones aprobadas y publicaciones
compartidas habilitadas. El borrador mutable no participa. Las cantidades
ausentes no equivalen a cero; un filtro monetario exige moneda. El catálogo
distingue año exacto e intervalo aproximado y conserva los filtros al paginar.

El ZIP editorial mantiene identificador de máquina, número de versión, fotos
autorizadas y `publicacion.json`, ahora con datos públicos y proyección numérica
`structured`. Es el contrato de salida para adaptar al esquema real de MySQL:

| Origen | Destino lógico pendiente de mapear |
| --- | --- |
| `machine_id` + `version` | Clave estable e idempotencia de publicación |
| `category`, marca/modelo/variante | Relaciones del catálogo de la web principal |
| `structured.hours`, `year`, intervalos | Columnas numéricas independientes |
| `structured.weight_kg`, `digging_depth_m`, `power_kw`, `capacity_m3` | Unidades canónicas |
| `structured.price`, `currency` | Precio aceptado y moneda |
| País/región/ciudad | Ubicación declarada del equipo |
| `assets` | Archivos revisados y autorizados |

**MySQL no está conectado.** Faltan su esquema, acceso y reglas de integración.
No se crean tablas supuestas ni se declara sincronización ejecutada. El receptor
debe validar este contrato, mapear categorías/unidades y aplicar actualizaciones
por identificador+versión dentro de una transacción. Los secretos y las llamadas
de IA permanecen en el backend.

## Verificación

Pruebas automatizadas cubren categoría opcional, fotografías distintas,
reutilización de lecturas, prohibición de horas estimadas, números/fechas,
protección de correcciones, concurrencia, biblioteca exacta, precios separados,
filtros combinados y privacidad en HTML/PDF/ZIP. Las respuestas del proveedor en
estas pruebas se simulan: validan el proceso y las defensas, no garantizan que
cualquier fotografía real produzca un modelo, año o precio.

Abrir, editar, filtrar, paginar o descargar un PDF no ejecuta análisis de pago.
No se han aumentado límites de consumo ni se ha incorporado Astra.

Verificación local final de esta entrega: `pytest -q` con FFmpeg disponible:
**885 pruebas y 1219 subpruebas aprobadas**. `npm run test:ui`, `manage.py check`
y `makemigrations --check --dry-run` aprobados. El paquete de interfaz incluye
las pruebas nuevas del selector y del perfil de excavadoras.
