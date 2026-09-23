# IMC México: análisis del sitio principal y adaptación del módulo

**Fecha:** 23 de septiembre de 2026.  
**Sitio analizado:** https://www.imcmexico.com.mx/  
**Sistema intervenido:** https://imc-mexico.seenode.app/ — repositorio `gabolaurav123/imc-mexico`.

## 1. Alcance y decisión de arquitectura

La web principal se usa como referencia comercial y funcional. Los cambios de
esta entrega se realizan en el módulo existente de SeeNode, conforme a la
aclaración del propietario. No se modifica el servidor del dominio principal.

El objetivo es que IMC pueda incorporar después el proceso de fotografía,
identificación, investigación, edición y revisión utilizando su propio frontal.
El módulo conserva Django, PostgreSQL, su worker y almacenamiento privado. No se
construye una segunda web principal ni se convierte código Python en PHP.

**Decisión recomendada:** conservar el motor como servicio y conectar el frontal
de IMC mediante adaptadores HTTP autorizados. Sus plantillas y su diseño pueden
permanecer en la web original. Copiar únicamente JavaScript o HTML no trasladaría
la cola de análisis, versiones, permisos, PDF ni almacenamiento.

Esta entrega mejora el contrato de consulta de la ficha y corrige filtros del
catálogo del módulo. La asignación de usuarios/empresas del principal, el catálogo
con IDs reales, la autenticación compartida y la escritura final en sus tablas
necesitarán un contrato y acceso cuando llegue la migración. No bloquean las
adaptaciones locales realizadas ahora.

## 2. Método y límites de la revisión

Se combinaron navegación real de escritorio y móvil, lectura de HTML/JavaScript
público, cabeceras HTTP, mediciones puntuales de descarga y revisión del código
del módulo. No se enviaron solicitudes comerciales, correos, SMS ni formularios
de registro. No se hicieron pruebas de explotación ni cambios en el principal.

La muestra incluye:

