# Auditoría técnica pública del sitio principal IMC México

**Fecha:** 23 de septiembre de 2026  
**Objetivo:** `https://www.imcmexico.com.mx/` como referencia pública para la evolución del módulo Django local. No cubre el módulo seenode ni supone que éste comparta implementación, datos o permisos con el sitio principal.

## Alcance, método y límites

La revisión fue pasiva y de solo lectura: `GET`/`HEAD` HTTPS de la portada, el catálogo de plantas de concreto, dos fichas públicas (Cementech C60 y Bohringer B120), `robots.txt` y recursos que esas páginas enlazan. Se leyó HTML, JavaScript y cabeceras; no se descargaron imágenes, no se enviaron formularios, no se inició sesión, no se visitaron zonas administrativas ni se llamaron rutas de escritura. Por ello, los nombres de archivos PHP/JavaScript no son una API ni evidencia del esquema, motor de base de datos o autorización de integración.

Las cifras de latencia son una muestra puntual con `curl` desde este entorno, no una prueba de carga, una medición de usuarios reales ni un Lighthouse.

## Evidencia principal

| Área | Hecho observado | Evidencia pública |
| --- | --- | --- |
| Stack visible | Las respuestas son `Apache`, HTTP/1.1, HTML `text/html; charset=iso-8859-1`, comprimido gzip y con cookie `PHPSESSID`. | Portada, catálogo y ambas fichas: respuestas `200`; cabecera `Server: Apache`, `Content-Encoding: gzip`, `Set-Cookie: PHPSESSID`. |
| Caché HTML | Las tres vistas HTML envían `Cache-Control: no-cache, must-revalidate` y una cookie de sesión aun sin autenticación. | Mismas respuestas. |
| Robots | El archivo permite el rastreo general con `Crawl-Delay: 60`, bloquea múltiples directorios y no contiene una directiva `Sitemap:`. | [robots.txt](https://www.imcmexico.com.mx/robots.txt). Una regla de `robots` no es un control de acceso. |
| SEO de listado y fichas | Catálogo y fichas llevan título, descripción y `meta robots=index`; las fichas incluyen Open Graph (`title`, `url`, `description`, imagen JPEG 300 × 300). No se halló `rel=canonical`, `meta viewport` ni JSON-LD en la muestra. | [catálogo](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto), [Cementech C60](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto-cementech-c60-1668191915090848), [Bohringer B120](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto-bohringer-b120-1709396833023629). |
| Datos estructurados | Las fichas usan microdatos `http://schema.org/Product`, `Brand`, `Offer` y `price`; no se observó `priceCurrency` ni JSON-LD en las dos fichas. | Fichas anteriores; Cementech declara el precio visual `$ 285,000.00 USD`. |
| Canonicalización histórica | La ruta pública heredada `catalogo-maquinaria-4.php?Parametros=…` devuelve `301` a la URL legible de Cementech. | [ruta heredada](https://www.imcmexico.com.mx/catalogo-maquinaria-4.php?Parametros=plantas-de-concreto-cementech-c60-1668191915090848). |
| Carga de imágenes | En la muestra no existe `loading`, `srcset` ni `preload`. El HTML transferido de la portada contiene 124 etiquetas `img`, el catálogo 86 y cada ficha 46; el DOM de navegador de la portada reportó 129 imágenes y 3,588 enlaces. | Conteo estático del HTML y observación de DOM; la diferencia demuestra que no deben confundirse ambos conteos. |
| Variantes de foto | La ficha Cementech enlaza una portada en `photos` (32,521 B) y las vistas/galería en `photosb` (198,773 B); ambas son `image/jpeg`, aceptan rangos y se cachean un año. | [portada](https://www.imcmexico.com.mx/photos/1668191915090848_1668192477-01.jpg), [variante de galería](https://www.imcmexico.com.mx/photosb/1668191915090848_1668192477-01.jpg). Solo se consultaron cabeceras. |
| Dependencias y maquetación | Se carga `jquery-1.6.js` (232,651 B; `Last-Modified: 2013-12-06`), CSS de escritorio de 240,236 B (`Last-Modified: 2019-03-31`), manejadores inline y tablas de ancho fijo. Los CSS responsivos se seleccionan con `max-device-width`/`min-device-width`; falta `meta viewport`. | Recursos enlazados desde las páginas; [jQuery](https://www.imcmexico.com.mx/scripts/jquery/jquery-1.6.js), [CSS PC](https://www.imcmexico.com.mx/css/estilos_pc.css?v=a81df4). |
| Codificación | El HTML declara `windows-1252` mediante `http-equiv`, mientras la cabecera HTTP declara `iso-8859-1`. En navegador se observó el texto visible `8 dÃas`. | [catálogo](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto) y observación de navegador. La coexistencia de esos dos valores no prueba por sí sola la causa, pero el texto visible es un defecto de presentación verificable. |
| Vista móvil | En una observación de navegador a viewport de 390 px, el documento tuvo ancho cliente 375 px y ancho de desplazamiento 992 px. | Portada; evidencia de desbordamiento horizontal en esa condición concreta. |

## Medición puntual de entrega

Las solicitudes HTTPS no siguieron redirecciones y usaron contenido comprimido. `time_starttransfer` incluye red y tiempo de respuesta del origen desde el punto de observación; no permite atribuir la demora a PHP, base de datos o red sin telemetría del servidor.

| URL | Tamaño transferido reportado | Conexión TLS | TTFB | Total |
| --- | ---: | ---: | ---: | ---: |
| [Portada](https://www.imcmexico.com.mx/) | 76,630 B | 0.301 s | 5.034 s | 7.923 s |
| [Catálogo](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto) | 25,158 B | 0.361 s | 8.218 s | 8.356 s |
| [Ficha Cementech](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto-cementech-c60-1668191915090848) | 24,200 B | 0.331 s | 5.886 s | 6.028 s |

La TTFB de 5–8 s en esta muestra merece instrumentación antes de cualquier conclusión causal. La cookie en páginas anónimas y `no-cache` son una explicación posible de menor capacidad de caché, no una prueba de la causa de la latencia.

## Defectos y riesgos verificables

### P1 — búsqueda rápida sin navegación en una prueba; causa sin confirmar

**Hecho.** En la portada, al elegir `EXCAVADORAS HIDRAULICAS` → `CATERPILLAR` → `320D`, una interacción de navegador observada dejó la URL en `/` sin resultados, mensaje o diálogo. No se repitió la acción ni se envió el `POST` del formulario.

El JavaScript público de la misma portada, `Valida_Busqueda_Simple('MX')`, arma en cliente `/catalogo-de-excavadoras-hidraulicas-caterpillar-320d` y asigna `location.href`. El código además usa asignación (`if (Idioma = "MX")`) en vez de comparación; con esa invocación concreta sigue tomando la rama española, por lo que no explica por sí solo el resultado observado.

**Riesgo/inferencia.** Hay que confirmar la interacción, los valores dinámicos del selector, la construcción de slug y la regla de enrutamiento o redirección. Una sola interacción sin navegación no demuestra que la ruta generada falle en HTTP ni permite atribuir la causa; se evitó solicitar esa ruta adicional. Si se reproduce, puede impedir descubrir inventario y degradar SEO.

**Acción propuesta para el módulo Django.** Mantener tipo, marca y modelo como campos separados y conservar el slug/URL externa sólo como referencia. Validar con una tabla de correspondencias importable y pruebas locales que contemplen variantes (`315 BL`/`315BL`, `229`/`229 L`) en vez de reconstruir URLs con texto.

### P1 — imagen de una tarjeta construida con una ruta inválida

**Hecho.** El HTML de la portada para la tarjeta KOMATSU PC200 L referencia `/photosb/https://imcmexico.mx/photos/1782412064971384-1.jpg`. Es una ruta relativa cuyo segmento posterior ya es una URL absoluta, por lo que no apunta al formato normal de fotos observado. No se solicitó ese recurso.

**Riesgo.** La miniatura puede fallar y consume una solicitud inútil. Es un defecto concreto de la fuente de datos o de su concatenación, no evidencia de un problema de acceso a archivos.

**Acción propuesta para el módulo Django.** Guardar URL/origen de archivo y variante de presentación por separado; validar que las URLs sean HTTPS válidas antes de renderizarlas y mostrar un estado de imagen no disponible, sin intentar adivinar o reescribir rutas remotas.

### P1 — señales SEO estructurales incompletas

**Hechos.** No se observó canónica ni `viewport` en portada, listado o fichas; la ficha declara producto/oferta pero no `priceCurrency` y no hay JSON-LD en la muestra. La canónica de la redirección heredada existe de hecho como 301, pero no sustituye `rel=canonical` en el HTML de las URLs finales.

**Riesgo.** Las URLs alternas, parámetros y rutas heredadas pueden depender más de redirecciones que de señales explícitas. Los motores pueden interpretar peor precio/moneda y el contenido de ficha.

**Acción propuesta para el módulo Django.** Generar una URL canónica propia por ficha; servir `Product`/`Offer` en JSON-LD con moneda ISO (`USD`, etc.), disponibilidad sólo cuando sea verificable y una imagen absoluta válida. No usar la referencia pública de 16 dígitos como clave interna ni deducir su significado.

### P1 — rendimiento y compatibilidad de frontend a comprobar

**Hechos.** Las TTFB puntuales son elevadas para tres páginas y las vistas HTML anónimas no son cacheables según sus cabeceras. Hay muchas imágenes sin carga diferida o variantes responsivas, jQuery 1.6, tablas/anchos fijos, handlers inline y ausencia de `viewport`. En navegador, la portada también tuvo desbordamiento horizontal a 390 px (375 px de ancho cliente frente a 992 px de desplazamiento).

**Riesgo/inferencia.** El desbordamiento documenta una incompatibilidad de maquetación en esa condición móvil. En redes móviles y equipos actuales también puede aumentar el tiempo de presentación y la fragilidad de mantenimiento; esta auditoría no establece su alcance en otros tamaños o navegadores.

**Acción propuesta para el módulo Django.** No copiar esa arquitectura: usar HTML semántico, CSS responsive con `meta viewport`, JavaScript sin dependencia de los handlers inline, miniaturas derivadas del módulo y `loading="lazy"` para contenido fuera de pantalla. Medir TTFB, LCP y errores del propio módulo antes y después de cambios.

### P2 — codificación y enlaces externos no cifrados

**Hechos.** La portada mostró `8 dÃas` en navegador y el documento contiene declaraciones de codificación distintas (`windows-1252` y `iso-8859-1`), sin atribuir una como causa de la otra. La portada contiene enlaces `http://` a `cancun.estate` e `imc.club`; además incluye un píxel `https` de Facebook. No se abrieron los destinos externos.

**Riesgo.** La codificación puede degradar títulos/descripciones; los enlaces HTTP entregan al usuario a un protocolo no cifrado si el destino no redirige.

**Acción propuesta para el módulo Django.** Emitir UTF-8 de forma coherente en cabecera y documento, normalizar textos de importación sin perder el original y permitir sólo enlaces externos HTTPS validados en contenido propio.

### P2 — cabeceras a revisar con el responsable del alojamiento

**Hecho.** En las tres respuestas HTML no estuvieron presentes `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` ni `Permissions-Policy`.

**Riesgo/inferencia.** Son capas de defensa y de control del navegador que no se observan en la muestra; su ausencia no prueba una vulnerabilidad explotable ni define la configuración del servidor completo.

**Acción propuesta.** Para el futuro despliegue del módulo, configurar estas cabeceras tras probar dependencias reales. El principal sólo puede modificarse con autorización y acceso al alojamiento.

### P2 — acceso al PDF de ficha sin control nativo de teclado

**Hecho.** En la ficha pública CAT 320D, el control de PDF coincide con el selector
`#Ficha_Grupo_Botones > div` y ejecuta `Visualiza_PDF` desde un `onclick`, en vez
de un enlace o botón nativo. Al hacer clic abrió una pestaña, pero la política de
URL del navegador bloqueó su apertura posterior; no se intentó descargar el PDF
por otra ruta ni se auditó su contenido.

**Riesgo.** Un `div` con sólo evento de ratón puede no ser utilizable mediante
teclado ni comunicar su función correctamente a tecnologías de asistencia. El
bloqueo local de la URL no demuestra que el PDF público esté roto.

**Acción propuesta para el módulo Django.** Publicar documentos mediante un
`<a href>` o `<button>` semántico, con nombre accesible, foco visible y una URL
HTTPS verificable; tratar el PDF como un artefacto independiente que requiere su
propia revisión de contenido y accesibilidad.

## Compatibilidad del catálogo para la futura migración

Las fichas públicas muestran una identidad visible de tipo, marca, modelo, referencia, año, horas, precio y galería. En Cementech: tipo `PLANTAS DE CONCRETO`, marca `CEMENTECH`, modelo `C60`, referencia `1668191915090848`, año `2020`, horas `No Disponible` y `$ 285,000.00 USD`. En Bohringer: `BOHRINGER`, `B120`, referencia `1709396833023629`, año `2023`, horas `No Disponible` y `$ 439,000.00 USD`.

Esto sólo justifica un adaptador de lectura autorizado y un modelo compatible en Django. La `Referencia` es una etiqueta pública y no demuestra que sea clave primaria, ID de usuario, secuencia enumerable o identificador apto para escritura.

La observación de navegador de [CAT 320D](https://www.imcmexico.com.mx/catalogo-de-excavadoras-hidraulicas-caterpillar-320d-1561145342951147) mostró referencia `1561145342951147`, año `2017`, `464 hrs.`, precio `$ 556,900.00 USD` y ubicación `Georgia, US`. En su galería se vieron miniaturas de 639 × 479 y 638 × 388 px renderizadas a 76 × 60 px, y una imagen principal de 340 × 250 px en la vista virtual. Es evidencia de una presentación de fotos concreta, no de límites de carga, dimensiones originales ni contrato de imágenes del principal.

Campos recomendados para el módulo: UUID local inmutable; `external_reference` opaco y opcional; URL externa canónica; tipo/marca/modelo originales más IDs de un catálogo autorizado; año/hora/precio/moneda separados; descripción; activos con MIME, bytes, hash, orden y portada. La importación debe conservar el texto original y registrar fecha/fuente, validar variantes de fotos y dejar los valores ausentes como ausentes, nunca rellenarlos con cero o inferencias.

## Prioridad de trabajo sugerida

1. Corregir y cubrir con pruebas locales la generación/resolución de búsqueda y la validación de URLs de imagen en el módulo Django, usando una muestra autorizada de catálogo.
2. Implementar el contrato local compatible: IDs locales, referencia externa opaca, taxonomía separada, moneda explícita y manifiesto de imágenes.
3. Añadir canónicas, `viewport`, JSON-LD correcto y carga de imágenes moderna al frontend Django; medir con datos propios.
4. Con acceso autorizado al principal, repetir la medición desde varias regiones, revisar caché, reescrituras y cabeceras, y confirmar un mecanismo de consulta o importación. No inferir SQL ni reutilizar sus archivos AJAX como API.
