# Evaluación del objetivo de menos de 130.000 instrucciones

El mejor resultado validado de estas pruebas es **288,244 instrucciones**.
No se ha alcanzado el objetivo de menos de 130.000, ni existe todavía evidencia
suficiente para prometer que sea alcanzable con los métodos actuales.

## Qué exigiría el objetivo

Desde 290.713 habría que eliminar al menos 160.714 instrucciones (55,28 %).
Hay 26.898 objetivos distintos que no están presentes inicialmente, sumados por
puzle. El promedio actual antes de estas pruebas era 10,81 instrucciones por
objetivo nuevo; 130.000 exigiría 4,83. Este cociente incluye el coste de construir
los valores compartidos, no es un coste individual asignado a cada objetivo.

La cota elemental de 26.898 instrucciones solo cuenta objetivos nuevos. Es una
cota inferior válida porque cada instrucción produce un valor, pero es demasiado
débil para decidir si 130.000 es viable. No constituye un método de construcción.

## Pruebas realizadas

| Prueba | Cobertura | Resultado | Ahorro |
|---|---|---:|---:|
| Búsqueda ampliada: 24 rondas, 384 propuestas, 4.096 regiones | Primeros 100 puzles | 290.459 | 254 |
| Construcción por bases con cocientes y restos compartidos | 1.000 puzles | 288.244 | 2.215 adicionales |

La primera prueba asignó hasta diez segundos de CPU por puzle. Usó 181,6 segundos
de CPU en total y terminó en 24,4 segundos con ocho procesos: la búsqueda acotada
se agotó antes que el tiempo disponible. Ahorró el 0,857 % de las instrucciones
de esos 100 puzles. Esa muestra no permite asegurar el mismo porcentaje en el resto.

La segunda prueba reconstruye cada objetivo como cociente por base más resto,
o menos un resto equilibrado cuando el límite de valores lo permite. Comparte
componentes iguales y prueba bases fijas y valores iniciales utilizables como
base. Tardó 21,7 segundos con ocho procesos. Su mejora es complementaria, pero
no se aproxima al salto requerido.

En conjunto se ahorran **2,469 instrucciones**, mejoran **213 puzles**,
787 conservan su longitud y ninguno empeora. Los 16 programas tiny
siguen idénticos. Se validaron los 1.000 programas finales y el ZIP contiene
exactamente el CSV validado. Aún faltan **158,245 instrucciones**
por eliminar para quedar estrictamente por debajo de 130.000.

## Qué investigar después

El siguiente experimento con posibilidades de un salto mayor sería reconstruir
conjuntamente grupos de objetivos mediante intermediarios compartidos nuevos:
buscar relaciones aditivas, multiplicativas y divisiones exactas entre varios
objetivos, y evaluar el coste total de construir y mantener sus dependencias.
La búsqueda actual de fragmentos privados no puede cambiar libremente esas
estructuras compartidas. Esta es una hipótesis de trabajo, no una mejora medida.

Conviene comparar esa estrategia sobre una muestra por familias antes de una
búsqueda larga. La aceptación debe seguir usando programas ejecutables, con
asignación real de registros y validación completa. Aumentar únicamente los
límites del optimizador actual no está dando un ahorro del orden necesario.

## Reproducción

Desde la raíz del proyecto:

```bash
python3 src/advanced_optimizer.py \
  --puzzles data/puzzles.csv \
  --current submissions/submission_advanced.csv \
  --modes synthesis_first --prefix target130k_pilot --end-index 100 \
  --cpu-budget 10 --windows 4096 --rounds 24 --proposal-limit 384 --workers 8
python3 experiments/target130k_radix_probe.py
```

El primer paso tiene límites de CPU y puede variar cerca de ellos. El segundo
usa la salida guardada del piloto y una enumeración determinista.

- [CSV validado](../submissions/submission_target130k_radix.csv).
- [ZIP del resultado](../deliverables/submission_target130k_radix.zip).
- [Diagnóstico y comparación](target130k_diagnostics.json).
- [Informe del piloto](target130k_pilot_synthesis_first_report.json).
- [Informe de construcción por bases](target130k_radix_report.json).
- [Código del experimento](../experiments/target130k_radix_probe.py).
