# Síntesis de fragmentos: resultado final

El envío final reduce el total de **306.723 a 290.713 instrucciones**: ahorra
**16.010 (5,22 %)**. Mejoran 910 puzles, 90 mantienen su longitud y ninguno empeora.
Frente a la solución original de 1.490.379 instrucciones, el ahorro acumulado es
1.199.666 (80,49 %). Son resultados de validación local.

## Qué cambia

El sintetizador reemplaza regiones privadas de hasta seis operaciones por
expresiones de una a tres operaciones. Puede introducir valores intermedios que
no existían en el programa anterior. Protege las dependencias compartidas y los
objetivos alcanzados transitoriamente, y acepta únicamente programas ejecutables,
válidos y estrictamente más cortos.

La búsqueda de grafos retiene hasta ocho alternativas por ronda y las compara
por la longitud del programa emitido. Esto permite aprovechar otro candidato
cuando el grafo más pequeño no consigue una asignación de registros adecuada.

En los primeros 100 puzles, repetir el optimizador anterior ahorró 94 instrucciones;
seleccionar entre ocho grafos, 239; aplicar síntesis, 1.475; ejecutar grafos antes
de síntesis, 970; y priorizar síntesis, 1.495. Cada método tuvo un presupuesto
nominal de dos segundos de CPU por puzle. Los detalles están en
[la comparación principal](advanced_pilot_v2_comparison.json) y
[el piloto que prioriza síntesis](advanced_priority_pilot_comparison.json).

La estrategia elegida aplica síntesis primero y dedica el tiempo restante a los
grafos. La ejecución completa obtuvo 290.733 instrucciones en 184 segundos con
ocho procesos. Combinar sus programas con los mejores resultados de los pilotos
ahorró otras 20 instrucciones. El combinador registra el origen de cada solución.

## Resultados por familia estimada

| Familia | Puzles | Mejorados | Antes | Después | Ahorro |
|---|---:|---:|---:|---:|---:|
| Independientes | 253 | 234 | 100.670 | 97.020 | 3.650 |
| Mixtos | 222 | 211 | 85.744 | 79.645 | 6.099 |
| Compartidos | 271 | 247 | 79.004 | 73.827 | 5.177 |
| Multiplicativos | 238 | 218 | 41.248 | 40.164 | 1.084 |
| Tiny | 16 | 0 | 57 | 57 | 0 |
| **Total** | **1.000** | **910** | **306.723** | **290.713** | **16.010** |

## Verificación y límites

Las 21 pruebas de los dos optimizadores pasan, incluidos 120 programas aleatorios
repartidos entre ambas suites. Se validaron independientemente los 1.000 programas
finales y todos los envíos usados en la combinación. Cada programa final tiene la
menor longitud entre las entradas guardadas para ese puzle. Los 16 programas
`tiny` permanecen idénticos a los de la etapa anterior.

El máximo por puzle es 589 instrucciones y el máximo por celda, 8.389 bytes.
El ZIP contiene exclusivamente el CSV final y se ha comprobado que sus bytes
coinciden con el archivo validado.

La búsqueda es heurística: limita las entradas disponibles, las regiones y los
candidatos; no certifica optimalidad global. El límite de CPU es cooperativo y
la limpieza y validación pueden excederlo. Las decisiones próximas al límite
pueden variar al repetir una ejecución. Los 184 segundos corresponden a la
pasada completa elegida, sin incluir los pilotos ni la combinación final.

## Archivos

- [CSV final](../submissions/submission_advanced.csv).
- [ZIP final](../deliverables/submission_advanced.zip).
- [Procedencia por puzle y validación](advanced_final_report.json).
- [Comparación por familia](advanced_final_comparison.json).
- [Informe de la ejecución completa](advanced_synthesis_first_report.json).
- [Comandos de ejecución y combinación](../README.md).
