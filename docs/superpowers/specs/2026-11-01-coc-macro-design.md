# CoC Macro: diseño

Fecha: 2026-11-01. Estado: borrador para aprobar. Las decisiones marcadas **[mi decisión]** las tomé yo, no el usuario.

## Intención

El usuario ataca a menudo en Clash of Clans y quiere ir rápido. Quiere una app de escritorio pequeña que repita el ciclo "buscar aldea buena → desplegar tropas → rendirse al pasar el 50% → volver a empezar" sin intervenir y sin tener el juego en primer plano. Con eso farmea recursos rápido.

## Entorno verificado (spike, 2026-11-01)

- Juego en **Google Play Games para PC**, proceso `crosvm`, ventana titulada `Clash of Clans - <nombre>`. Ventana 1315×776, área cliente 1296×729 (desfase 9,38).
- **Captura sin foco: funciona.** `PrintWindow` con flag 2 devuelve la imagen aunque la ventana esté detrás de otras.
- **Click sin foco: funciona.** `PostMessage` de `WM_LBUTTONDOWN`/`WM_LBUTTONUP` a la ventana de nivel superior, con coordenadas de cliente, seleccionó un edificio con Orca en primer plano.
- **No verificado:** arrastres (`WM_MOUSEMOVE` con botón pulsado), pulsación larga, captura con la ventana minimizada, y fiabilidad de OCR sobre los números.

## Objetivos

1. Ventana de escritorio con botones **Empezar**, **Parar**, **Grabar despliegue** y selector de despliegues guardados con nombre.
2. Bucle automático:
   1. Clicks fijos: Batalla → Buscar batalla → Atacar.
   2. Esperar a que cargue la aldea enemiga.
   3. Leer oro y elixir (los dos primeros números, arriba a la izquierda). Si **ambos** son mayores que el umbral (por defecto 500.000), atacar. Si no, pulsar **Siguiente** y volver a leer, hasta encontrar una aldea válida.
   4. Reproducir el despliegue de tropas elegido, con las pausas de la grabación.
   5. Con las tropas desplegadas, vigilar el % de daño. Al superar el umbral (por defecto 50%), pulsar Rendirse → Vale → Volver.
   6. Volver al paso 1.
3. Todo debe funcionar con el juego en segundo plano (visible detrás de otras ventanas).
4. Varios despliegues grabados, elegibles desde la interfaz.

## No objetivos

- Reconocer tropas, decidir dónde atacar o adaptar el ataque a cada aldea. El despliegue es siempre el mismo clic grabado.
- Mejorar edificios, entrenar tropas, donar, ni nada fuera del bucle de atacar y rendirse (ver pregunta abierta).
- Soportar otros emuladores o móvil. Solo Google Play Games PC.
- Leer la memoria del juego, inyectar código o modificar el juego.

## Antiobjetivos (sería un fracaso aunque "funcione")

- Que se descontrole sin forma de pararlo. Debe haber una tecla global de parada **[mi decisión: F8]** que funcione aunque el juego no tenga foco, y un botón Parar.
- Que pulse a ciegas en una pantalla inesperada (por ejemplo un diálogo de error o de conexión). Ante algo que no reconoce, debe parar y avisar, no seguir clicando.
- Que el usuario pierda su grabación por un cierre o un fallo. Se guarda en disco al terminar.

## Restricciones

- Python en Windows 11. Interfaz **tkinter [mi decisión]**.
- Aviso aceptado por el usuario: Supercell prohíbe automatizar ataques; hay riesgo de ban de la cuenta. La app debe mostrar este aviso la primera vez que se abre.
- Las coordenadas se guardan **relativas al tamaño del área cliente (0–1)**, no en píxeles absolutos, para que sobrevivan a cambios de tamaño de la ventana. **[mi decisión]** Si cambia la proporción de la ventana, avisa y pide recalibrar.
- Identificar la ventana por proceso `crosvm` y título que empiece por `Clash of Clans`.

## Cómo funciona cada pieza

- **Grabar despliegue:** hook global del ratón (por ejemplo `pynput`), filtrado a clicks dentro de la ventana del juego. Guarda cada evento (bajar, subir, mover si hay arrastre) con su posición relativa y el tiempo desde el anterior. Termina con una tecla **[mi decisión: F9]**. Se guarda como JSON, uno por nombre.
- **Reproducir:** envía los mismos eventos con `PostMessage` y respeta las pausas. Si los arrastres no se reproducen bien con mensajes, es un riesgo a resolver (ver abajo).
- **Calibración de botones [mi decisión]:** los botones fijos (Batalla, Buscar batalla, Atacar, Siguiente, Rendirse, Vale, Volver) se registran una vez haciendo clic en cada uno, en vez de ir con coordenadas escritas a mano. Igual para los recortes donde se leen oro, elixir y %: se marcan arrastrando un rectángulo sobre una captura.
- **Lectura de números:** recorte pequeño de cada zona y reconocimiento de dígitos. Método a elegir por quien construya (ver "A decidir por quien construya").
- **Detección de estado [mi decisión]:** antes de cada paso, comprobar que la pantalla es la esperada (por ejemplo, que el botón a pulsar sigue ahí). Cada espera tiene un tiempo máximo. Si se agota, parar y avisar.
- **Configuración** en un JSON: umbral de recursos, umbral de %, despliegue elegido, regiones y botones calibrados.

## Interfaz mínima

Botones Empezar / Parar / Grabar despliegue, desplegable de despliegues, campos de umbral de recursos y de %, contador de ataques hechos, y un registro de texto con lo que está haciendo. Una sola ventana, sin más.

## Riesgos a resolver al principio (antes de construir el resto)

1. **Arrastres sin foco:** probar si `WM_MOUSEMOVE` con botón pulsado despliega tropas con el juego en segundo plano. Si no, plan B: traer la ventana al frente solo durante el despliegue.
2. **OCR:** medir la tasa de acierto de los números de oro, elixir y % con capturas reales de la pantalla de exploración y de la batalla.
3. **Captura minimizada:** confirmar que falla y mostrar un aviso claro si pasa.

## Cómo se verifica

- Pruebas unitarias de la lógica (decidir si atacar, decidir si rendirse, máquina de estados) con capturas guardadas como fixtures. Hacen falta capturas reales de la pantalla de exploración de aldea, de la batalla y del botón Rendirse; las puedo sacar con el mismo método que el spike mientras el usuario esté en esas pantallas.
- Pruebas manuales por tramos: primero solo la lectura de recursos sin clicar, luego un ataque completo vigilado, luego varios seguidos.
- Mostrar la salida de las pruebas antes de dar nada por terminado.

## A decidir por quien construya

- Librería de OCR o lectura de dígitos (por ejemplo, comparación con plantillas de dígitos, o Tesseract/RapidOCR), según lo que mida mejor en el riesgo 2.
- Estructura de módulos y nombres de archivos.
- Cómo reintentar y registrar errores.

## Decisiones del usuario sobre las preguntas abiertas

1. **Reposición de tropas:** el juego rellena tropas, hechizos y héroes solo. La app no entrena nada ni espera a que se rellenen (no objetivo confirmado).
2. **Batalla que acaba sola** (100% de destrucción o fin del tiempo): la app detecta la pantalla de resultados y solo pulsa **Volver**.
