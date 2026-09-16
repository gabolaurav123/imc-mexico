# Referencias de maquinaria del sitio principal

## Fuente y alcance

La navegación y las tarjetas públicas de [IMCMEXICO](https://www.imcmexico.com.mx/) se consultaron el **15 de septiembre de 2026**, hora de México; la captura tiene marca UTC `2026-09-16T00:09:38Z`. La lectura directa del HTML permitió verificar los enlaces que sustentan las sugerencias. No se consultaron cuentas, mensajes de proveedores ni información privada.

El archivo versionado [`portal/data/machinery_reference.json`](../portal/data/machinery_reference.json) conserva URL de origen, fecha, SHA-256 de la captura, categoría observada y enlaces de cada modelo. Cuando la fuente es una tarjeta concreta, su referencia se guarda como `web_reference`. **Esa referencia es del anuncio del sitio principal; no se usa como número de serie de la máquina.**

Estas observaciones sirven para orientar nombres y tipos. No acreditan disponibilidad actual, propiedad, condición mecánica ni especificaciones de un equipo del anunciante. La captura original completa permanece como evidencia de trabajo fuera del repositorio; no se publica con el portal.

## Equipos concretos visibles en la portada consultada

Los siguientes datos corresponden a lo mostrado por la página durante la consulta. No se cargan como inventario ni se utilizan para completar borradores.

| Ficha del sitio principal | Tipo | Marca y modelo | Año mostrado | Horas mostradas |
|---|---|---|---|---|
| [Referencia 1782846072230411](https://www.imcmexico.com.mx/catalogo-de-plataformas-elevadoras-jlg-e450aj-1782846072230411) | Plataformas elevadoras | JLG E450AJ | 1996 | 6.000 |
| [Referencia 1782845630555184](https://www.imcmexico.com.mx/catalogo-de-plataformas-elevadoras-jlg-e450aj-1782845630555184) | Plataformas elevadoras | JLG E450AJ | 2024 | 4 |
| [Referencia 1782753956794700](https://www.imcmexico.com.mx/catalogo-de-gruas-tadano-gr150-1782753956794700) | Grúas | Tadano GR150 | 2015 | 6.828 |
| [Referencia 1782412064971384](https://www.imcmexico.com.mx/catalogo-de-excavadoras-hidraulicas-komatsu-pc200-l-1782412064971384) | Excavadoras hidráulicas | Komatsu PC200 L | 2017 | 3.740 |
| [Referencia 1782410705122071](https://www.imcmexico.com.mx/catalogo-de-excavadoras-hidraulicas-caterpillar-320dl-1782410705122071) | Excavadoras hidráulicas | Caterpillar 320DL | 2023 | 2.500 |

Los años y horas son declaraciones visibles del sitio, no datos certificados del fabricante. Si una ficha cambia posteriormente, esta tabla describe la observación documentada, no su estado actual.

## Sugerencias iniciales del formulario

`seed` incorpora **9 marcas y 9 modelos**. La navegación oficial permite proponer nombres, sin copiar anuncios, fotografías, precios, año, horas, disponibilidad o capacidades técnicas.

| Marca | Modelo | Categoría en el portal | Fuente oficial |
|---|---|---|---|
| Caterpillar | 320DL | Excavadoras | [Ficha observada](https://www.imcmexico.com.mx/catalogo-de-excavadoras-hidraulicas-caterpillar-320dl-1782410705122071) |
| Komatsu | PC200 L | Excavadoras | [Ficha observada](https://www.imcmexico.com.mx/catalogo-de-excavadoras-hidraulicas-komatsu-pc200-l-1782412064971384) |
| JLG | E450AJ | Plataformas elevadoras | [Ficha observada](https://www.imcmexico.com.mx/catalogo-de-plataformas-elevadoras-jlg-e450aj-1782846072230411) |
| Tadano | GR150 | Grúas | [Ficha observada](https://www.imcmexico.com.mx/catalogo-de-gruas-tadano-gr150-1782753956794700) |
| Case | 845 B | Motoniveladoras | [Catálogo de motoconformadoras](https://www.imcmexico.com.mx/catalogo-de-motoconformadoras-case-845-b) |
| Bobcat | B100 | Retroexcavadoras | [Catálogo](https://www.imcmexico.com.mx/catalogo-de-retroexcavadoras-bobcat-b100) |
| Bomag | BW100 | Compactadores | [Catálogo de compactadora vibratoria](https://www.imcmexico.com.mx/catalogo-de-compactadora-vibratoria-bomag-bw100) |
| Atlas Copco | ST710 | Cargadores | [Catálogo de cargadoras sobre ruedas](https://www.imcmexico.com.mx/catalogo-de-cargadoras-sobre-ruedas-atlas-copco-st710) |
| Altec | A77TE93 | Grúas | [Catálogo](https://www.imcmexico.com.mx/catalogo-de-gruas-altec-a77te93) |

Se conservan las categorías existentes: por ejemplo, el nombre «Motoconformadoras» del sitio principal se relaciona con «Motoniveladoras» en el portal. El seed no renombra categorías previamente configuradas.

El formulario usa listas de sugerencias (`datalist`) y permite escribir otra marca o modelo. Los modelos sugeridos se filtran por marca y categoría. Cambiar cualquiera de ellas **no borra ni reemplaza el texto ya declarado**. Elegir un modelo no rellena ningún dato técnico ni la serie. Las entradas inactivas y los modelos de marcas o categorías inactivas no se recomiendan.

## Categorías y campos

Se añaden **11 categorías** verificadas en los enlaces públicos, para un total de **23 categorías iniciales**: plataformas elevadoras, pavimentadoras, zanjadoras, perforadoras, compresores, minicargadores, trituradoras, cribas, manipuladores telescópicos, maquinaria agrícola y maquinaria forestal.

Los formularios reutilizan los campos estándar existentes: potencia, peso, capacidad, dimensiones, combustible, motor y accesorios, según el tipo de equipo. Cada valor permanece vacío hasta que lo declare el anunciante o acepte una sugerencia de análisis de sus propias imágenes. No hay capacidades, potencias ni dimensiones predeterminadas por modelo.

El administrador puede gestionar marcas, modelos y campos de categoría. `seed` sólo crea las entradas ausentes: conserva nombres, asignaciones, campos personalizados y estados inactivos existentes, y evita duplicar marcas o modelos por diferencias de mayúsculas. No crea usuarios, máquinas, activos, versiones ni publicaciones.

## Validación

- Cuatro pruebas Django verifican repetición segura del seed, conservación de configuración, ausencia de inventario, selección de sugerencias activas y aceptación de valores libres sin completar datos técnicos.
- `node portal/tests/catalog_dom_test.cjs` ejecuta la lógica real de sugerencias y verifica los filtros y la conservación de textos escritos al cambiar marca o categoría.
- `node --check portal/static/portal/catalog.js` valida la sintaxis.

El estado de despliegue y las evidencias generales de la plataforma se documentan por separado en [Aceptación](acceptance.md).
