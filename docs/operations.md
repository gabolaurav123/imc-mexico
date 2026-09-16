# Operación y recuperación

## Arquitectura prevista

Un servicio Seenode con una sola réplica ejecuta `start.py`: primero `deploy.py`
aplica migraciones y datos iniciales con bloqueo asesor en la conexión directa;
después supervisa Gunicorn y el worker persistente. Si un proceso esencial termina,
el contenedor termina para que el proveedor lo reinicie. No depende de una computadora
personal. El volumen `/data` conserva los archivos de `MEDIA_ROOT=/data/media`.
La base PostgreSQL es Neon. No se permite SQLite en producción.

`build.sh` instala `postgresql-client-18` desde el repositorio APT oficial PGDG,
con `Signed-By` limitado a su clave oficial y el codename de `/etc/os-release`.
No instala un servidor PostgreSQL dentro del contenedor. El servidor inicial se
comprobó como PostgreSQL 18.6; el cliente genérico antiguo de una distribución no
debe utilizarse para volcar un servidor de versión superior.

El volumen no se comparte entre servicios: no aumentar réplicas con almacenamiento
local. Para más réplicas, migrar medios a un bucket S3 privado y configurar workers
independientes. No montar medios dentro de archivos estáticos. La aplicación no
entrega rutas públicas del volumen ni del bucket.

Los trabajos de IA viven en PostgreSQL. Un reinicio no los borra: las leases vencidas
se recuperan con el tope de intentos configurado. El estado de anuncios y versiones
aprobadas también reside en PostgreSQL. No borrar ni reinicializar la base al desplegar.

