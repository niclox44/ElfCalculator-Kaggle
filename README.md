# Santa 2026 — The Elf Calculator

Proyecto de optimización para construir los 1.000 programas aritméticos de la competición con el menor número total de instrucciones.

## Búsqueda activa de 130.000 instrucciones

Mejor envío validado a 22/11/2026: **132.255 instrucciones** en
`submissions/submission_public_v89.csv`, con ZIP en
`deliverables/submission_public_v89.zip`. Los 1.000 programas son válidos y
ningún puzle empeora respecto al envío anterior. Faltan 2.255 instrucciones;
el objetivo todavía no se ha alcanzado. Estado actual y hash en
`reports/goal_130k_progress.json`.

Este resultado incorpora programas públicos Apache-2.0 de goodpjw2008 y
Juan-Severiano. El ahorro desde 181.974 hasta 132.255 procede de esas
referencias; no es una mejora producida por nuestros optimizadores.
La procedencia está en `third_party/goodpjw_v89/NOTICE.md`,
`third_party/santa_dictionary/NOTICE.md` y `reports/public_v89.json`.
El mejor resultado construido exclusivamente aquí es 181.974.

Los nuevos motores locales incluyen reducción conjunta por cocientes y residuos,
reutilización de factores, síntesis de intermediarios compartidos y planificación
de registros. Los experimentos opcionales de selección de recetas usan C++17
y la biblioteca de desarrollo Z3; el constructor público de diccionarios usa
C++17. El validador independiente sigue usando solo la biblioteca estándar de Python.
Las cifras de las secciones siguientes documentan etapas anteriores.

Después de fijar la referencia pública, la síntesis global de un intermediario
se ejecutó sobre los 1.000 puzles sin ahorro adicional. Los pilotos de 100 casos
de selección Z3, síntesis de dos intermediarios, reconstrucción conjunta de
pares y sustitución de valores compartidos tampoco mejoraron el envío.
Estos resultados se conservan en `reports/public_global.json`,
`reports/smt_public_pilot.json`, `reports/smt_bv_public_pilot.json`,
`reports/multi_helper_public_pilot.json`, `reports/lns_pair_pilot.json` y
`reports/rebase2_pilot.json`. Son resultados negativos de búsquedas limitadas,
no pruebas de optimalidad ni de imposibilidad de alcanzar 130.000.

Backend opcional CP-SAT: `src/cpsat_recipe_optimizer.py`. Sus dependencias se
instalan dentro del proyecto con
`python3 -m pip install --target .deps/ortools -r requirements-optimization.lock`.
El selector cobra todos los nodos nuevos, impone un orden sin ciclos y verifica
el programa final con el validador existente. Pruebas controladas comprueban
que selecciona correctamente uno y dos intermediarios nuevos compartidos.

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
- `src/short_synthesis_optimizer.py`: síntesis acotada de fragmentos con
  intermediarios nuevos y entre una y tres operaciones.
- `src/advanced_optimizer.py`: comparación de estrategias con presupuesto de
  CPU por puzle y ejecución de la síntesis seguida de búsqueda de grafos.
- `src/test_short_synthesis_optimizer.py`: pruebas de síntesis, planificación
  entre varios candidatos y conservación de objetivos y dependencias compartidas.
- `src/merge_best_submissions.py`: valida varios envíos completos y conserva el
  programa más corto por puzle, registrando su procedencia.
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
- Puntuación con tres/cuatro niveles: `363,056`.
- Puntuación tras la primera etapa de optimización de grafos: `338,407`.
- Puntuación con el planificador híbrido: `322,106`.
- Puntuación con catálogo de recetas y reescritura SSA: `306,723`.
- Puntuación con síntesis de fragmentos y selección de candidatos: `290,713`.
- Mejor puntuación local, tras búsqueda ampliada y construcción por bases: `288,244`.
- Última mejora: `2,469` instrucciones (`0.85 %`), en 213 puzles; ninguno empeora.
- Mejora acumulada frente a la solución base: `1,202,135` instrucciones (`80.66 %`).
- Los 1.000 programas se validan localmente contra las reglas del concurso.
- Máximo por puzle: `583` instrucciones; máximo por celda: `8,475` bytes.

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
etapa de anclas profundas se regenera así:

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
  --submission submissions/submission_target130k_radix.csv
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

El ZIP de esta etapa contiene únicamente `submission_hybrid.csv`.

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

## Síntesis de fragmentos y selección de candidatos ejecutables

La búsqueda de grafos admite `--candidate-width 8`: conserva hasta ocho
alternativas de cada ronda y selecciona por la longitud del programa ejecutable.
Un grafo pequeño que no consigue asignar registros ya no descarta por sí solo
las demás alternativas retenidas. El valor predeterminado sigue siendo uno
para conservar la configuración de la etapa anterior.

El sintetizador trabaja sobre regiones privadas del grafo SSA de hasta seis
operaciones, protegiendo las dependencias usadas por otros resultados y los
objetivos transitorios. Enumera reemplazos de una a tres operaciones con nuevos
intermediarios en cadenas o ramas. Usa aritmética entera exacta, sin constantes
gratuitas ni intermediarios fuera de los límites del puzle. La enumeración está
acotada por valores de entrada, candidatos, regiones y tiempo; no prueba
optimalidad global.

