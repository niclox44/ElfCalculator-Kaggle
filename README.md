# Santa 2026 — The Elf Calculator

Proyecto de optimización para construir los 1.000 programas aritméticos de la competición con el menor número total de instrucciones.

## Estructura

- `data/`: archivos originales de Kaggle.
- `src/structure_detector.py`: detector de familias estructurales.
- `src/tiny_solver.py`: solucionador exacto para puzzles `tiny`.
- `src/power_basis_solver.py`: construcción con potencias de dos compartidas.
- `src/signed_digit_solver.py`: representaciones binarias y NAF compartidas.
- `src/anchor_difference_solver.py`: objetivos como ancla más/menos diferencia.
- `src/multiplicative_solver.py`: reutilización de un factor común.
- `src/multifactor_solver.py`: reutilización de varios factores y cocientes.
- `src/recursive_anchor_solver.py`: anclas y diferencias en dos niveles.
- `src/deep_anchor_solver.py`: selección entre tres y cuatro niveles de anclas.
- `src/value_graph_optimizer.py`: numeración global de valores, poda y nueva
  asignación de registros.
- `src/ssa_copy_optimizer.py`: propagación conservadora de copias, poda SSA y
  reasignación por vida útil.
- `src/hybrid_planner.py`: planificador por objetivo que mezcla construcción
  directa, anclas, factores y divisiones mediante búsqueda local/beam search.
- `src/recipe_graph_optimizer.py`: catálogo de recetas de varios envíos,
  sustitución de subgrafos y reescritura SSA con valores disponibles.
- `src/test_recipe_graph_optimizer.py`: pruebas de ciclos, cobertura transitoria,
  registros, recomputación y conservación de soluciones óptimas pequeñas.
- `src/merge_hybrid_parts.py`: combina rangos híbridos procesados de forma
  independiente y vuelve a validar el envío completo.
- `src/validate_submission.py`: validador independiente de envíos completos.
- `reports/`: análisis y detalle de soluciones.
- `submissions/`: archivos CSV completos listos para enviar.

Todo el código actual usa únicamente la biblioteca estándar de Python.

## Estado actual

- Puntuación de la solución base: `1,490,379`.
- Puntuación tras resolver exactamente los 16 puzzles `tiny`: `1,490,270`.
- Puntuación con potencias de dos compartidas: `547,572`.
- Puntuación con dígitos binarios/NAF: `439,527`.
- Puntuación con anclas y diferencias: `399,864`.
- Puntuación tras factores múltiples: `397,499`.
- Puntuación con anclas recursivas de dos niveles: `376,815`.
- Mejor puntuación local, con tres/cuatro niveles: `363,056`.
- Puntuación tras la primera etapa de optimización de grafos: `338,407`.
- Puntuación con el planificador híbrido: `322,106`.
- Mejor puntuación local, con catálogo de recetas y reescritura SSA: `306,723`.
- Última mejora frente al híbrido: `15,383` instrucciones (`4.78 %`), en 977 puzzles.
- Mejora acumulada frente a la solución base: `1,183,656` instrucciones (`79.42 %`).
- Los 1.000 programas se validan localmente contra las reglas del concurso.
- Máximo por puzzle: `606` instrucciones; máximo por celda: `8,618` bytes.

## Regenerar la clasificación estructural

```bash
python3 src/structure_detector.py \
  --practice data/practice_puzzles.csv \
  --scored data/puzzles.csv \
  --output reports/structure_report.json
```

## Regenerar el envío con soluciones `tiny` óptimas

```bash
python3 src/tiny_solver.py \
  --puzzles data/puzzles.csv \
  --baseline data/sample_submission.csv \
  --output submissions/submission_tiny_exact.csv \
  --solutions reports/tiny_exact_solutions.csv
```

## Validar un envío

```bash
python3 src/validate_submission.py \
  --puzzles data/puzzles.csv \
  --submission submissions/submission_tiny_exact.csv
```

El validador comprueba identificadores, formato JSON, operaciones, registros, divisiones exactas, valores máximos, objetivos cubiertos, número de instrucciones y tamaño de cada celda.

## Regenerar el envío con potencias compartidas

Este solucionador reutiliza cada potencia de dos entre todos los objetivos del puzzle y conserva las soluciones `tiny` cuando son más cortas.

```bash
python3 src/power_basis_solver.py \
  --puzzles data/puzzles.csv \
  --current submissions/submission_tiny_exact.csv \
  --output submissions/submission_power_basis.csv \
  --report reports/power_basis_report.json
```

## Regenerar las mejoras sucesivas

Cada etapa conserva, puzzle por puzzle, el programa más corto de la etapa
anterior. Los comandos completos están reflejados en los propios scripts; la
última etapa se regenera así:

```bash
python3 src/deep_anchor_solver.py \
  --puzzles data/puzzles.csv \
  --current submissions/submission_recursive_anchor.csv \
  --output submissions/submission_deep_anchor.csv \
  --report reports/deep_anchor_report.json
```

## Validar el mejor envío actual

