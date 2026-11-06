# Modos: parar con depósitos llenos, mejora de muros, constructores ocupados

Fecha: 2026-11-05. Estado: borrador para aprobar. **[mi decisión]** = lo decidí yo, no el usuario.

## Intención

Hoy el bot solo ataca en bucle. El usuario quiere que el tiempo de farmeo sirva también para gastar
lo farmeado: parar cuando ya no cabe más botín y usar los constructores libres entre ataques
(muros, o la mejora permanente más barata).

## Objetivos

1. **Parar con depósitos llenos** (casilla, activable): antes de cada búsqueda, si los depósitos de
   arriba a la derecha están llenos, no se ataca.
2. **Modo muros**: atacar; al volver a la aldea, si hay constructor libre, mejorar muros y volver a atacar.
3. **Modo constructores ocupados**: atacar hasta depósitos llenos o hasta que algo esté libre
   (constructor, investigador o mascota); entonces mejorar y volver a atacar.
4. Los modos son excluyentes y elegibles desde la ventana (ninguno = comportamiento actual).
5. **Nada de lo que funciona hoy se rompe**: sin modo activo, el ciclo de ataque es idéntico.

## No objetivos / antiobjetivos

- No entrenar tropas, no donar, no elegir qué construir salvo lo descrito.
- No gastar gemas jamás. Si un botón pide gemas, parar y avisar.
- No clicar a ciegas: ante pantalla no reconocida, parar y avisar (como el bot actual).
- Parar con F8 sigue funcionando en cualquier punto de las rutinas nuevas.

## Hechos medidos en el juego real (cuenta secundaria, ventana 1296x729, 2026-11-05)

- Depósitos arriba a la derecha: oro (y~31), elixir (y~73), elixir oscuro (y~115), barra detrás de la cifra.
- Contadores sobre «Construir»: constructores `0/7` (x~1198,y~587) e investigadores `0/2` (x~1250,y~587).
  Se asume formato libres/total.
- Menú Construir (botón x~0.945,y~0.905; cerrar X x~0.984,y~0.032): abajo cuatro contadores
  (constructores, investigadores, yunque, mascotas `0/1`). Filtro: botón arriba-izquierda
  (x~0.7595,y~0.032) con Recurso (oro/elixir/oscuro), Tipo (Ejército, Defensa, Héroe, Recurso, Nuevo,
  Permanente) y Orden (Coste máx., Coste mín.). **El juego recuerda el último filtro**: el bot debe
  fijar Permanente + Coste mín. cada vez.
- Tras cerrar un menú, la cámara queda alejada mostrando toda la aldea; el bloque de muros está arriba
  al centro. Click en el borde inferior del bloque (~0.585,0.335 relativo) selecciona un muro.
- Panel de muro seleccionado (una vez): `Infor.`, `Marcar fila`, `Mejorar más`, Mejorar oro, Mejorar elixir.
  Tras «Mejorar más»: `Eliminar muro (-1)`, `Añadir muro (+10)`, `Añadir muro (+1)`, Mejorar oro, Mejorar elixir.
  Título «Muro (Nivel N)». Los costes salen en rojo cuando no se pueden pagar.
- Nivel máximo de muro: 19. Cuando no queda nada por mejorar el botón desaparece (pero eso no prueba que
  se esté en el máximo, ver Modo muros).
- Los muros del bloque tienen niveles mezclados (visto 16 y 17). Los de más nivel están abajo; el usuario
  empieza siempre por abajo y sube.

## Parar con depósitos llenos

- Leer la barra de oro y elixir (relleno completo = lleno). **[mi decisión]**: se para cuando **ambos**
  están llenos (el ataque exige ambos mínimos, así que un depósito lleno solo no impide farmear el otro).
- Se comprueba en la pantalla de inicio, antes de Batalla. Si están llenos: no atacar, esperar
  (comprobar cada pocos segundos) mientras el bot siga activo, o parar con aviso. **[mi decisión]**: esperar
  y avisar en el log; en modo muros / ocupados llenos significa «es hora de gastar».
- Calibración: región de cada barra en `config.regions`, con valor por defecto medido.

## Modo muros

Tras cada ataque, en la aldea:
1. Leer el contador de constructores. Si libres == 0, seguir atacando. Si depósitos llenos y libres == 0,
   esperar a que haya uno (comprobando cada pocos segundos).
2. Si libres >= 1: **rutina de muros** (abajo), luego abrir Construir (cierra la selección y reinicia la
   cámara), cerrarlo, y volver a atacar.

**Rutina de muros** (por cada recurso, oro y luego elixir):
1. Pulsar un muro del borde inferior del bloque (punto fijo, calibrable).
2. Leer el título (nivel). Si es 19 o no hay panel de muro: terminar el recurso.
3. Pulsar «Mejorar más»; pulsar «+10» repetidamente y luego «+1» mientras el coste del recurso no esté en rojo.
4. Al ponerse en rojo: «Eliminar muro» una vez; comprobar que el coste ya no está en rojo.
5. Pulsar el botón Mejorar del recurso; confirmar si el juego lo pide (nunca si pide gemas).
6. Repetir para el otro recurso (reseleccionar un muro; tras mejorar, la selección suele perderse).
7. Detenerse si ya no hay constructor libre (releer contador) o no se logra seleccionar un muro.

**[mi decisión]** Solo se guarda un reintento por paso; si falla dos veces, abortar la rutina, loguear y seguir
atacando (no parar el bot entero por esto).

## Modo constructores ocupados

Tras cada ataque, si depósitos llenos **o** hay algo libre (constructor, investigador o mascota):
1. Abrir Construir, fijar Tipo = Permanente, Orden = Coste mín., cerrar el selector.
2. Pulsar la primera entrada de la lista. Confirmar si lo pide (nunca gemas).
3. Cerrar el menú y volver a atacar.
Si la primera entrada no se puede pagar (coste en rojo) no se pulsa; se loguea y se vuelve a atacar.
**[mi decisión]**: «algo libre» se lee de los contadores del menú Construir (constructores, investigadores,
mascotas), no solo del de la aldea.

## Estructura (propuesta)

- `cocmacro/storage.py`: lectura de barras de depósitos (puro sobre un frame).
- `cocmacro/builders.py`: lectura de contadores libres/total y detección de «coste en rojo» (puro sobre frames).
- `cocmacro/upgrades.py`: rutinas de muros y de constructores, sobre el protocolo `Game`.
- `bot.py`: tras cada ataque, un gancho por modo. Sin modo activo, ni se llama.
- `config.py`: `mode` (`none`/`walls`/`busy`), `stop_when_full`, posiciones nuevas con defaults.
- `gui.py`: selector de modo y casilla; sin cambios en lo existente.
- Plantillas nuevas (botones del panel de muro, menú Construir, filtro) cortadas de capturas reales.

## Verificación

- Tests unitarios con capturas de fixtures enmascaradas para lectura de barras, contadores y «rojo».
- Bot probado con `Game` falso (cubre los ramales: libre/no libre, lleno/no lleno, fallo de selección).
- **Validación en la cuenta secundaria**: yo mismo ejecuto cada rutina con el juego real, mirando capturas
  paso a paso (primero sin gastar: hasta justo antes de «Mejorar»; luego una mejora real supervisada).

## Fuera de alcance de este documento / por calibrar en las pruebas

- Coordenadas exactas de cada botón y de las barras (se miden en el juego real).
- Qué hace el bot si el bloque de muros cambia de sitio (se asume cámara estándar tras cerrar un menú).
