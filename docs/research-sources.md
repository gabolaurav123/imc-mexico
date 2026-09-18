# Fuentes públicas para investigación de maquinaria

Verificación documental: **16 de septiembre de 2026**. El catálogo de `portal/research_sources.py` contiene **seis perfiles generales de fabricantes, un perfil de Cat Lift Trucks y catálogos técnicos por familia**. Son puntos de partida reales para búsquedas; no conexiones a registros privados, APIs contratadas ni garantía de que exista información de una máquina concreta.

## Fabricantes verificados

| Marca / aliases | Dominio para búsqueda | Página comprobada | Alcance y acceso observado |
| --- | --- | --- | --- |
| Caterpillar / Cat | `cat.com` | [Parts & Service Manuals](https://www.cat.com/en_US/support/maintenance/service-manuals.html) | Página pública legible con vías para manuales, SIS2GO y distribuidores. Parte de la documentación requiere compra, aplicación o distribuidor; no se descargaron manuales restringidos. |
| Komatsu | `komatsu.com` | [Excavators](https://www.komatsu.com/en-us/products/equipment/excavators) | Catálogo público legible y fichas técnicas por modelo. Es una entrada regional; no acredita año de una unidad por serie. |
| Volvo Construction Equipment / Volvo CE / Volvo | `volvoce.com` | [Product archive](https://www.volvoce.com/global/en/products-and-services/past-products/) | Archivo público de modelos anteriores con especificaciones, manuales y folletos. Los intervalos de producción de un modelo no equivalen al año de fabricación de una unidad. El alias Volvo se refiere aquí a maquinaria de construcción, no a camiones o automóviles. |
| John Deere / Deere | `deere.com` | [Manuals & Training](https://www.deere.com/en-us/parts-owner-support/manuals-training), [Technical Information Store](https://rmi.techpubs.deere.com/Products/ProductSearch.aspx) | La antigua página redirigió al portal moderno, cuya extracción de texto fue limitada. La tienda de publicaciones muestra búsqueda y compra; no se verificó acceso completo a documentos de pago o suscripción. |
| JLG / JLG Industries | `jlg.com` | [Troubleshooting Tools](https://www.jlg.com/en/support-and-services/troubleshooting) | Página pública legible con enlace a publicaciones técnicas y Online Express, que solicita una cuenta gratuita. La ruta `/en/resources` falló en la herramienta de lectura y no se usa como entrada principal. |
| Bobcat / Bobcat Company | `bobcat.com` | [Manuals](https://www.bobcat.com/na/en/parts-service/service/manuals) | Página pública legible con documentación de operación, mantenimiento y servicio; enlaza manuales ofrecidos en tienda. No implica acceso gratuito a todos ellos. |

Se incluyeron Caterpillar, Komatsu, JLG y Bobcat porque también figuran en el catálogo orientativo local; Volvo y Deere amplían las fuentes solicitadas. No se atribuyen automáticamente marcas adquiridas, marcas parecidas, distribuidores ni dominios regionales no comprobados a estos perfiles.

## Catálogos externos, separados de fabricantes

| Fuente | Dominio / entrada comprobada | Uso y límite |
| --- | --- | --- |
| LECTURA Specs | [`lectura-specs.com`](https://www.lectura-specs.com/) | Catálogo público de especificaciones por modelo. Ofrece servicios comerciales, pero no se contrató ni integró su API. La disponibilidad pública de páginas no concede una licencia de extracción masiva. |
| RitchieSpecs | [`ritchiespecs.com`](https://www.ritchiespecs.com/) | Base pública de modelos actuales e históricos. Advierte que las especificaciones describen unidades base y pueden variar según opciones. Algunas partes de la página se renderizan dinámicamente. |

Ambos conservan `source_kind='technical_catalog'`, incluso cuando una página contiene años o una URL menciona series. Sirven como referencias de modelo pendientes de comprobación; **no son autoridades de año por número de serie**.

### Periodos del modelo en metadatos de LECTURA

Verificación adicional: **17 de septiembre de 2026**. Los registros públicos de [Caterpillar 14H de 1996–2002](https://www.lectura-specs.com/en/model/construction-machinery/graders-caterpillar/14h-13775) y [Caterpillar 14H de 2003–2007](https://www.lectura-specs.com/en/model/construction-machinery/graders-caterpillar/14h-1005586), leídos mediante la herramienta de búsqueda, muestran la etiqueta `Years of manufacture` y los mismos intervalos de su título estándar `Specifications & Technical Data`. Corresponden a registros distintos del modelo y contienen configuraciones diferentes.

Un adaptador específico reconoce únicamente ese formato de metadatos en rutas de modelo inglesas de `www.lectura-specs.com`, con marca y modelo exactos. Usa los títulos y URLs realmente recuperados por la herramienta; no convierte títulos reconstruidos por la IA, fechas genéricas, anuncios ni copyright en años de fabricación. No requiere descargar la página ni eludir el bloqueo HTTP 403 del lector directo.

El resultado es una **referencia temporal orientativa del modelo**, nunca el año confirmado de la unidad. Si los registros del mismo modelo presentan periodos contiguos o superpuestos, puede mostrar su cobertura amplia, conservando cada intervalo y enlace en la procedencia firmada. No rellena huecos ni mezcla motores, medidas u otras especificaciones de generaciones diferentes. Los intervalos, su regla de combinación y sus fuentes se vuelven a validar antes de aplicar el trío de campos aproximados. El formulario, la ficha virtual y el PDF mantienen la indicación de que el año de esta unidad está por confirmar.

## Montacargas Cat: documentación de manutención

Cuando la categoría confirmada es `Montacargas`, `lookup_brand('CAT', 'Montacargas')` dirige la investigación a **Cat Lift Trucks**, mediante [Logisnext y sus marcas](https://www.logisnextamericas.com/en/logisnext/our-brands), [servicio de Logisnext](https://www.logisnextamericas.com/en/logisnext/support/service) y [la historia de Cat Lift Trucks](https://www.catlifttruck.com/catr-lift-trucks-story-success). Las búsquedas pueden consultar documentación histórica MCFA; el perfil no asigna automáticamente fabricante, país ni configuración a una unidad. Una sede en Houston no demuestra origen estadounidense.

La etapa de catálogos prioriza **MachineTools y LECTURA** para esta familia. La [página del modelo 2EC25 en MachineTools](https://www.machinetools.com/en/models/caterpillar-2ec25) muestra información limitada y un peso sin unidad visible en la lectura comprobada: no se completa la unidad por suposición. MachineTools devolvió HTTP 403 al cliente directo y no se habilita evasión ni lector directo para ese sitio.

El [catálogo de baterías de East Penn para Caterpillar](https://www.eastpennmanufacturing.com/wp-content/uploads/Caterpillar.pdf) contiene configuraciones alternativas de voltaje y pesos mínimos de batería. Una alternativa no prueba el voltaje instalado y su peso no equivale al peso del montacargas.

### Fichas históricas que identifican la serie

El lector de [Smith Machinery](https://www.smithmachinery.com/) admite únicamente rutas públicas `/listing/<slug>/` devueltas realmente por el buscador. Exige marca y modelo en los atributos de la ficha, modelo y **serie idéntica completa en el encabezado visible**, y tipo montacargas. No utiliza la URL, nombres de imágenes ni el modelo para inventar la identidad.

Extrae filas literales de capacidad, altura de elevación, voltaje, peso con/sin batería, peso mínimo/máximo de batería, capacidad en amperio-horas y longitud de horquillas cuando estén presentes con sus etiquetas/unidades. Conserva calificadores y la nota de verificación del vendedor. Una ficha de otra serie o una consulta sin serie no se convierte en referencia genérica del modelo. Nunca importa condición, precio, disponibilidad, año del anuncio, ubicación del vendedor o país supuesto.

Estos datos conservan `scope='exact_serial'`, `source='web'` y `review='needs_review'`: documentan lo que una fuente decía de esa unidad, sin certificar su configuración actual. Pasan por la misma validación y firma. URLs y títulos que contienen la serie conservan las restricciones de privacidad de la ficha pública. Las pruebas usan identificadores sintéticos; no se incluyen series de anunciantes en el repositorio.

APIs compatibles: `lookup_brand(name, category=None)`, `catalogs_for_category(category=None)` y `source_kind(url, brand=None, category=None)`. Sin categoría se mantiene el perfil de construcción anterior. El lector Smith comparte límites de dos documentos, tiempos, tamaños, URLs recuperadas y DNS público con H-CPC/Ritchie; no añade llamadas de IA ni cambia cuotas. Su contenido histórico no autoriza años de fabricación por serie.

## HESSEN 016-9020 y 016-9030

Se buscaron públicamente las combinaciones exactas `"HESSEN" "016-9020"` y `"HESSEN" "016-9030"`, variantes con «compactadora» y búsquedas de manuales. No se encontró un documento técnico o una página de fabricante que vincule de forma verificable esos modelos en esta revisión. No se utilizó ningún número de serie privado.

Se encontró el [catálogo brasileño Hessen / ADA](https://hessen.com.br/produtos/hessen/), con herramientas y cortadores de piso. Las búsquedas de los dos modelos dentro de ese dominio no devolvieron coincidencias verificables. **La coincidencia de marca no demuestra que sea el fabricante de esas compactadoras**; por eso no se incorpora a `MANUFACTURERS` y `lookup_brand('HESSEN')` devuelve `None`. Otros resultados usaban Hessen como ubicación alemana o contenían números de catálogo ajenos: se descartaron.

La ausencia de resultados en esta búsqueda no demuestra que los manuales no existan. Una página del fabricante, manual legible o documento del importador que identifique de forma explícita el modelo permitiría evaluar una fuente nueva; no se completa el catálogo con dominios supuestos.

## Contrato para integración

```python
from portal.research_sources import lookup_brand, TECHNICAL_CATALOGS, source_kind

profile = lookup_brand('CAT')
manufacturer_domains = profile.manufacturer_domains if profile else ()
documentation_urls = profile.documentation_urls if profile else ()
catalog_domains = tuple(domain for item in TECHNICAL_CATALOGS for domain in item.domains)
kind = source_kind('https://www.cat.com/en_US/support/maintenance/service-manuals.html', 'CAT')
```

- `lookup_brand(name, category=None) -> BrandProfile | None`: coincidencia de alias completo normalizado; no coincidencias parciales de nombres o modelos.
- `MANUFACTURERS`: tupla de dataclasses congeladas con `brand`, `aliases`, `manufacturer_domains`, `documentation_urls`, `source_kind`, `verified_on` y `access_note`.
- `TECHNICAL_CATALOGS`: tupla de dataclasses congeladas con `name`, `domains`, `documentation_urls`, `source_kind`, `verified_on` y `access_note`.
- `source_kind(url, brand=None, category=None)`: devuelve `manufacturer`, `technical_catalog`, `public_documentation` o `None`. Con marca/categoría reconoce los dominios de ese perfil; sin marca reconoce los perfiles registrados. Compara límites de dominio, evitando que `cat.com.otro-dominio.example` herede autoridad.
- `public_documentation` significa **origen público no clasificado**: no acredita que la URL contenga un manual, que se haya descargado, que sea oficial ni que sus afirmaciones sean correctas. URL inválida, credenciales incrustadas, IP literal o nombre local devuelve `None`.
- El módulo no hace peticiones. Su comprobación de URL no es un cortafuegos de red ni un validador SSRF; cualquier futura descarga debe aplicar su política de red y volver a clasificar el destino final de una redirección.

Los dominios alimentan las etapas de búsqueda dirigidas, con una estrategia compatible con el modelo:

- Cuando el modelo admite filtros de dominios de `web_search`, la etapa usa `filters.allowed_domains`.
- Con la familia `gpt-4.1`, la consulta incorpora operadores `site:`; esta alternativa responde al rechazo del parámetro observado en la prueba real con `gpt-4.1-mini`. El servidor comprueba después el dominio de cada fuente y excluye fuentes y fragmentos fuera de la lista de esa etapa. Se acepta el dominio completo o un subdominio delimitado; `cat.com.otro-dominio.example` no pertenece a `cat.com`.
- `site:` orienta el buscador; **la comprobación local impide aceptar evidencia fuera de los dominios previstos**. No se presenta esta alternativa como un filtro nativo de la API. Las etapas sin lista de dominios mantienen la búsqueda pública y sus validadores de evidencia.

La elección de estrategia conserva el modelo configurado, las etapas y las cuotas; no habilita acceso privado. Cada dato aún requiere evidencia vinculada a su URL, identidad de marca/modelo coherente, ámbito explícito y validación de procedencia. **Ningún perfil autoriza por sí solo un año por serie ni confirma la configuración de la unidad.** Se mantienen los validadores existentes y la revisión humana. No se añaden valores técnicos, existencias, precios ni datos personales al catálogo.

## Lectura directa de documentos públicos

Además de la búsqueda por etapas, el servidor puede leer hasta **dos páginas de especificaciones** que el buscador haya devuelto realmente. Los lectores cubren tablas públicas de **Caterpillar H-CPC**, **RitchieSpecs** y las fichas exactas de **Smith Machinery** descritas arriba. No se construyen enlaces de modelos ni se envían datos de contacto. Esta lectura no consume otra llamada de IA.

El lector comprueba el encabezado real del documento y extrae filas con etiquetas y unidades literales. Las páginas que agrupan modelos distintos, las variantes no coincidentes, los motores opcionales y los valores incompatibles no se convierten automáticamente en especificaciones de una unidad. Las tablas aceptadas pasan por la misma validación de procedencia y conflictos que la búsqueda y pueden conservarse si falla el resumen de IA. Los catálogos conservan ámbito de modelo; una fuente que vincula literalmente la serie completa, marca y modelo puede aportar datos de ámbito `exact_serial`. Ambos permanecen pendientes de revisión de la máquina concreta.

Las descargas permiten únicamente HTTPS, rutas de catálogo registradas, direcciones de red públicas y redirecciones revalidadas. Tienen límites de tiempo, tamaño y cantidad. Se respetan errores de acceso: **LECTURA respondió 403 a la lectura directa de prueba**, por lo que no tiene lector directo habilitado. Sus páginas públicas pueden seguir apareciendo como fuentes del buscador. No se eluden inicios de sesión ni se contratan APIs.

La disponibilidad y el formato de una página externa pueden cambiar. El fallo de un lector se registra y deja continuar las otras etapas. El país de fabricación todavía requiere una declaración explícita de origen; la ubicación actual y el historial privado de una unidad no se deducen de un catálogo.

## Pruebas locales de las fuentes

`portal/tests/test_research_sources.py` verifica aliases completos, separación de fabricantes y catálogos, marca desconocida, inmutabilidad, origen por marca, falsificación de dominios, URLs no públicas y reclasificación de redirecciones. Son pruebas sin red y sin acceso a producción; no sustituyen una nueva comprobación de disponibilidad del sitio en cada investigación.
