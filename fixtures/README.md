# Medios sintéticos de aceptación

`synthetic-test-media.tar.gz` contiene únicamente cuatro archivos JPEG de una
placa sintética marcada PRUEBA, generados para comprobar la distinción entre la
identificación del motor y la maquinaria. No contiene fotos de inventario,
datos de personas, credenciales, base de datos ni archivos de clientes.

El paquete conserva las rutas de los registros `is_test` utilizados en Neon.
`import_test_media` comprueba pertenencia a cuentas de prueba, rutas, tamaños y
SHA256. No crea registros ni sobrescribe archivos. En la instancia de aceptación
se habilita con `IMPORT_SYNTHETIC_TEST_MEDIA=true` para trasladar los originales
locales al volumen persistente y conservar reproducibles esos ensayos. En una
instalación nueva se deja desactivado.
