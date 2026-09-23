# Observaciones públicas del sitio principal — 2026-09-23

## Alcance y límite de acceso

Esta nota procede de solicitudes públicas de solo lectura (HTML, JavaScript,
cabeceras HTTP y `robots.txt`) a `https://www.imcmexico.com.mx`. No se inició
sesión, no se enviaron formularios, no se invocaron rutas de escritura, no se
descargaron imágenes y no se accedió a rutas de administración. Por tanto, no
describe un contrato de integración ni el esquema de una base de datos.

La ficha pública expone el formulario de acceso y el JavaScript contiene nombres
de rutas de operaciones. Eso no demuestra acceso público ni autoriza su uso. El
`robots.txt` público además desaconseja el rastreo de `/adminMex1389`; no se
visitó esa ruta. Ninguna API REST o GraphQL documentada fue encontrada en el
material revisado.

## Catálogo y fichas observadas

El catálogo público [Plantas de concreto](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto)
muestra los filtros **Tipo**, **Marca**, **Modelo** y **Nomenclatura**, y las
columnas **Foto**, **Tipo, Marca y Modelo**, **Año**, **Horas** y **Precio**.

Tres fichas verificadas:

| URL | Campos públicos observados |
| --- | --- |
| [Cementech C60](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto-cementech-c60-1668191915090848) | Tipo `PLANTAS DE CONCRETO`; Marca `CEMENTECH`; Modelo `C60`; **Referencia** `1668191915090848`; Año `2020`; Horas `No Disponible`; precio `$ 285,000.00 USD`. |
| [Bohringer B120](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto-bohringer-b120-1709396833023629) | Tipo `PLANTAS DE CONCRETO`; Marca `BOHRINGER`; Modelo `B120`; **Referencia** `1709396833023629`; Año `2023`; Horas `No Disponible`; precio `$ 439,000.00 USD`. |
| [Stephens 10 YARD](https://www.imcmexico.com.mx/catalogo-de-plantas-de-concreto-stephens-10-yard-1710968144890636) | Tipo `PLANTAS DE CONCRETO`; Marca `STEPHENS`; Modelo `10 YARD`; **Referencia** `1710968144890636`; Año `2010`; Horas `No Disponible`; precio `$ 129,000.00 USD`. |

La URL canónica de la primera ficha lleva el patrón visible
`/catalogo-de-{tipo}-{marca}-{modelo}-{referencia}`. La ruta heredada pública
`/catalogo-maquinaria-4.php?Parametros=plantas-de-concreto-cementech-c60-1668191915090848`
redirige a ella. La etiqueta mostrada es **Referencia**: no hay evidencia pública
de que sea una clave primaria de base de datos, de que se pueda enumerar ni de
que sea un identificador apto para escritura.

## Fotos

La portada Open Graph de Cementech es
`/photos/1668191915090848_1668192477-01.jpg`; la ficha la declara JPEG de
`300 × 300`. La galería visible usa
`/photosb/1668191915090848_1668192477-01.jpg`, `-02.jpg` y `-03.jpg`. La imagen
`-01` tiene la clase `Seleccionada`; las siguientes tienen `Desmarcada`, por lo
que `-01` es la portada visual y el sufijo de dos dígitos expresa el orden.

Se observó el mismo formato `{Referencia}_{segundo-número}-{01..NN}.jpg` en
Fastway `1709833853846920_1709835075-01` a `-04`, Bohringer
`1709396833023629_1709397398-01` a `-04`, y Stephens
`1710968144890636_1710968575-01` a `-02`. El segundo número no fue identificado
semánticamente. `photos` y `photosb` son variantes distintas: una consulta HEAD
de la portada Cementech mostró 32,521 bytes para `photos` y 198,773 bytes para
`photosb`, ambas `image/jpeg`; no se infirió dimensión para `photosb`.

## Evidencia técnica y decisión de integración

La respuesta pública identifica `Server: Apache`, usa cookie `PHPSESSID`, carga
`/AJAX_Funciones.js`, `/scripts/funcionesGenerales.js` y
`/scripts/jquery/jquery-1.6.js`, y presenta microdatos `schema.org/Product` y
`Offer`. Esto es evidencia de una interfaz PHP/Apache con JavaScript clásico,
no evidencia de MySQL, de otro motor concreto ni de su modelo interno.

El JavaScript entrega rutas como `POST /AJAX_ListadoMaquinaria_Maquinas.php`,
`POST /AJAX_CotizaFlete.php`, `POST /AJAX_InicioSesion.php` y una redirección
`AdminMaquinas.php?reg=…` en un flujo de creación. Se observaron sin llamarlas:
los nombres no constituyen API pública documentada, contrato de autenticación ni
permiso para crear, modificar, enviar correo o asociar registros.

Por ello `portal.integration_catalogue.resolve_catalogue` acepta únicamente filas
suministradas por un adaptador autorizado y una identidad de tipo/marca/modelo.
Es una prevalidación pura: devuelve `matched`, `missing` o `ambiguous`; conserva
IDs opacos de texto sólo cuando hay una ruta única, y nunca consulta este sitio,
persiste una asociación, crea elementos remotos ni infiere alias.