Variables principales: `SECRET_KEY`, `DATABASE_URL`, `DIRECT_URL`, `PUBLIC_URL`,
`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `MEDIA_ROOT`, credenciales SMTP y OpenAI.
Se almacenan en secretos del proveedor, nunca en Git ni en documentación pública.
`DIRECT_URL` debe apuntar al endpoint directo, no al pooler, para migraciones y backups.

## Entrada del administrador

Las cuentas activas del equipo entran por su panel de gestión al iniciar sesión o
visitar `/panel/`: `/operaciones/` para quienes tienen `operate_platform` y `/admin/`
para los demás usuarios staff. Si falta verificar el segundo factor, la entrada
lleva primero a `/panel/seguridad/` y conserva un destino interno seguro. El código
de la aplicación autenticadora debe introducirlo el titular; no se desactiva MFA
ni se cambia su contraseña para resolver problemas de navegación.

La navegación identifica al superadministrador y muestra leads, usuarios,
solicitudes y configuración según sus permisos. El panel de operaciones filtra
también los datos y contadores en el servidor: ocultar un enlace no concede ni
revoca por sí solo acceso. `/panel/?modo=anunciante` permite usar explícitamente
las herramientas personales de maquinaria sin alterar el rol administrativo.

## Supervisión

- `/salud/` verifica conectividad a la base. También revisar logs de Gunicorn y
  `runworker`, jobs fallidos/antiguos y avisos de correo desde operaciones.
- Confirmar espacio libre del volumen, duración/estado del último backup y estado
  del proveedor. El límite de archivos por equipo no limita el total de la cuenta.
- Un correo `sent` fue aceptado por SMTP: verificar recepción real y reputación del
  remitente. Un análisis completado no prueba exactitud de sus datos.
- Si la IA falla, pausar `ai_enabled` sin bloquear el guardado manual. Conservar los
  originales y mostrar el error; nunca convertirlo en éxito ficticio.
- Si se pierde el proceso worker, reiniciar el servicio y esperar recuperación de
  leases. No lanzar trabajos duplicados por SQL ni borrar su historial.
- Para publicación externa, el paquete exportado no implica que la web principal lo
  haya publicado. Registrar el identificador real después de verificarlo.

## Copias de seguridad automáticas

El comando `python manage.py backup_private --daemon` ejecuta una copia cada 24 horas.
Debe ser otro proceso supervisado por `start.py`. Una ejecución manual es
`python manage.py backup_private`. El comando necesita `pg_dump` instalado y de
versión mayor o igual al servidor. `PG_DUMP_BINARY` permite indicar su ruta.

Configuración:

| Variable | Valor inicial / finalidad |
|---|---|
| `BACKUP_DIR` | `/data/backups`, fuera de `MEDIA_ROOT` |
| `BACKUP_INTERVAL_HOURS` | `24` (mínimo efectivo 1 hora) |
| `BACKUP_RETENTION_DAYS` | `7` días para archivos locales verificados |
| `BACKUP_S3_BUCKET` | Bucket externo opcional de respaldos |
| `BACKUP_S3_ENDPOINT_URL` | Endpoint S3 compatible, opcional |
| `BACKUP_S3_REGION` | `us-east-1` |
| `BACKUP_S3_ACCESS_KEY_ID` / `BACKUP_S3_SECRET_ACCESS_KEY` | Credenciales separadas del almacén de imágenes |
| `BACKUP_S3_PREFIX` | `imc-private-backups` |
| `BACKUP_S3_SSE` | `AES256`; ajustar si el proveedor cifra por otro mecanismo |

La copia contiene:

1. `database.dump`, exportación PostgreSQL en formato custom (cuentas, hashes de
   contraseñas, consentimientos, mensajes, versiones, auditoría y trabajos incluidos).
2. Todos los originales y vistas optimizadas referenciados por los registros de
   `Asset`, bajo `media/`, incluso si el almacenamiento activo es S3.
3. `manifest.json`, listado de tamaños y SHA-256 de cada archivo y de la base.

Una transacción de lectura repetible exporta un snapshot que también utiliza
`pg_dump`: la lista de medios coincide con la versión de base respaldada. Los archivos
son inmutables bajo sus claves; no ejecutar una purga física del almacenamiento
mientras corre el respaldo. Los archivos huérfanos que ya no tienen referencia en
base no se incluyen.

El proceso no pasa contraseñas por argumentos: usa un archivo pgpass temporal
con permisos 600 dentro de un directorio 700. El archivo final tiene permisos 600;
la carpeta de copias es privada y nunca se sirve por HTTP. No incluye `.env`, claves
de OpenAI/SMTP ni otros secretos del entorno. El contenido del respaldo sí contiene
datos personales y hashes de acceso: debe tratarse como información privada.

Antes de marcar éxito se comprueba el manifiesto leyendo los bytes de la copia.
Una copia temporal incompleta no se considera respaldo. El nombre final se asigna
después de verificar. El comando comprueba espacio libre antes de empezar; conserva
los respaldos existentes si la siguiente copia falla. El vencimiento de siete días
solo elimina archivos regulares del directorio de backups, después de crear otra
copia correcta; nunca elimina medios activos.

`last-success.json` informa hora, checksum, tamaño y `state`:

- `local_only`: existe copia íntegra en el mismo volumen.
- `external_verified`: el bucket externo confirmó tamaño y metadato checksum de la
  copia subida. La verificación íntegra de restauración también debe hacerse tras
  descargarla en el simulacro periódico.

El archivo local `.tar.gz` **no está cifrado por la aplicación**. Los permisos lo
protegen dentro del sistema; para protección criptográfica usar un destino con
cifrado administrado y acceso restringido. La copia S3 solicita AES256 por defecto.
Configurar bloqueo de acceso público y, preferiblemente, versionado/retención en una
cuenta separada. Establecer la política de ciclo de vida remoto; la aplicación no
borra objetos remotos de backup.

### Recuperación frente a pérdida total del proveedor

Una copia en `/data/backups` comparte el fallo del volumen: no basta si ese volumen
desaparece. Para cubrirlo, configurar y comprobar `BACKUP_S3_BUCKET` en un proveedor o
cuenta independiente, o descargar diariamente las copias con un operador/sistema
externo seguro. Mientras no exista destino externo verificado, registrar esta
limitación como pendiente operativa; no declarar redundancia completa.

Dimensionar almacenamiento: siete copias completas pueden necesitar varias veces el
tamaño de los medios. El volumen inicial de 5 GB no equivale a 5 GB útiles de imágenes
más siete respaldos completos. Aumentar capacidad o mover medios y respaldos al
destino adecuado antes de acercarse al límite.

Neon Free ofrece una ventana de recuperación histórica de hasta 6 horas o 1 GB de
cambios, lo que se alcance primero. Confirmarla en su consola:
no sustituye las copias independientes ni respalda los archivos del volumen. La
política diaria propuesta tiene un punto de recuperación de hasta 24 horas para
base y medios juntos. El tiempo de restauración debe medirse con datos reales; no
se promete una duración sin simulacro.

## Restaurar de forma segura en un entorno nuevo

No hay restauración automática ni comandos que limpien producción. Procedimiento:

1. Elegir una copia anterior al incidente y descargarla desde el destino verificado.
   Guardarla en un directorio privado. Mantener el entorno existente intacto.
2. Comprobar la integridad sin extraer ni modificar nada:

   ```sh
   python manage.py backup_private --verify /ruta/privada/imc-private-FECHA.tar.gz
   ```

3. Crear una base PostgreSQL **nueva y vacía**, un volumen o bucket privado nuevo y
   un despliegue de recuperación sin tráfico público. Usar el mismo commit que
   generó la copia cuando esté disponible. Instalar un `pg_restore` compatible.
4. Extraer la copia verificada dentro de un directorio nuevo y vacío. El verificador
   rechaza rutas ascendentes, entradas duplicadas, enlaces y discrepancias de hash.
   Usar una cuenta de sistema dedicada y conservar permisos privados.
5. Configurar `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGSSLMODE` para **la nueva
   base** y `PGPASSFILE` con un archivo temporal de permisos 600. Comprobar el destino
   antes de ejecutar:

   ```sh
   pg_restore --no-owner --no-acl --exit-on-error --single-transaction --dbname NUEVA_BASE database.dump
   ```

   No usar `--clean` sobre la base de producción. Nunca pegar contraseñas en la línea
   de comandos ni en logs. Eliminar el pgpass temporal después de restaurar.
6. Copiar el contenido de `media/` al nuevo `MEDIA_ROOT` preservando exactamente las
   rutas relativas, o subirlo al nuevo bucket bajo esas mismas claves privadas.
   Verificar hashes frente a `manifest.json`. Restaurar las variables secretas desde
   el gestor de secretos, por separado: no están incluidas en la copia.
7. Mantener `ai_enabled` desactivado, el worker detenido y el correo saliente bloqueado
   durante la validación. Así los trabajos pendientes y avisos antiguos no se vuelven
   a ejecutar por accidente en el entorno de ensayo.
8. Comprobar inicio de sesión/MFA, propietario y permisos, borradores, historial de
   versiones, medios privados, ficha autorizada, descargas PDF y ausencia de acceso
   anónimo a placas/documentos. Comparar conteos clave y verificar disponibilidad de
   máquinas vendidas/retiradas.
9. Probar `pg_restore --list` y la aplicación no basta por sí solo: documentar el
   resultado del simulacro, la hora recuperada y cuánto tardó. Solo después cambiar
   el tráfico al entorno recuperado y habilitar los procesos que correspondan.

## Cambios, rollback y mantenimiento

### Importar los medios sintéticos de los ensayos iniciales

Las pruebas reales de IA realizadas antes de desplegar crearon dos registros de
ensayo en la base y cuatro archivos locales: dos originales y dos vistas JPEG.
Los archivos están marcados visualmente PRUEBA/SIN INVENTARIO y no representan
maquinaria real. No deben desaparecer por cambiar `MEDIA_ROOT` al volumen del host.

Se preparó un paquete separado `synthetic-test-media.tar.gz` con esos cuatro archivos
y un manifiesto de hashes, sin base de datos, secretos ni contactos. Transferirlo
por el mecanismo privado de archivos/consola del proveedor a un directorio temporal
de la aplicación. Si se decide incluirlo como fixture de despliegue, revisar antes
que contiene únicamente ese material sintético; nunca aplicar este mecanismo a
imágenes reales del cliente ni incluirlas en Git.

Desde la consola del servicio, con `MEDIA_ROOT=/data/media` ya configurado:

```sh
python manage.py import_test_media /ruta/privada/synthetic-test-media.tar.gz
python manage.py backup_private
```

El importador solo admite rutas ya referenciadas en `Asset` de usuarios `is_test`.
Valida propósito del paquete, tamaños, hashes, rutas y pertenencia antes de guardar.
No crea cuentas ni maquinarias, no publica fichas y no reemplaza archivos existentes:
si sus bytes difieren, falla. Se puede repetir de forma segura cuando los archivos
coinciden. No se añadió ningún endpoint HTTP de importación.

Si existen otras referencias de medios creadas en un entorno local, transferirlas
mediante un procedimiento privado de migración con manifiesto separado y permisos
adecuados antes de hacer el primer respaldo. `backup_private` falla ante un archivo
referenciado ausente; no lo omite silenciosamente ni declara una copia completa.

Antes de migraciones de datos, crear y verificar un respaldo. `deploy.py` serializa
las migraciones pero no realiza una copia por sí solo. Conservar el commit desplegado
y variables del gestor de secretos. Si una versión falla, regresar al último commit
compatible con el esquema actual; no ejecutar migraciones inversas ni restauraciones
destructivas sin evaluar los datos añadidos después.

La retención legal de datos y solicitudes de supresión requiere procedimiento
operativo de IMC. No borrar instantáneas aprobadas o auditoría para resolver un error.
La fecha de retención configurable no activa una purga física automática.

`python manage.py retention` solo informa. Con `--apply` elimina sesiones vencidas,
límites de frecuencia de más de 31 días y telemetría vencida según `retention_days`,
y redacta el contenido de avisos con enlaces de acceso vencidos. Nunca elimina
medios, maquinarias ni versiones; `--inspect-media` solo informa archivos sin referencia.

### Archivos huérfanos y temporales

`python manage.py audit_media` compara los archivos del almacenamiento con **todos**
los originales y vistas de `Asset`, incluyendo archivos conservados por versiones.
Informa referencias ausentes, archivos sin referencia, bytes antiguos y enlaces
omitidos. No elimina nada por defecto. Para la instalación local, después de revisar
el inventario y disponer de respaldo, un operador puede ejecutar:

```sh
python manage.py audit_media --apply --older-than 7
```

El umbral nunca puede ser menor de siete días y se calcula desde la última
modificación del archivo. Cada candidato debe seguir sin referencia al momento de
borrarlo, conservar su identidad, tamaño y fecha y permanecer dentro de `MEDIA_ROOT`.
No se siguen enlaces simbólicos, junctions ni puntos de redirección. No se eliminan
directorios, registros, medios activos ni versiones. Ejecutar la limpieza durante
una ventana sin importaciones o migraciones de medios que reutilicen rutas antiguas;
las cargas ordinarias generan rutas nuevas y quedan protegidas por la antigüedad.
La comprobación final de referencias no sustituye esa coordinación con operaciones
externas de importación. Este comando **no se ejecutó con `--apply` en producción**.

Con almacenamiento S3, el comando ofrece inventario de solo lectura mediante el
listado del bucket privado y rechaza `--apply`: la purga remota no está implementada.
El inventario requiere permiso `ListBucket`; nunca necesita permiso de borrado.

### Comprobaciones realizadas y pendientes

- Verificados con pruebas automatizadas: integridad de manifiesto, detección de
  medios alterados, rechazo de traversal y credenciales fuera de argumentos.
- Simulacro real completado el **15 de septiembre de 2026, 23:34 UTC**: exportación
  de Neon PostgreSQL 18.6 con `pg_dump` 18.6 y restauración mediante `pg_restore`
  en la nueva base aislada `imc_restore_test`, dentro del mismo proyecto dedicado.
  Coincidieron los conteos de las **34 tablas** con el snapshot del respaldo y los
  hashes SHA-256 y tamaños de los **10 archivos** recuperados (5 originales y
  5 vistas: JPEG, HEIC y MOV con sus conversiones). Duración: **128,67 segundos**.
  El paquete privado pesó **757.087 bytes**. No se modificaron tablas de origen,
  no se usó `--clean` ni se eliminó la base temporal; no tiene web ni worker activo.
  La evidencia detallada y el paquete quedaron fuera de Git en el directorio privado
  de trabajo. El cliente portable se obtuvo de los binarios oficiales EDB enlazados
  por PostgreSQL, sin instalar un servidor local.
- El respaldo del simulacro tiene estado `local_only`. La copia a un bucket externo
  aún requiere configuración y comprobación; la recuperación local exitosa no
  demuestra que un desastre que afecte al volumen deje disponible ese respaldo.
- El daemon del hosting requiere comprobación en el entorno desplegado. El panel
  `/operaciones/` muestra únicamente la fecha, el alcance local/externo, el tamaño y
  el número de medios de `BACKUP_DIR/last-success.json`. Un registro ausente o inválido
  aparece como «No comprobado», y una copia de más de 48 horas muestra una alerta.
  Este resumen no expone nombres de archivos, rutas, buckets ni credenciales, y no
  afirma que el proceso siga activo solo porque terminó una copia anterior.

Referencias técnicas: [pg_dump y snapshots sincronizados](https://www.postgresql.org/docs/current/app-pgdump.html),
[variables y credenciales de libpq](https://www.postgresql.org/docs/current/libpq-envars.html),
[repositorio APT oficial PostgreSQL](https://www.postgresql.org/download/linux/debian/),
[límites de recuperación de Neon](https://neon.com/pricing).
