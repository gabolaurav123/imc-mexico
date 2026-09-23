# Adaptación a IMC México: informe técnico y contrato de entrega

Fecha de comprobación: 23 de septiembre de 2026. Proyecto existente: `gabolaurav123/imc-mexico`.
Base de código anterior: `4b3762d7d0fcd4e5171877a09886eb789ad2b96f`.

## 1. Resultado y límite comprobado

Se amplió el módulo existente para preparar entregas reproducibles, conservar su
identidad, comprobar correspondencias de catálogo y registrar acuses cotejados
por un operador autorizado. Se corrigieron diferencias entre las dos exportaciones
y el etiquetado de imágenes. No se reconstruyó el sistema ni se creó otro catálogo.

**La integración automática con el servidor principal todavía no está conectada.**
No se obtuvo sesión administrativa, código fuente, esquema MySQL ni una API
autorizada del sitio principal. La nueva pantalla lo indica expresamente. Las
pruebas con acuses sintéticos son pruebas locales: no constituyen una publicación
real ni una respuesta de IMC México.

## 2. Qué se pudo comprobar en cada sistema

### Módulo desarrollado

- Django 5.2, PostgreSQL/Neon, plantillas de servidor y JavaScript existentes.
- Conexión real de lectura verificada: PostgreSQL 18.6; migración inicial 0015.
- Antes de cambios: 54 máquinas, 15 usuarios, 74 archivos, 9 versiones y 2 destinos
  de publicación. Solo un destino `main`, en estado `exported`; ningún ID remoto
  duplicado. No había confirmación de entrega automática al sistema principal.
- `Machine` identifica la ficha local mediante UUID; `MachineVersion` guarda su
  instantánea. `Publication` separa los destinos compartible y principal.
- `User.company` es texto, no una relación con una empresa del sistema principal.
  `Machine.owner` es la cuenta responsable del módulo; no acredita propietario
  jurídico, vendedor o contacto comercial distinto.
- Archivos privados mediante `PrivateStorage`; originales y vistas optimizadas
  se sirven por rutas con autorización. No hay conexión MySQL en el navegador.
- La configuración local contiene Neon, IA y correo del módulo. No contiene un
  receptor/API/SSO o credencial MySQL del sitio principal. La búsqueda del repositorio
  IMC disponible encontró este módulo, no el código de la web principal.

### Sitio principal

