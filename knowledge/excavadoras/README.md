# Biblioteca inicial de excavadoras

Cobertura inicial: Caterpillar 320 **Tier 3** para el mercado MX. La referencia se
tomó el 18 de septiembre de 2026 de la ficha oficial de Caterpillar. Incluye
potencia neta ISO 9249, peso operativo y profundidad máxima; se recupera sólo
cuando la variante Tier 3 y el mercado MX están explícitamente confirmados. Cada cifra es una
especificación del modelo, no una confirmación de la unidad anunciada.

La taxonomía usa familia hidráulica, rodamiento, pluma y brazo/balancín como
dimensiones separadas. Cat distingue excavadoras por tamaño, demolición, largo
alcance y ruedas en su catálogo oficial; sus fichas 320 y 395 documentan que el
largo alcance depende de configuraciones de pluma y brazo. Las referencias se
mantienen con URL, versión y fecha de consulta en cada JSON.

Usa `python manage.py import_technical_knowledge --path knowledge/excavadoras`.
El comando sólo lee archivos locales y deja referencias nuevas o cambiadas como
pendientes e inactivas. Un administrador autenticado debe revisarlas y aprobarlas
antes de que la recuperación exacta pueda usarlas.