La comparación de los primeros 100 puzles, con el mismo presupuesto nominal de
dos segundos de CPU por puzle y método, dio:

| Método | Ahorro adicional | Puzles mejorados |
|---|---:|---:|
| Repetir el optimizador anterior | 94 | 9 |
| Seleccionar entre ocho grafos | 239 | 14 |
| Síntesis de fragmentos | 1.475 | 92 |
| Grafos primero y después síntesis | 970 | 83 |
| Síntesis primero y grafos con el tiempo restante | 1.495 | 92 |

El presupuesto es cooperativo: se comprueba entre unidades de búsqueda, con
limpieza y validación finales. El informe registra el tiempo efectivo y los
excesos sobre el presupuesto. Las decisiones cercanas al límite pueden
variar entre ejecuciones. Los métodos no tienen por qué agotar todo su tiempo.

Reproducir la comparación principal:

```bash
python3 src/advanced_optimizer.py \
  --puzzles data/puzzles.csv \
  --current submissions/submission_recipe_graph.csv \
  --source submissions/submission_deep_anchor.csv \
  --source submissions/submission_multifactor.csv \
  --source submissions/submission_signed_digits.csv \
  --modes baseline wide synthesis combined \
  --prefix advanced_pilot_v2 --end-index 100 \
  --cpu-budget 2 --windows 512 --workers 4
```

La variante que prioriza la síntesis se compara con `--modes synthesis_first`.
Los informes de la comparación están en `reports/advanced_pilot_v2_comparison.json`
y `reports/advanced_priority_pilot_comparison.json`.

Ejecutar la variante elegida sobre los 1.000 puzles:

```bash
python3 src/advanced_optimizer.py \
  --puzzles data/puzzles.csv \
  --current submissions/submission_recipe_graph.csv \
  --source submissions/submission_deep_anchor.csv \
  --source submissions/submission_multifactor.csv \
  --source submissions/submission_signed_digits.csv \
  --modes synthesis_first --prefix advanced \
  --cpu-budget 2 --windows 512 --workers 8
```

Ejecutar las pruebas de ambas etapas:

```bash
python3 -m unittest discover -s src -p 'test_*optimizer.py' -v
```


La ejecución completa produjo **290.733 instrucciones** en 184 segundos con ocho
procesos. Al conservar también las mejores soluciones puntuales de los pilotos,
el resultado final es **290.713 instrucciones**: 910 puzles mejoran, 90 mantienen
su longitud y ninguno empeora. Los 16 programas `tiny` permanecen idénticos.

Recombinar los resultados guardados, con validación de cada entrada y del envío final:

```bash
python3 src/merge_best_submissions.py \
  --puzzles data/puzzles.csv \
  --base submissions/submission_recipe_graph.csv \
  --candidate submissions/submission_advanced_synthesis_first.csv \
  --candidate submissions/submission_advanced_pilot_baseline.csv \
  --candidate submissions/submission_advanced_pilot_wide.csv \
  --candidate submissions/submission_advanced_pilot_synthesis.csv \
  --candidate submissions/submission_advanced_pilot_combined.csv \
  --candidate submissions/submission_advanced_pilot_v2_baseline.csv \
  --candidate submissions/submission_advanced_pilot_v2_wide.csv \
  --candidate submissions/submission_advanced_pilot_v2_synthesis.csv \
  --candidate submissions/submission_advanced_pilot_v2_combined.csv \
  --candidate submissions/submission_advanced_priority_pilot_synthesis_first.csv \
  --output submissions/submission_advanced.csv \
  --report reports/advanced_final_report.json
```

La combinación es reproducible a partir de los CSV guardados. Regenerar búsquedas
con límite de CPU puede producir otras soluciones cerca del límite temporal.
Las 21 pruebas de los optimizadores pasan y el validador independiente acepta los
1.000 programas del envío final.

- Envío de esta etapa: `submissions/submission_advanced.csv`.
- ZIP con un único CSV: `deliverables/submission_advanced.zip`.
- Informe legible: `reports/advanced_summary.md`.
- Procedencia y validación: `reports/advanced_final_report.json`.
- Comparación por familia: `reports/advanced_final_comparison.json`.


## Evaluación del objetivo de 130.000 instrucciones

Dos experimentos adicionales reducen el total a **288.244 instrucciones**. El
objetivo de menos de 130.000 no está alcanzado. La búsqueda ampliada sobre los
primeros 100 puzles ahorra 254 instrucciones; la construcción por bases sobre
los 1.000 ahorra otras 2.215. El diagnóstico, los límites y los comandos están en
`reports/target130k_assessment.md`.

- Mejor envío actual: `submissions/submission_target130k_radix.csv`.
- ZIP validado: `deliverables/submission_target130k_radix.zip`.
- Código experimental: `experiments/target130k_radix_probe.py`.