Se observaron páginas reales del [sitio principal](https://www.imcmexico.com.mx/),
su flujo público de publicación, fichas, HTML y recursos de lectura. Apache,
`PHPSESSID`, rutas PHP y jQuery son evidencias de su implementación pública;
**no prueban el motor ni las tablas internas**.

La sesión disponible abre sin autenticar. «Publicar Maquinaria» conduce a
[datos de registro](https://www.imcmexico.com.mx/registro-de-datos-para-la-publicacion-gratuita-de-maquinaria).
No se creó otra cuenta ni se enviaron formularios comerciales. La ruta administrativa
indicada por robots muestra un índice de directorio, no una sesión de gestión útil.
No se exploraron rutas de escritura ni se alteraron anuncios reales.

La investigación de fichas e imágenes queda documentada con ejemplos verificables
en [Observaciones del sitio principal](main-site-observations-2026-09-23.md).
Los nombres de tablas, claves internas, permisos, entidades de empresas y expedientes
de compra siguen sin poder verificarse.

## 3. Recorrido de una ficha

1. El usuario guarda un borrador y fotografías privadas; el análisis/edición funciona
   igual que antes y conserva las correcciones humanas.
2. El envío crea una instantánea y una solicitud de revisión.
3. El equipo revisa anunciante, contenido y autorización individual de fotografías.
4. Aprobar fija la versión autorizada. No publica en el sitio principal.
5. Exportar construye JSON, PDF y archivos permitidos. Registra una entrega con
   UUID propio y huella SHA-256 del JSON canónico. No ejecuta llamadas al receptor.
6. Un receptor autorizado deberá importar o actualizar por la identidad estable y
   devolver su acuse. Este receptor **no está implementado en la web principal**.
7. Con un acuse real, el operador puede cotejarlo y registrarlo en «Integración IMC».
   La vinculación y la publicación son estados distintos: `acknowledged` no publica;
   `published` exige que el operador compruebe la publicación y el enlace HTTPS.

La disponibilidad (`available/reserved/sold/withdrawn`) continúa separada de la
revisión editorial y del último acuse remoto. Retirar una ficha local no retira
automáticamente el anuncio principal. Se conserva y se muestra la fecha del último
acuse; la actualización posterior aparece pendiente.

## 4. Identificadores: ninguna conversión improvisada

| Dato | Uso y regla |
|---|---|
| `Machine.id` | UUID local, estable; se conserva con sus relaciones históricas. |
| `Machine.folio` | `IMC-` más el primer segmento UUID. Es un folio local. |
| `IntegrationDelivery.id` | UUID de entrega y clave de idempotencia. Reexportar el mismo contenido/versión conserva esta clave. |
| `payload_sha256` | Huella del JSON ordenado canónicamente; identifica el contenido de esa entrega. |
| `Publication.external_id` | ID canónico devuelto por el sistema principal, texto opaco de hasta 200 caracteres. No se obtiene del título o de la URL. |
| `external_reference` | Referencia comercial visible, separada del ID canónico; texto, incluidos ceros iniciales. |
| `external_url` | Enlace de consulta, nunca sustituto de la identidad. HTTPS de `imcmexico.com.mx` o `www.imcmexico.com.mx`. |

En las fichas públicas se observan referencias de 16 dígitos. Que el HTML reutilice
ese valor como `IdMaquina` no demuestra su llave primaria o algoritmo de generación.
No se generan esos números localmente ni se renumeran registros históricos.

La base local impide que dos publicaciones principales compartan un ID canónico no
vacío. `current_delivery` señala la entrega activa. Acuses de otra ficha, otra versión,
otra huella, una entrega sustituida, un anunciante suspendido o permisos de fotos
revocados son rechazados. Los acuses contradictorios tampoco reemplazan al anterior.

**Respuesta perdida:** la preparación y el reintento local se prueban sin duplicar
entregas. La garantía de no duplicar anuncios requiere además una restricción única
y recuperación por clave en el receptor. Ese extremo permanece pendiente. Una
respuesta histórica no se puede reutilizar para pisar un acuse remoto posterior;
la operación se detiene y requiere una nueva versión/entrega revisada.

## 5. Mapeo verificable de campos

«Destino observado» nombra etiquetas públicas, no columnas SQL inventadas. Los IDs
del contrato de adaptador son nombres locales propuestos hasta conocer el esquema.

| Origen del módulo | Destino observado / pendiente | Formato y validación | Obligación / responsable |
|---|---|---|---|
| `Machine.id` | Correlación del módulo; campo remoto pendiente | UUID textual, inmutable | Obligatorio para entrega; módulo |
| Acuse `remote_id` | Llave real pendiente de comprobar | Texto, sin coerción numérica ni recorte | Obligatorio para vincular; principal |
| Acuse `external_reference` | «Referencia» pública | Texto independiente; no generarlo | Principal; puede no existir aún |
| `User.id` | Usuario principal no accesible | Relacionar por ID estable autorizado | Pendiente; no vincular por coincidencia de correo |
| `User.company` | Empresa principal no accesible | Texto original; no equivale a ID | Opcional local; principal debe definir relación |
| `User.phone/email` | Contactos privados / rol comercial pendiente | Teléfono internacional y correo ya validados | No exportar como contacto público por defecto |
| Categoría de la versión | «Tipo de Máquina» | Coincidencia exacta en catálogo autorizado | Para integración final, ID principal pendiente |
| `data.brand` | «Marca» | Texto original + ID verificado | No confundir CAT/Caterpillar sin alias aprobado |
| `data.model` | «Modelo» | Texto original + ID con padres compatibles | No eliminar sufijos, variantes ni decimales |
| `data.year` | «Año» | Año exacto si existe | Opcional; anunciante/cotejo técnico |
| `estimated_year_from/to` | Campo remoto no comprobado | Rango aproximado separado | No convertir en año exacto ni escribirlo en «Año» |
| `data.hours` | «Horas» | Número, normalización estructurada | Opcional; nunca rellenar desconocido con cero |
| `data.price/currency` | «Precio» y moneda | Importe y moneda explícita | Precio solicitado confirmado, no valoración automática |
| Valoración orientativa | Destino no comprobado | Se conserva privada según proyección existente | No sustituye precio anunciado |
| País/estado/ciudad de ubicación | Ubicación pública | Texto estructurado disponible | No deducir ubicación física por IP o país de fabricante |
| Peso/profundidad/potencia y demás datos | Campos técnicos remotos pendientes | Valores públicos y normalizados disponibles | Adaptar unidades tras confirmar campos reales |
| `description` | Descripción de ficha | Texto público autorizado | Versión aprobada; no importar borrador más reciente |
| `Asset.id` + manifiesto | Fotos/galería | UUID local, bytes, MIME, tamaño, SHA-256, orden, portada | Traducir a IDs/rutas del receptor, sin usar nombres históricos |
| `Machine.availability` | Disponibilidad remota pendiente | Estado separado de publicación | Confirmar autoridad principal antes de sincronizar |
| Compra/adquisición/inventario propio | No accesible | Sin equivalencia implementada | No inferir de «vendida» ni crear expedientes ficticios |

El borrador conserva sus validaciones vigentes; esta adaptación no añade campos
obligatorios al anunciante. La revisión y exportación siguen exigiendo la autorización
existente. Los campos exigidos por el principal no pueden definirse sin su esquema.

## 6. Catálogo e incidencias

`integration_catalogue.resolve_catalogue` compara un extracto autorizado de rutas
tipo/marca/modelo. Es una función sin red ni escritura en base: no es otro catálogo.
Normaliza mayúsculas, acentos, espacios y guiones, conserva decimales y sufijos, y
acepta únicamente alias explícitos. Detecta colisiones y padres incompatibles.

La pantalla informa «Tipo de máquina no encontrado», «Marca no encontrada»,
«Modelo no encontrado» o ambigüedad. Conserva el texto y las correcciones. Cuando
el responsable dé de alta un modelo en el principal, puede volver a comprobarse
el extracto sin recapturar la ficha. **El alta remota, comprobación de duplicados
en su transacción y persistencia de asociaciones por ID están pendientes del acceso.**
No se crean modelos genéricos ni se cargó el catálogo público como si fuera maestro.

Contrato local de una fila de comprobación (los nombres no son columnas de MySQL):

```json
{"type_id":"ID_REAL","type":"TIPO","brand_id":"ID_REAL","brand":"MARCA","model_id":"ID_REAL","model":"MODELO"}
```

## 7. Fotografías y documentos

Se observó la forma `{Referencia}_{otro-numero}-{01..NN}.jpg`, con variantes
`photos/` y `photosb/`. La segunda secuencia numérica no se interpretó como timestamp
ni llave. La primera foto seleccionada figura como portada en los ejemplos.
Los límites reales de carga y dimensiones de originales no se conocen.

La exportación ahora describe los bytes realmente incluidos: PNG sigue siendo PNG,
JPEG es JPEG y QuickTime no se etiqueta MP4. Incluye dimensiones/proporción para
imágenes, tamaño, SHA-256, posición y una portada determinista. No cambia ni recorta
originales. Excluye fotos ajenas, placas detectadas y documentos privados; vuelve a
comprobar autorización al preparar, finalizar y reconocer la entrega.

Límites de construcción actuales: 100 MiB por archivo y 128 MiB acumulados. No se
presentan como límites de IMC principal. Las rutas de almacenamiento privado no
aparecen en el JSON. Tanto ZIP como JSON administrativo usan la misma proyección
pública; se cerró la divergencia que permitía que el JSON administrativo incluyera
campos internos adicionales.

No se inventaron categorías de documentos de compra. Cualquier adaptación de
expedientes conservará el acceso privado y requerirá conocer permisos y tipos reales.

## 8. Consulta en ambos sentidos y autoridad de datos

- El módulo abre el enlace asociado al ID reconocido, con el último acuse y fecha.
- Cada entrega aporta un enlace privado estable de retorno por UUID.
- `/panel/vinculos/imc/?id=<ID_CANONICO>` resuelve un ID reconocido a la ficha local;
  exige sesión y propiedad o permisos administrativos/MFA. Otras cuentas obtienen 404.
- Añadir ese enlace dentro del principal sigue pendiente de acceso a su código.
- No se transfieren credenciales al navegador ni se implementó escritura bidireccional.

Autoridad prevista: principal asigna sus IDs, catálogo y expedientes; módulo conserva
fotos aportadas, análisis, correcciones y versiones. La aprobación autoriza una
instantánea concreta. Precios, disponibilidad, personas y empresa requieren una
regla explícita de autoridad del principal antes de permitir actualizaciones.
Un título o correo parecido no autoriza una unión de registros.

## 9. Implementación, archivos y migración

| Archivo / grupo | Adaptación |
|---|---|
| `portal/models.py`, `migrations/0016_main_integration_ledger.py` | Campos de acuse, referencia separada, entrega activa, ledger y unicidades. Migración aditiva sin borrado ni conversión de IDs. |
| `portal/integration.py` | Preparación, huella, idempotencia local, validación/transacción de acuses y estado exportado. |
| `portal/export_payload.py` | Proyección y manifiesto común, bytes reales, límites y revisión de permisos de fotos. |
| `portal/integration_catalogue.py` | Resolución exacta de un extracto de IDs autorizado, sin crear un catálogo. |
| `portal/integration_views.py`, `config/urls.py` | Panel, comprobación, acuse manual y retorno privado por ID. |
| `portal/views.py`, `portal/admin.py` | Reutilización en exportaciones; eliminación del cambio arbitrario a publicado solo con ID/URL; historial de entregas de solo lectura. |
| Plantillas `integration_*`, `operations`, `panel_base`, `sheet`; regla CSS acotada | Acceso desde administración, consulta del registro reconocido desde la ficha privada y navegación de regreso, usando componentes actuales. |
| `test_main_integration`, `test_export_payload`, `test_integration_catalogue`, `test_integration_views` | Pruebas de contrato, privacidad, permisos, reintentos e incidencias. |

No se modificaron modelos de IA, presupuestos, análisis visual, años/precios estimados,
PDF, correos, cuentas existentes, catálogo comercial histórico ni diseño de la web principal.

## 10. Respaldo, compatibilidad y reversión

Antes de la migración se creó una copia privada PostgreSQL custom, verificada con
`pg_restore --list`, y un `git bundle` del código anterior. Manifest y SHA-256 están
en `backups/integration-2026-09-23/`, fuera del repositorio y con ACL privada.
Los originales multimedia no cambian: esta intervención no los mueve ni sobrescribe.

Se restauró la copia en PostgreSQL 18 local aislado (`127.0.0.1:55439`), se aplicó
0016 y se compararon los cinco conteos anteriores: sin diferencias. Se detuvo el
servidor de prueba al terminar. No se probaron altas o bajas destructivas en anuncios
reales. El respaldo no se subió a GitHub.

Reversión recomendada: desplegar el código anterior manteniendo las columnas/tablas
aditivas; el código previo las ignora. No ejecutar automáticamente el reverso de 0016
si ya contiene acuses, porque eliminaría su historial. Si se necesitara recuperar
datos, restaurar la copia en una base nueva, verificarla y cambiar el destino tras
evaluar los cambios posteriores; nunca restaurar encima de producción a ciegas.

## 11. Pruebas y resultados

- Suite completa del repositorio: **993 pruebas y 1 305 subpruebas aprobadas**,
  incluyendo vídeo con FFmpeg disponible.
- PostgreSQL real aislado: restauración + migración sin pérdida de registros y
  **25 pruebas de integración/exportación/pantallas aprobadas**.
- Comprobación posterior de autorización de fotos añadida al cierre: suite dirigida
  de los cuatro módulos nuevos **37 pruebas aprobadas**.
- `makemigrations --check --dry-run`: sin cambios pendientes.
- `manage.py check` y `git diff --check`: sin incidencias.
- Navegador: sesión sintética aislada, navegación administrativa, incidencia de
  catálogo y pantalla móvil de 390 px; sin desbordamiento horizontal de la página.
- Las suites DOM existentes comprueban catálogo, selector, entrada, perfiles,
  preparación rápida, contraseña visible y campana de notificaciones.

| Caso solicitado | Resultado comprobado |
|---|---|
| Guardado, análisis, revisión y exportación anteriores | Regresiones locales aprobadas; funciones conservadas. |
| Usuario/empresa existentes del principal | Bloqueado: faltan identidad y esquema principal. No se emparejó por correo. |
| Catálogo exacto, ausente y ambiguo | Probado con extractos aislados, incluidos IDs con ceros y variantes. |
| Alta de modelo faltante en principal | Pendiente de su mecanismo real; no se simuló un alta. |
| ID canónico y referencia visible | Persistencia/transacción probada con acuses sintéticos separados. Sin acuse real disponible. |
| Fotos, portada, pertenencia y privacidad | Probado con archivos sintéticos y formatos reales; permisos revocados rechazados. |
| Disponibilidad | Se mantiene separada; acuses de disponibilidad antigua rechazados. No sincroniza el principal. |
| Expediente de compra/documentos | Bloqueado: estructura y acceso no disponibles. |
| Consulta recíproca | Ruta privada local probada; enlace en principal pendiente. |
| Reintentos/duplicados/conflictos | Control local probado; deduplicación remota y pérdida de respuesta real pendientes del receptor. |
| Errores de almacenamiento y permisos | Fallan sin declarar exportación/publicación realizada; CSRF/MFA se conservan. |

## 12. Cambios indispensables frente a recomendaciones

### A. Módulo: implementado

Preparación consistente, manifiesto de imágenes, ledger, IDs separados, validación
de acuses, panel de seguimiento, comprobación de catálogo y retorno autenticado.

### B. Principal: indispensable para completar, pendiente de acceso

1. Revisar código/esquema y confirmar las claves, folios, actores, catálogo,
   disponibilidad, compras y reglas reales de imágenes.
2. Exponer o reutilizar un servicio autorizado de consulta e importación/actualización;
   aprovechar su lógica actual de alta y numeración. No generar SQL contra tablas adivinadas.
3. Mantener correlación única por módulo+UUID y deduplicación por entrega, con consulta
   del resultado tras un timeout. Devolver ID canónico, referencia, revisión y acuse.
4. Definir quién mantiene cada dato, validación de versiones y permisos de escritura.
5. Resolver autenticación compartida y vínculo de usuarios/empresa con IDs reales,
   y añadir enlace de retorno en la ficha/expediente existente.

Estos puntos no justifican reemplazar el sitio. Las rutas AJAX observadas no se
usan como API privada improvisada ni como permiso para escribir.

### C. Opcional, fuera de esta adaptación

Sincronización automática bidireccional, rediseño, migración tecnológica general,
reestructuración de compras y modernización amplia del frontal. La revisión pública
observó un directorio administrativo indexable y dependencias antiguas; corresponde
revisarlo con el responsable del alojamiento cuando exista acceso. No se cambiaron
permisos del servidor ni se realizaron pruebas de explotación.

### Bloqueo concreto restante

Hace falta una sesión autorizada del administrador/alojamiento o acceso al código
y esquema del sistema principal. La autorización del titular permite trabajar,
pero no crea esa conexión técnica. Sin ella no se puede afirmar que una máquina,
usuario, empresa o expediente haya quedado integrado o publicado realmente allí.