| Superficie | Qué se comprobó |
|---|---|
| [Portada](https://www.imcmexico.com.mx/) | Navegación, búsqueda rápida, opciones de tipo/marca/modelo, contenido comercial, semántica y ancho móvil. |
| [Búsqueda avanzada](https://www.imcmexico.com.mx/busqueda-de-maquinaria) | Referencia de 16 dígitos, filtros de tipo/marca/modelo, precio y año. |
| [Excavadoras](https://www.imcmexico.com.mx/catalogo-de-excavadoras-hidraulicas) | Listado, ordenación anunciada, filtros geográficos, disponibilidad, paginación y fichas enlazadas. |
| [Caterpillar 320D](https://www.imcmexico.com.mx/catalogo-de-excavadoras-hidraulicas-caterpillar-320d-1561145342951147) | Identificación, fotos, horas, año, precio/moneda, ubicación, cotización de traslado, contacto y acceso PDF. |
| [Plantas de concreto](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto) | Segunda familia de máquinas; estructura común del catálogo. |
| [Cementech C60](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto-cementech-c60-1668191915090848) y [Bohringer B120](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto-bohringer-b120-1709396833023629) | Identidad, precio, valores ausentes, fotos y metadatos públicos. |
| [Publicar maquinaria](https://www.imcmexico.com.mx/registro-de-datos-para-la-publicacion-gratuita-de-maquinaria) | Primer paso y controles de registro; no se creó una cuenta. |
| [Registro](https://www.imcmexico.com.mx/formulario-de-registro), [contacto](https://www.imcmexico.com.mx/datos-de-contacto), recursos y robots | Lectura pública parcial y enlaces; algunas consultas del lector web agotaron su tiempo. |

La acción de PDF abrió una pestaña, pero la política de URL del navegador impidió
abrir su destino. **No se evaluó el contenido ni el diseño del PDF del principal.**
La ficha virtual sí se inspeccionó. No se intentó eludir ese bloqueo.

La navegación pública permite comprobar lo que ve un visitante. No demuestra
tablas SQL, forma de guardar contraseñas, propiedad del inventario, expedientes
de compra ni lógica privada. Una referencia visible tampoco acredita la llave
primaria del sistema.

## 3. Qué hace hoy la web principal

### 3.1 Descubrimiento de maquinaria

El visitante puede entrar por categoría, buscar por tipo/marca/modelo, usar una
búsqueda avanzada por referencia y consultar máquinas similares. La estructura
de tipos y relaciones de catálogo ya existe y debe aprovecharse en la migración.

En portada se comprobaron 66 opciones en el selector de tipo, incluida la opción
inicial. La carga dependiente de marcas y modelos respondió al seleccionar
excavadoras y Caterpillar. El catálogo tiene campos separados para año, horas y
precio; esto confirma que la información del nuevo módulo debe permanecer en
campos estructurados y no únicamente dentro de una descripción.

En el listado de excavadoras se observó activada por defecto la opción que
incluye equipos apartados o vendidos. El precio aparece con `$` en las filas;
en la ficha examinada se aclara `USD`. La tabla anuncia ordenación por año, horas
y precio. También distingue todas las ubicaciones frente a sólo México.

### 3.2 Ficha y contacto

La ficha 320D examinada muestra referencia `1561145342951147`, año 2017, 464 horas,
precio 556.900 USD, ubicación Georgia, U.S.A., cuatro fotografías y una descripción
breve del accesorio. Estos son datos del anuncio observado; no una comprobación
independiente del equipo, su disponibilidad o su valor de mercado.

El precio de la máquina se distingue de un cálculo de flete y del total. Existen
selectores de destino, plataforma y seguro, contacto de IMC, envío de ficha por
correo/SMS y máquinas similares disponibles o vendidas. Se conservará esa
separación: una estimación de mercado no debe sobrescribir precio anunciado,
flete, impuestos ni importe total.

### 3.3 Publicación

El enlace de publicación conduce primero a datos de cuenta. El paso observado
pide email y muestra una contraseña sugerida; el DOM contiene campos de
contraseña con longitud máxima de 10 caracteres y sin controles nativos para
mostrarla. No se verificaron los pasos privados posteriores.

El módulo ya dispone de borrador, fotografías con placa opcional, análisis,
edición, ficha virtual/PDF, revisión y observaciones. En la integración definitiva
se debe enlazar la identidad existente de IMC, evitando exigir un segundo registro.
Mientras se usa como entorno independiente, sus cuentas conservan la protección
actual; retirarlas sin autenticación alternativa dejaría las fichas sin control.

## 4. Hallazgos y tratamiento recomendado

Las prioridades expresan impacto funcional: P1 afecta descubrimiento, confianza
o acceso; P2 mejora mantenimiento, calidad o rendimiento. No se declara una
incidencia crítica de seguridad sin evidencia.

| ID / prioridad | Evidencia y consecuencia | Qué hacer y dónde |
|---|---|---|
| M01 · P1 | En viewport de 390 px, `clientWidth=375` y `scrollWidth=992`. El principal requiere desplazamiento horizontal. | Conservar el frontal móvil del módulo; probar su catálogo y editor a 390 px. En la futura incorporación, adaptar el contenedor de IMC y añadir viewport tras probar sus estilos, no copiar tablas fijas. |
| M02 · P1 | Los desplegables rápidos cargaron, pero una pulsación de Buscar para CAT 320D no produjo navegación ni mensaje en la prueba. | En el módulo, usar consultas GET con parámetros y resultados visibles; evitar reconstruir rutas con nombres. La causa exacta del comportamiento del principal queda sin confirmar. |
| M03 · P1 | Apartadas/vendidas incluidas por defecto en el catálogo principal. | El módulo muestra disponibles inicialmente; permite consultar reservadas, vendidas o todas de forma explícita y etiqueta sus tarjetas. |
| M04 · P1 | Precio de listado sin código de moneda; ficha sí declara USD. | Mantener importe y moneda ISO separados en filtros, tarjetas, PDF y contrato. Ordenar/comparar precios sólo dentro de una moneda elegida. No convertir divisas sin una tasa, fecha y política definidas. |
| M05 · P1 | El módulo tenía código para `year_min/year_max`, pero no recogía esos parámetros y los ignoraba. | Corregido: rango de año efectivo, validación de enteros y límites, diferenciación exacto/aproximado, compatibilidad con `year` anterior. |
| M06 · P1 | El frontal original depende de HTML y handlers propios; no puede consumir una ficha editable del módulo sólo copiando plantillas. | Nueva consulta privada versionada de maquinaria en JSON. Reutilizar los POST existentes para guardar, analizar y enviar; conservar revisión y permisos. |
| M07 · P1 | La publicación del principal comienza con cuenta y no se comprobó relación con la cuenta del módulo. | Preparar autenticación compartida y relación de IDs al migrar. No emparejar personas sólo por correo ni desactivar autorización ahora. |
| M08 · P2 | En el catálogo aparecen DEERE y JOHN DEERE y variantes con espacios como 315 BL/315BL. | Tratar como candidatos a depuración, no fusionarlos automáticamente. Confirmar alias y relaciones con el catálogo maestro; conservar texto original y variante. |
| M09 · P2 | En el listado principal no siempre se explica lo que significa un dato ausente. Cementech muestra horas no disponibles. | El módulo mantiene ausentes los valores desconocidos, no los transforma en cero. Ocultar filas sin valor en la ficha pública y mostrar pendientes al editor. |
| M10 · P2 | Imágenes de la ficha usan dimensiones renderizadas fijas, incluso para originales de proporción distinta. Una tarjeta de portada contiene una URL absoluta concatenada detrás de `/photosb/`. | Mantener originales, dimensiones y manifiesto por UUID en el módulo. No importar literalmente rutas concatenadas ni renombrar fotos históricas. |
| M11 · P2 | La acción PDF observada es un `div` con `onclick`, sin la semántica de enlace/botón. | Conservar descarga y vista virtual accesibles del módulo. En el frontal definitivo usar enlaces/botones operables con teclado. |
| M12 · P2 | Muchos controles del principal carecen de etiquetas asociadas; en el árbol accesible WhatsApp aparece como `n`. | Mantener labels, estados de carga y botones descriptivos del módulo. Incorporar esos requisitos a las pruebas del frontal futuro. |
| M13 · P2 | Hay jQuery 1.6, handlers inline y miles de enlaces en la portada. | Reutilizar reglas de negocio del módulo como servicios; no trasladar dependencias del principal al motor de IA. Cambios graduales en el frontal cuando corresponda. |
| M14 · P2 | TTFB puntual de 5–8 s en tres páginas públicas; no es una medición de carga o de usuarios reales. | Medir por separado red, PHP, consultas y caché antes de optimizar. En el módulo, GET no ejecuta IA y el análisis sigue en cola persistente. |
| M15 · P2 | Metadatos públicos sin canónica/viewport en la muestra y microdatos de oferta sin moneda observada. | Al integrar, generar metadatos a partir de la versión pública aprobada y URL canónica del principal. No indexar borradores ni publicar datos privados por SEO. |
| M16 · P2 | Texto visible con codificación rota, por ejemplo `8 dÃas`. | Mantener UTF-8 del módulo y acordar conversión de entrada/salida con el principal, conservando una copia del original antes de convertir datos históricos. |

Las cabeceras, recursos, medidas y límites específicos se detallan en
[la auditoría técnica complementaria](audit-main-technical-2026-09-23.md).

## 5. Estructura de datos que debe viajar

La pantalla final puede cambiar; estos significados deben mantenerse.

| Concepto | Campo del módulo / salida | Regla de adaptación |
|---|---|---|
| Máquina local | UUID `Machine.id` | Estable; nunca convertirlo a una referencia de 16 dígitos mediante una fórmula. |
| Folio local | `Machine.folio` | Ayuda operativa del módulo; no es numeración IMC principal. |
| Identificador principal | `Publication.external_id` | Texto opaco devuelto/confirmado por el receptor. |
| Referencia comercial | `external_reference` | Separada del ID; preservar prefijos y ceros. |
| Tipo | `category`, relación local | Resolver después contra ID real de catálogo principal. No equiparar ID local al remoto. |
| Marca/modelo/variante | `data.brand/model/variant` y proyección estructurada | Campos separados, alias revisados y sufijos conservados. |
| Año exacto | `data.year` | Sólo año de la unidad identificado/confirmado; no extraer el centro de un rango para rellenarlo. |
| Año aproximado | `estimated_year_from/to` | Intervalo explícito, con su evidencia privada. No reemplaza año exacto. |
| Horas | `hours` | Dato numérico; cero válido sólo cuando es conocido. No calcularlo a partir de desgaste visible. |
| Precio solicitado | `price` + `currency` | Importe confirmado por el anunciante con moneda. |
| Estimación de mercado | Campos de valoración | Separada del precio solicitado y de flete; sugerencia editable, sin cifras inventadas. |
| Ubicación actual | País/estado/ciudad | Ubicación del equipo declarada o comprobada; IP y país de fabricante no la acreditan. |
| País de fabricación | `country_of_origin` | Separado de ubicación, dirección del fabricante y mercado de venta. |
| Disponibilidad | `available/reserved/sold/withdrawn` | Separada del estado editorial, anuncio publicado y compra. |
| Características filtrables | Horas, peso kg, profundidad m, potencia, etc. | Proyección tipada con unidades conocidas, además del texto original. |
| Fotos | UUID, MIME, hash, orden, portada, dimensiones | Pertenencia a la máquina y permisos comprobados. La placa no se vuelve pública por estar en la galería privada. |
| Serie y transcripción | Datos privados de la ficha | Sólo propietario/equipo autorizado; no pasan a catálogo/JSON público. |
| Usuarios/empresa | Identidades locales actuales | Conectar por IDs autorizados en la migración; no inferir persona jurídica desde un texto de empresa. |
| Compra/documentos | Pendiente del contrato principal | No crear categorías ficticias ni interpretar `sold` como adquisición de IMC. |

La lista completa de campos, las reglas de exportación y la migración 0016 de la
entrega anterior están en [el informe de integración](main-integration-2026-09-23.md).
Esta entrega no añade otra base maestra ni duplica esos modelos.

## 6. Cambios realizados ahora en el módulo

### 6.1 Catálogo y búsqueda

- Se leen y aplican `year_min` y `year_max`.
- En modo exacto se consulta el año conocido de la unidad.
- En modo aproximado se comparan intervalos: un registro 2017–2019 coincide con
  una búsqueda 2019–2020; no se convierte en una máquina fabricada en 2019.
- Las URLs anteriores con `year=2018` siguen siendo válidas.
- Rangos invertidos, negativos, años decimales, valores no numéricos y moneda
  inválida producen mensajes visibles en lugar de ignorarse silenciosamente.
- Los rangos numéricos respetan los límites de los campos estructurados; un
  exponente desmesurado se rechaza antes de llegar a la base de datos.
- Filtrar por importe exige moneda; ordenar por precio sin moneda avisa y
  conserva el orden de recientes.
- Por defecto se muestran disponibles. Reservadas, vendidas y todas se eligen
  expresamente; las tarjetas indican los estados distintos de disponible.
- El año exacto existente se muestra en la tarjeta. No se presenta un año vacío.

### 6.2 Lectura privada para un frontal integrado

`GET /api/maquinarias/{uuid}/` entrega el documento privado actual con un contrato
versionado. Incluye identidad local, título, revisión, estado, disponibilidad,
categoría, datos, procedencia, versión aprobada y enlaces autorizados a archivos.

Este endpoint permite que un formulario de IMC recupere la ficha y la revisión
necesaria para guardar cambios con los POST existentes. No renderiza una plantilla
ni dispara otro análisis. No incluye credenciales, nombres internos del storage o
URLs firmadas del proveedor de almacenamiento.

La consulta requiere sesión del módulo, propiedad o permisos administrativos y
MFA según la configuración vigente. Responde con errores JSON y marca las
respuestas privadas para impedir su almacenamiento en cachés compartidas.
No acepta una identidad enviada por parámetro como sustituto de autenticación.

**Esto no es SSO ni una API pública anónima.** La autenticación compartida deberá
ser instalada cuando se conozca cómo valida identidades la aplicación principal.

### 6.3 Elementos existentes que se conservan

Se reutilizan el análisis por fotografías, lectura de placa opcional, serie
escrita, investigación, estimaciones, edición, versiones, PDF, cola y revisión.
No se cambian modelos ni presupuestos de IA. No se crea una llamada de pago al
consultar una ficha. El enlace compartible y la entrega a IMC siguen requiriendo
la aprobación existente; no se equipara una exportación a una publicación real.

## 7. Plan concreto para incorporar el sistema a IMC

### Etapa A — motor y contrato: disponible en el módulo

1. Recibir borrador/fotografías mediante las rutas autorizadas existentes.
2. Procesar el trabajo en el worker, consultar su estado y aplicar el resultado.
3. Recuperar el documento privado con el GET añadido y editar con revisión.
4. Previsualizar/descargar y enviar a revisión.
5. Exportar la versión aprobada con manifiesto y entrega idempotente.

### Etapa B — integración del frontal y autenticación

1. Confirmar sesión y roles actuales de IMC con su mantenedor.
2. Definir una relación estable usuario principal ↔ usuario técnico del módulo,
   incluyendo empresa/contacto cuando el principal los distinga.
3. Elegir entre adaptador servidor a servidor del principal o rutas de servicio
   bajo el mismo origen. Resolver rutas, cookies y CSRF en un entorno de prueba.
4. Construir el formulario con los componentes de IMC, usando el contrato privado
   y las mismas reglas de revisión/guardado del módulo.
5. Retirar el segundo registro sólo cuando la identidad externa quede validada.

No se habilitará CORS abierto ni se enviará la clave de IA al navegador para hacer
esta integración. Los paths de ejemplo son del módulo actual: su montaje bajo un
prefijo distinto requiere configurar rutas y probar enlaces, archivos y callbacks.

### Etapa C — catálogo y recepción maestra

1. Obtener una muestra autorizada de tipo/marca/modelo con IDs reales y padres.
2. Resolver coincidencias con el comprobador existente; mantener incidencias.
3. Dar de alta faltantes mediante la lógica del principal, nunca por SQL adivinado.
4. Crear/actualizar únicamente una versión aprobada y sus fotos autorizadas.
5. El receptor conserva correlación por UUID y clave de entrega, y devuelve ID,
   referencia comercial, estado y huella de contenido.
6. Si la respuesta se pierde, consultar por la misma clave; no crear otro anuncio.

### Etapa D — procesos comerciales

Definir quién mantiene precio, ubicación y disponibilidad. Conectar fletes,
apartados, compras y documentos usando sus expedientes reales. El registro de un
lead debe incluir la máquina y versión consultadas. Una valoración de IA nunca
autoriza una cotización de traslado ni sustituye el expediente de adquisición.

### Etapa E — cambio de tráfico y verificación

Desplegar primero a una copia, probar usuarios/roles, carga móvil, fotos, PDF,
errores/reintentos y una publicación autorizada de prueba. Mantener reversión al
flujo anterior, mapear URLs canónicas y conservar los enlaces históricos.

## 8. Criterios de aceptación de la migración futura

| Prueba | Resultado exigido |
|---|---|
| Usuario de IMC abre publicación | Recupera su identidad sin segunda cuenta y sin acceso a fichas ajenas. |
| Sube foto general sin placa | Obtiene una ficha parcial editable; no se bloquea por serie ausente. |
| Añade placa después | Completa campos con evidencia conservando correcciones humanas. |
| No hay evidencia de precio/año | Conserva el resto; no fabrica una cifra ni un año exacto. |
| Modelo ausente/ambiguo | Señala la incidencia; no asigna un modelo de nombre parecido. |
| Guardado con revisión antigua | Rechaza conflicto y permite recuperar cambios. |
| Foto privada o revocada | No se incluye en publicación, exportación ni metadatos públicos. |
| Reintento tras timeout | Devuelve la misma operación/registro, sin segunda ficha. |
| Ficha vendida/retirada | No aparece como disponible; aplica la política comercial acordada. |
| Cambio de plantilla de IMC | No altera análisis, autorización o formato de datos. |
| Expediente de compra | Sólo usuarios con permiso acceden a documentos reales. |
| Publicación final | ID, URL, campos y fotos coinciden en ambos sistemas y existe acuse. |

## 9. Validación de esta entrega

| Comprobación | Resultado |
|---|---|
| Batería completa de Python | 1.002 pruebas y 1.305 subpruebas aprobadas; una omitida porque `ffmpeg`/`ffprobe` no estaban disponibles en el PATH de esa ejecución. |
| Última comprobación tras proteger rangos extremos y completar HTTP 405 | 21 pruebas de catálogo/API y 4 subpruebas aprobadas. Incluye exponentes enormes, autorización, MFA y aislamiento de fichas. |
| Pruebas de interfaz `npm run test:ui` | Aprobadas: catálogo, selector de categoría, inicio, perfil de excavadora, captura rápida, contraseña y notificaciones. |
| Validación Django y esquema | `manage.py check` sin incidencias y `makemigrations --check --dry-run`: sin cambios. |
| Calidad del diff | `git diff --check` sin errores de formato. |
| Navegación local con datos sintéticos | Por defecto una disponible; al elegir todas aparecen tres con reservada/vendida identificadas; rango 2018–2018 devuelve sólo la máquina de 2018. |
| Precio sin moneda | Aviso visible y cero resultados; no mezcla importes de monedas distintas. |
| Móvil del catálogo | A 390 px de viewport: ancho de contenido y desplazamiento de 375 px, sin desbordamiento horizontal. |
| Semántica del catálogo | Un único elemento principal; sección del catálogo vinculada a su encabezado. |

Las comprobaciones locales usan una base SQLite aislada, datos sintéticos y
proveedores simulados. No se crean anuncios ni se envían mensajes comerciales a
la web principal. No se consume saldo de IA para estas pruebas. La precisión de
identificación, año y valoración con nuevas fotos requiere su propia evaluación
con ejemplos reales; no se deduce de los tests de software.

La consulta privada se valida por pruebas HTTP de Django; el navegador bloqueó
la navegación directa a su URL local y no se eludió ese bloqueo. La verificación
de la versión desplegada y de salud en SeeNode se comunica al cerrar la entrega.

No se requiere una migración de esquema para los cambios de esta entrega. Antes
de publicar se conserva el código base `83ccb63` en un bundle local verificado,
en `backups/audit-adaptation-2026-09-23/code-before.bundle`, fuera del repositorio.
La reversión consiste en desplegar esa versión; no requiere borrar datos.

## 10. Prioridades después de esta entrega

1. **Prueba funcional con el equipo de IMC:** validar el conjunto mínimo de campos
   por categoría y qué datos comerciales requieren confirmación humana.
2. **Contrato de identidad y catálogo:** obtener IDs/roles reales cuando se vaya
   a conectar el principal. No copiar su catálogo público como base maestra.
3. **Piloto controlado de recepción:** una categoría, catálogo autorizado y
   fichas de prueba antes de incorporar el resto.
4. **Medición de calidad de IA:** conjunto de fotos reales consentidas, tasa de
   identificación correcta, campos útiles recuperados y coste por ficha. Las
   pruebas de software no demuestran precisión de IA ni una tasación real.
5. **Seguimiento operativo:** edad del anuncio, última confirmación de
   disponibilidad, errores de entrega y tiempo de respuesta del equipo.

La conclusión técnica es que el módulo debe entregar datos fiables y procesos
reutilizables. El principal conserva su identidad, su catálogo y su operación;
la integración se completa por contratos comprobados, sin convertir las
limitaciones observadas en nuevas dependencias del motor.