```bash
python3 src/validate_submission.py \
  --puzzles data/puzzles.csv \
  --submission submissions/submission_recipe_graph.csv
```

## Primera etapa de la fase 2

La pasada agresiva comparte todos los valores iguales y se queda únicamente
con el cono de dependencias necesario para producir los objetivos:

```bash
python3 src/value_graph_optimizer.py \
  --puzzles data/puzzles.csv \
  --current submissions/submission_deep_anchor.csv \
  --output submissions/submission_value_graph.csv \
  --report reports/value_graph_report.json
```

La pasada SSA conservadora elimina copias identidad en los puzzles donde la
compartición global elevaría demasiado la presión sobre los 48 registros:

```bash
python3 src/ssa_copy_optimizer.py \
  --puzzles data/puzzles.csv \
  --current submissions/submission_value_graph.csv \
  --output submissions/submission_phase2_ssa.csv \
  --report reports/ssa_copy_report.json
```

## Planificador híbrido

El planificador genera alternativas por objetivo —directa, ancla/diferencia,
factor/cociente y división exacta—, busca combinaciones que compartan
componentes y ejecuta las dos podas de grafos antes de aceptar cada candidato.
Admite `--start-index` y `--end-index` para procesar rangos independientes.

```bash
python3 src/hybrid_planner.py \
  --puzzles data/puzzles.csv \
  --current submissions/submission_phase2_ssa.csv \
  --output submissions/submission_hybrid.csv \
  --report reports/hybrid_report.json
```

Para ejecuciones por bloques, `src/merge_hybrid_parts.py` combina los rangos y
exige que cubran exactamente los 1.000 puzzles sin solapamientos.

El ZIP para Kaggle debe contener únicamente `submission_hybrid.csv`.

## Catálogo de recetas y reescritura de programas

La nueva etapa extrae todas las formas de obtener cada valor de varios envíos.
Prueba sustituciones individuales y grupos de hasta seis recetas que comparten
un operando. Cuenta exactamente las operaciones del grafo necesario para todos
los objetivos y rechaza las dependencias cíclicas. La búsqueda está acotada y no
certifica optimalidad global.

Antes y después de esa búsqueda, una pasada SSA prueba recetas con operandos que
ya estaban disponibles en el momento de la instrucción original. También
descubre relaciones aritméticas exactas entre esos valores. La poda conserva los
objetivos alcanzados durante el programa, aunque después se sobrescriban.

El emisor prueba órdenes de ejecución distintos y reutiliza los registros en su
último uso. Si no caben todos los valores vivos, intenta recomputar los valores
expulsados, con un presupuesto estricto de instrucciones. Un grafo más pequeño
solo reemplaza el programa anterior si su **programa ejecutable** es más corto y
valida. Las soluciones anteriores se conservan como respaldo en cada puzle.

Ejecución reproducible, únicamente con la biblioteca estándar de Python:

```bash
python3 src/recipe_graph_optimizer.py \
  --puzzles data/puzzles.csv \
  --current submissions/submission_hybrid.csv \
  --source submissions/submission_deep_anchor.csv \
  --source submissions/submission_multifactor.csv \
  --source submissions/submission_signed_digits.csv \
  --output submissions/submission_recipe_graph.csv \
  --report reports/recipe_graph_report.json \
  --rounds 8 --proposal-limit 128 --workers 4
```

`--workers` ejecuta puzles independientes en procesos locales. No cambia las
decisiones del optimizador. `--start-index` y `--end-index` permiten experimentar
en un rango manteniendo los demás programas del envío de entrada. Los parámetros
`--rounds` y `--proposal-limit` limitan la búsqueda de grafos; la pasada SSA usa
hasta tres recorridos antes y después de esa búsqueda.

```bash
python3 -m unittest discover -s src -p 'test_recipe_graph_optimizer.py' -v
python3 src/validate_submission.py \
  --puzzles data/puzzles.csv \
  --submission submissions/submission_recipe_graph.csv
```

El informe incluye resultados por puzle, tiempo, sustituciones SSA, candidatos
cíclicos, fallos de planificación y la validación independiente del envío entero.
Los contadores de movimientos del grafo incluyen estados de búsqueda que pueden
no llegar a convertirse en el programa elegido.

Resultado completo: **322.106 → 306.723 instrucciones**. Mejoran 977 puzzles,
23 se mantienen y ninguno empeora. Los 16 `tiny` mantienen sus soluciones
óptimas. La ejecución tardó 228 segundos con cuatro procesos locales. La muestra
de 100 puzzles ejecutada con un solo proceso produce los mismos programas que
esos mismos puzzles en la ejecución completa con cuatro procesos.

- Envío: `submissions/submission_recipe_graph.csv`.
- ZIP con un único CSV: `deliverables/submission_recipe_graph.zip`.
- Informe legible: `reports/recipe_graph_summary.md`.
- Métricas completas: `reports/recipe_graph_report.json`.
- Comparación y ausencia de regresiones: `reports/recipe_graph_comparison.json`.
