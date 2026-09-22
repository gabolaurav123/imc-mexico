# Biblioteca inicial de compactadores

`catalogo_tecnico_2026-09-22.json` incorpora siete referencias de fabricante:
cuatro placas vibratorias Wacker Neuson para Estados Unidos, el rodillo BOMAG
BW 120 AD-5 de la ficha APAC, el HAMM HD 12 P VV H312 de la ficha DE y la
configuración Honda GX200 del Dynapac LG200. Cada ficha especifica literalmente
mercado, variante y configuración cuando el fabricante la publica. El documento
histórico de Dynapac no declara mercado ni años de producción: ambos se dejan
vacíos; no se interpreta como una ficha mundial.

Las cifras son especificaciones de modelo y no identifican ni confirman una
unidad anunciada. No se ha documentado un periodo de producción oficial para
estas siete referencias y por eso no se incluyen años estimados. La variante
de emisiones del BOMAG y la configuración de motor Dynapac sólo pueden usarse
si se confirman literalmente para la unidad.

HESSEN 016-9020 y 016-9030 siguen fuera de este catálogo: la investigación de
fuentes documentada en `docs/research-sources.md` no halló una fuente primaria
que ligue esos identificadores con una compactadora. La marca visible o una
coincidencia de nombre no basta para completar modelo, país, año o especificación.

Para cargar las referencias: `python manage.py import_technical_knowledge --path knowledge/compactadores`.
El proceso local las deja pendientes hasta la revisión y aprobación administrativa.
