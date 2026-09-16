# Fuentes públicas para investigación de maquinaria

Verificación documental: **16 de septiembre de 2026**. El catálogo de `portal/research_sources.py` contiene **seis fabricantes y dos catálogos técnicos externos**. Son puntos de partida reales para búsquedas; no conexiones a registros privados, APIs contratadas ni garantía de que exista información de una máquina concreta.

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

- `lookup_brand(name) -> BrandProfile | None`: coincidencia de alias completo normalizado; no coincidencias parciales de nombres o modelos.
- `MANUFACTURERS`: tupla de dataclasses congeladas con `brand`, `aliases`, `manufacturer_domains`, `documentation_urls`, `source_kind`, `verified_on` y `access_note`.
- `TECHNICAL_CATALOGS`: tupla de dataclasses congeladas con `name`, `domains`, `documentation_urls`, `source_kind`, `verified_on` y `access_note`.
- `source_kind(url, brand=None)`: devuelve `manufacturer`, `technical_catalog`, `public_documentation` o `None`. Con marca sólo reconoce como fabricante los dominios de esa marca; sin marca reconoce cualquiera de los seis perfiles. Compara límites de dominio, evitando que `cat.com.otro-dominio.example` herede autoridad.
- `public_documentation` significa **origen público no clasificado**: no acredita que la URL contenga un manual, que se haya descargado, que sea oficial ni que sus afirmaciones sean correctas. URL inválida, credenciales incrustadas, IP literal o nombre local devuelve `None`.
- El módulo no hace peticiones. Su comprobación de URL no es un cortafuegos de red ni un validador SSRF; cualquier futura descarga debe aplicar su política de red y volver a clasificar el destino final de una redirección.

Los dominios alimentan las etapas de búsqueda dirigidas, con una estrategia compatible con el modelo:

- Cuando el modelo admite filtros de dominios de `web_search`, la etapa usa `filters.allowed_domains`.
- Con la familia `gpt-4.1`, la consulta incorpora operadores `site:`; esta alternativa responde al rechazo del parámetro observado en la prueba real con `gpt-4.1-mini`. El servidor comprueba después el dominio de cada fuente y excluye fuentes y fragmentos fuera de la lista de esa etapa. Se acepta el dominio completo o un subdominio delimitado; `cat.com.otro-dominio.example` no pertenece a `cat.com`.
- `site:` orienta el buscador; **la comprobación local impide aceptar evidencia fuera de los dominios previstos**. No se presenta esta alternativa como un filtro nativo de la API. Las etapas sin lista de dominios mantienen la búsqueda pública y sus validadores de evidencia.

La elección de estrategia conserva el modelo configurado, las etapas y las cuotas; no habilita acceso privado. Cada dato aún requiere evidencia vinculada a su URL, identidad de marca/modelo coherente, ámbito explícito y validación de procedencia. **Ningún perfil autoriza por sí solo un año por serie ni confirma la configuración de la unidad.** Se mantienen los validadores existentes y la revisión humana. No se añaden valores técnicos, existencias, precios ni datos personales al catálogo.

## Pruebas locales

`portal/tests/test_research_sources.py` verifica aliases completos, separación de fabricantes y catálogos, marca desconocida, inmutabilidad, origen por marca, falsificación de dominios, URLs no públicas y reclasificación de redirecciones. Son pruebas sin red y sin acceso a producción; no sustituyen una nueva comprobación de disponibilidad del sitio en cada investigación.
