# Fuentes del índice de construcción

`knowledge/new_ritchiespecs_construction_identities_2026-10-06.json` es un
índice de identidades de modelos de construcción. No es un inventario y no
declara que una unidad concreta tenga las especificaciones de una ficha.

## RitchieSpecs

La fuente de descubrimiento es el sitemap público de RitchieSpecs:
`https://www.ritchiespecs.com/sitemap.xml`. `robots.txt` publicado por el sitio
lo declara como sitemap y no prohíbe el acceso de agentes. La herramienta
`tools/import_ritchiespecs_construction.py` descarga una vez ese documento,
calcula su SHA-256 y conserva, para cada fila, la URL exacta de modelo.

Solo se incluyen familias que el sitio publica bajo `/industry/construction/`,
`/industry/asphalt-aggregate-concrete/` y
`/industry/lifting-material-handling/`; se excluyen agricultura y silvicultura.
Cada URL debe separar sin ambigüedad un slug de
fabricante que también aparece en `/manufacturer/`, un slug de modelo no vacío
y una de esas familias. La herramienta descarta cualquier URL que no cumpla
esas condiciones y quita URL repetidas.

Los slugs literales de fabricante y modelo permanecen en `brand_slug` y
`model_slug`. `brand` se presenta a partir del slug de fabricante y `model` se
presenta en mayúsculas, sin eliminar signos de puntuación; no se añaden aliases
ni variantes. `source_type` conserva la familia RitchieSpecs y `category_slug` hace explícito
el mapeo a la taxonomía IMC para el selector tipo → marca → modelo.

Al 2026-10-06, el sitemap tenía 14,821 URL de modelo. El filtro de los tres
sectores incluidos encontró 10,657 ocurrencias de URL (10,638 URL distintas) y
produjo 10,360 identidades únicas después de descartar URL repetidas o
equivalentes, 119 filas cuyo mismo fabricante+modelo cae en
categorías IMC distintas y la fila de marca no verificable `aaa`. En esa consulta el endpoint público de detalle
de RitchieSpecs respondió un error de índice y las URL de detalle devolvieron
la página de ausencia de contenido; por eso todas las filas llevan `specs: {}` y
`specification_status: not_retrieved`. No se deducen peso, potencia, capacidad,
año ni configuración a partir de un slug.

Para regenerar el artefacto:

```powershell
python tools/import_ritchiespecs_construction.py --output knowledge/new_ritchiespecs_construction_identities_2026-10-06.json --retrieved-at 2026-10-06
```

Una futura ampliación de especificaciones debe partir de páginas de detalle o
documentación OEM que vuelva a estar disponible, guardar el valor y su URL de
origen por modelo y pasar revisión. No debe rellenar medidas comunes por
familia.

## Komatsu actual, Estados Unidos

`knowledge/new_komatsu_current_specs_2026-10-06.json` contiene 120 referencias
de fabricante. La navegación pública de `https://www.komatsu.com/en-us/products`
identificó 129 páginas de equipos de excavación, tractores, cargadores, camiones
y motoniveladoras. Se leyeron de forma acotada y solo se guardó una ficha cuando
la propia página publicó al menos una medida métrica con etiqueta: potencia,
peso operativo, capacidad, velocidad de desplazamiento o profundidad de
excavación. Las siete páginas sin una de esas medidas no se incluyen. Dos URLs
que ya estaban representadas por la fuente Komatsu aprobada se excluyeron tras
normalizar mayúsculas/minúsculas, para que una misma página no compita consigo
misma.

Cada valor guarda una frase de evidencia que conserva la etiqueta visible de
Komatsu y la URL exacta de la página. Las configuraciones, accesorios y valores
no etiquetados no se infieren. La fuente es el fabricante; el alcance de mercado
es la configuración US de producto vigente al recuperarla.

Para regenerar sin duplicar una URL ya aprobada:

```powershell
python tools/import_komatsu_current_specs.py --output knowledge/new_komatsu_current_specs_2026-10-06.json --retrieved-at 2026-10-06 --exclude-source-file knowledge/excavadoras/catalogo_tecnico_us_2026-09-18.json
```
