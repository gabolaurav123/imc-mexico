# Auditoría de acceso al sitio principal — 2026-09-23

## Alcance

Inventario local, de solo lectura, del repositorio `gabolaurav123/imc-mexico`,
sus documentos y su configuración declarada. Este inventario no prueba
credenciales ni inspecciona archivos personales o valores secretos. La revisión
pública en navegador y el despliegue del módulo se documentan por separado en
[el informe de entrega](audit-and-adaptation-2026-09-23.md).

El resultado distingue el portal complementario de Django del sitio principal
`https://www.imcmexico.com.mx/`. No hay evidencia de que ambos compartan un
repositorio, una base de datos, una sesión o un canal de despliegue.

**Alcance aclarado por el propietario:** analizar el principal y aplicar los
cambios al módulo. La falta de acceso al hosting principal sólo afecta a la
conexión futura; no bloquea las mejoras ni el despliegue del módulo actual.

## Acceso comprobable disponible

| Recurso | Evidencia local | Alcance comprobable |
| --- | --- | --- |
| Código del portal complementario | Remoto Git `https://github.com/gabolaurav123/imc-mexico.git`, rama `main`, commit local `83ccb63` | Código Django del portal; no es el código de la web principal. |
| Despliegue del portal | `README.md` y `docs/operations.md` describen un servicio Seenode `imc-mexico` y una base Neon PostgreSQL; existe sesión autorizada en su panel web | Se puede desplegar y comprobar el módulo mediante el panel de Seenode. No acredita acceso al alojamiento del dominio principal. |
| Configuración local privada | Existe `.env`, ignorado por Git. Se revisaron sólo nombres de variables: aplicación, Neon/PostgreSQL, SMTP y OpenAI. | Puede configurar el portal complementario. No contiene una variable declarada para FTP/SFTP/SSH/cPanel/Plesk, MySQL/MariaDB, API, OAuth/SSO ni receptor del sitio principal. No se validaron valores. |
| Automatización GitHub | `.github/workflows/checks.yml` ejecuta verificaciones de aplicación | CI de pruebas. No despliega ni integra con el dominio principal. |
| Sitio principal | `docs/main-site-observations-2026-09-23.md` registra únicamente observación pública anterior: Apache, `PHPSESSID`, rutas PHP y JavaScript clásico | Una interfaz pública observada. No acredita acceso administrativo, acceso de archivos, contrato de endpoints de escritura, ni motor/esquema de base de datos. |

No se encontraron archivos PHP, SQL, exportaciones MySQL/MariaDB, archivos de
WordPress/Composer, llaves SSH, configuración de cPanel/Plesk, infraestructura
de despliegue para el dominio principal, ni un cliente HTTP en
`portal/integration.py`. Esta última pieza declara explícitamente que prepara y
registra acuses locales sin comunicarse por red con el sitio principal.

## Información necesaria para la conexión futura

Para modificar o integrar de forma segura el sitio principal hace falta, como
mínimo, que su titular entregue o habilite uno de estos caminos autorizados:

1. Acceso al repositorio o una copia de las fuentes PHP realmente desplegadas,
   más el procedimiento de despliegue y un entorno de prueba; o acceso de
   hosting limitado al directorio de la aplicación mediante SFTP/SSH y un
   respaldo verificable.
2. Un contrato de integración mantenido por el principal: URL, método,
   autenticación servidor a servidor, esquema de solicitud y respuesta,
   política de reintentos/idempotencia, límites de archivos y ambiente de
   pruebas.
3. El esquema aprobado o una API administrativa para identificar las entidades
   reales de usuario/anunciante, maquinaria, tipo, marca, modelo, fotos,
   publicación y estado. No debe deducirse desde las rutas PHP públicas ni
   desde la `Referencia` visible.
4. Una cuenta administrativa o un operador del principal que pueda instalar el
   adaptador, crear las credenciales de servicio y devolver un acuse con el ID
   canónico y URL publicados.

La existencia de un índice de directorio en `/adminMex1389`, una sesión pública
sin autenticar o los nombres de rutas `AJAX_*.php` no satisfacen ninguno de esos
requisitos.

## Artefactos factibles sin las fuentes del principal

No hay un artefacto PHP que pueda desplegarse en `www.imcmexico.com.mx` de forma
realista o segura sin acceso a sus fuentes/hosting. Un archivo PHP aislado no
sabe dónde se carga, cómo inicializa la aplicación, cómo autenticar una llamada
ni qué tablas, permisos y transacciones usar.

Sí están disponibles en el portal complementario, para que un receptor
autorizado los consuma:

- una exportación JSON y ZIP de la versión aprobada, con manifiesto de archivos,
  tamaños, MIME, hashes, orden y portada;
- `delivery_id` como clave de idempotencia y `payload_sha256` para enlazar el
  acuse al contenido exacto;
- el registro local del acuse con `remote_id`, referencia visible y URL HTTPS.

Estos son paquetes de intercambio, no publicadores remotos. Un administrador
del principal podría implementar después un adaptador PHP del lado que controla,
pero sus campos deben mapearse al esquema confirmado y no a nombres inventados.

## Plan mínimo de integración con el principal

1. El principal entrega fuentes/hosting de prueba o define un endpoint de
   importación autenticado y su contrato versionado.
2. Se obtiene un extracto autorizado del catálogo con IDs reales de
   tipo/marca/modelo y se configura el adaptador local existente para validar
   sólo esas coincidencias exactas.
3. El receptor crea o actualiza la maquinaria en una transacción propia,
   conserva la clave de idempotencia y devuelve `remote_id`, referencia visible,
   URL HTTPS, estado y la huella recibida. Debe rechazar duplicados y responder
   de modo recuperable ante reintentos.
4. El portal envía únicamente una versión aprobada y sus fotos autorizadas por
   un canal servidor a servidor; no expone credenciales ni rutas privadas al
   navegador.
5. Un operador coteja la primera publicación en el principal y registra el
   acuse. Las actualizaciones de precio, disponibilidad, empresas y contactos
   sólo se habilitan después de acordar cuál sistema es autoritativo para cada
   campo.

Hasta completar el paso 1, el estado correcto es exportación preparada con acuse
manual verificable; no publicación automática ni sincronización bidireccional.
