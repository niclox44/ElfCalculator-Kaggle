# Catálogo de recetas y reescritura de programas

El nuevo optimizador reduce el envío híbrido de **322.106 a 306.723
instrucciones**: un ahorro de **15.383 instrucciones (4,78 %)**.

| Medida | Resultado |
|---|---:|
| Puzles mejorados | 977 / 1.000 |
| Puzles sin cambios | 23 |
| Puzles empeorados | 0 |
| Mediana del ahorro, sobre los 1.000 puzles | 11 instrucciones |
| Mayor ahorro en un puzle | 76 instrucciones |
| Máximo de instrucciones por puzle | 606 |
| Tiempo de ejecución con cuatro procesos | 228 segundos |

## Implementación

`src/recipe_graph_optimizer.py` combina las recetas numéricas de los envíos
híbrido, anclas profundas, factores múltiples y dígitos con signo. Conserva
alternativas para cada valor y prueba sustituciones individuales y coordinadas
de hasta seis valores que comparten un operando. Cada candidato se puntúa por
el número exacto de operaciones necesarias en su grafo compartido. Se rechazan
los ciclos y las dependencias incompletas.

La pasada SSA anterior y posterior busca otras formas de obtener el resultado
de una instrucción usando valores disponibles en ese momento. Genera además
nuevas relaciones exactas entre esos valores. Las dependencias innecesarias se
eliminan preservando todos los objetivos, incluidos los que se sobrescriben más
adelante. Esta primera pasada aporta 8.944 instrucciones del ahorro total;
la búsqueda de grafos y la pasada posterior aportan las 6.439 restantes.

La planificación prueba distintos órdenes de ejecución y reutiliza registros
en su último uso. Incluye una alternativa con recomputación acotada. Ninguno
de los programas elegidos en esta ejecución necesitó esa alternativa; sigue
siendo una posibilidad experimental para otros catálogos o presupuestos.

Un candidato solo sustituye al anterior si el programa ejecutable valida y
tiene menos instrucciones. La búsqueda es heurística: no certifica optimalidad
global y puede descartar grafos que requieran un orden de ejecución no probado.

## Resultados por familia estimada

Las familias son las predicciones del detector existente, no etiquetas oficiales.

| Familia | Puzles | Mejorados | Antes | Después | Ahorro |
|---|---:|---:|---:|---:|---:|
| independent | 253 | 250 | 103.998 | 100.670 | 3.328 |
| mixed | 222 | 222 | 89.554 | 85.744 | 3.810 |
| shared | 271 | 270 | 84.417 | 79.004 | 5.413 |
| multiplicative | 238 | 235 | 44.080 | 41.248 | 2.832 |
| tiny | 16 | 0 | 57 | 57 | 0 |

Los 16 puzles `tiny` mantienen sus soluciones óptimas anteriores.

## Verificación y archivos

- Pasan las 12 pruebas automáticas, incluida una prueba con 40 programas
  aleatorios válidos y límites reducidos de registros.
- El validador independiente acepta los 1.000 programas y los límites de
  formato, instrucciones, registros, valores y tamaño de celda.
- La comparación por identificador confirma que ningún puzle empeora.
- Los primeros 100 programas coinciden exactamente con los de la muestra
  ejecutada con un solo proceso: la ejecución con cuatro procesos conserva
  esas decisiones.
- El ZIP contiene únicamente el CSV final y su contenido coincide byte a byte
  con el archivo de `submissions/`.

El comando de reproducción y los comandos de pruebas están en `README.md`.
El envío es `submissions/submission_recipe_graph.csv`; el paquete preparado es
`deliverables/submission_recipe_graph.zip`. Las métricas por puzle están en
`reports/recipe_graph_report.json` y la comparación final en
`reports/recipe_graph_comparison.json`.
