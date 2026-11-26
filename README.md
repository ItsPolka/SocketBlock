# SocketBlock — leonelcoin del salón

Red P2P en **Python 3.11 o posterior**, sin dependencias externas. Cada alumno ejecuta un nodo que escucha y se conecta mediante **sockets TCP/IP**. Incluye chat, descubrimiento de hasta 20 participantes, minería PoW simultánea, distribución de bloques, sincronización de cadenas y recompensas de **50 leonelcoin por bloque**.

## Arranque en el salón

Todos deben tener la misma versión del proyecto y estar en una red donde sus equipos puedan comunicarse. Puede ser una LAN, un hotspot que permita conexiones entre clientes o una VPN común. El Wi-Fi escolar puede aislar los equipos; en ese caso usen una red que permita tráfico entre alumnos. Permitan conexiones **TCP entrantes al puerto 6000** en el firewall de cada equipo.

No necesitan instalar paquetes. Abran una terminal en la carpeta del proyecto. En Windows pueden sustituir `python` por `py -3`; en Linux/macOS, por `python3`.

**1. Un alumno arranca el primer nodo.** Ejemplo: su IP de la LAN es `192.168.1.10`:

```sh
python -m socketblock --name Leonel --port 6000 --advertise 192.168.1.10
```

Obtengan la IP de la interfaz Wi-Fi/Ethernet con `ipconfig` en Windows, `ip addr` en Linux o la configuración de red en macOS. Cambien las IP de los ejemplos por las reales; `0.0.0.0` es para escuchar, no para compartir como dirección de conexión.

**2. Cada compañero arranca su nodo**, con su nombre y su propia IP. Por ejemplo, Ana está en `192.168.1.11`:

```sh
python -m socketblock --name Ana --port 6000 --advertise 192.168.1.11 --peer 192.168.1.10:6000
```

Los demás hacen lo mismo. Cada computadora puede usar el mismo puerto 6000. El primer compañero es un **punto de entrada**, no un servidor central: los nodos intercambian direcciones y se conectan directamente entre sí. Se pueden indicar varios `--peer` para tener más puntos de entrada.

**3. En cada terminal escriban:**

```text
/usuarios
```

Con el grupo completo debe mostrar **20/20 usuarios**, incluyendo el usuario local, y 19 pares. Los nombres pueden repetirse; la dirección persistente distingue a los usuarios. El límite es de 19 conexiones por nodo, pensado para una malla de 20 participantes; no es un registro global que impida incorporar equipos adicionales.

**4. Cada participante puede publicar una oferta de bloque.** Las ofertas quedan pendientes y se comparten con el salón.

```text
/ofrecer Registro de asistencia del equipo
/ofertas
```

Para minar una oferta, un compañero ejecuta `/iniciar [id]`. Si omite el ID, se elige la más antigua. Los nodos conectados compiten por confirmar esa oferta. `/minar [id]` inicia el trabajo local o permite volver a una ronda del salón tras una pausa.

**5. Al validar un ganador, los nodos detienen la ronda y muestran quién ganó.** La oferta confirmada sale de la lista pendiente. Para confirmar otra, inicien otra ronda explícitamente.

```text
/cadena todo
/ganadores
/saldo
/verificar
```

`/cadena todo` muestra la cadena principal completa desde el génesis. `/verificar` compara el hash local con el de cada par. Los anuncios periódicos se actualizan cada cinco segundos. El ganador difunde el bloque completo y los pares solicitan el historial que les falte en lotes de hasta 50 bloques.

Si dos nodos encuentran un bloque casi al mismo tiempo, puede aparecer una bifurcación temporal. Todos eligen la cadena con más trabajo acumulado y, en caso de empate, el hash menor. Si cambia la cadena principal, se recalculan los saldos y las ofertas desplazadas vuelven a estar pendientes.

## Comandos

| Comando | Acción |
| --- | --- |
| Cualquier texto sin `/` | Envía chat a todos los pares; los mensajes se retransmiten sin duplicarse |
| `/decir <texto>` | Envía chat al salón, incluso si el texto empieza con `/` |
| `/mensaje <usuario> <texto>` | Envía un mensaje directo. Usa la dirección o el nombre único entre comillas si contiene espacios |
| `/ofrecer <contenido>` | Publica una oferta de hasta 120 caracteres |
| `/ofertas` | Muestra las ofertas pendientes y sus IDs |
| `/iniciar [id]` | Inicia una ronda del salón para la oferta elegida |
| `/minar [id]` | Mina una oferta localmente o vuelve a la ronda del salón |
| `/pausar` | Pausa solo tu minero |
| `/usuarios`, `/pares` | Usuarios, direcciones, puertos, alturas y hashes anunciados |
| `/estado` | Estado local, saldo, configuración y hash completo |
| `/verificar` | Compara tu hash con los últimos anuncios de tus pares |
| `/saldo [direccion]` | Saldo actual y con seis confirmaciones |
| `/cadena [cantidad]`, `/cadena todo` | Últimos bloques o historial completo, con oferta, minero, hash padre y nonce |
| `/ganadores [cantidad]` | Ganadores de los últimos bloques |
| `/conectar IP:PUERTO` | Agrega un punto de conexión en caliente |
| `/ayuda` | Ayuda de la terminal |
| `/salir` | Cierra sockets y procesos y guarda los pares conocidos |

## Opciones y persistencia

```sh
python -m socketblock --help
```

- `--name`: nombre de 1 a 32 caracteres. Después del primer arranque es opcional.
- `--host`: interfaz de escucha, por defecto `0.0.0.0`.
- `--port`: puerto TCP, por defecto `6000`.
- `--advertise`: IP o DNS accesible desde los otros equipos. Si se omite, el otro nodo deduce la IP de la conexión.
- `--peer IP:PUERTO`: punto de entrada, repetible. IPv6: `--host :: --peer [::1]:6000`.
- `--data-dir`: carpeta de este nodo, por defecto `data/v2`. **Cada nodo debe tener una carpeta propia**, incluso si se ejecutan varios en una computadora.
- `--network`, `--difficulty`, `--reward`: parámetros de consenso que **deben coincidir en todos los nodos**. La configuración predeterminada es `leonelcoin-v2`, dificultad adaptativa y 50 monedas por bloque. Usen carpetas de datos distintas para redes con reglas diferentes.
- `--workers`: procesos PoW por nodo, por defecto uno. Cada alumno puede minar a la vez que los demás.
- `--mine`: mina al arrancar la primera oferta guardada que siga pendiente.
- `--no-input`: funciona sin consola interactiva hasta recibir Ctrl+C/SIGTERM.
- `--json`: eventos JSON por línea, útil para registrar la evidencia de la actividad.

La carpeta contiene `identity.json` con la dirección y nombre, `chain.sqlite3` con la cadena, las ramas alternativas y las ofertas, y `peers.json` con puntos de conexión para el siguiente arranque. SQLite se usa con transacciones y WAL. Un bloqueo de archivo impide que dos procesos utilicen la misma carpeta. No copien `identity.json` entre alumnos: cada uno necesita su propia identidad.

La dificultad adaptativa apunta a **120 segundos de minería en promedio**. Parte de 120 millones de intentos esperados y ajusta el objetivo SHA-256 con el trabajo esperado y el tiempo de minería de hasta las últimas 12 rondas. Al medir desde el inicio de la ronda hasta la solución, la espera para publicar una oferta o iniciar otra ronda queda fuera del cálculo. El tiempo real varía por azar, capacidad y número de mineros. Para pruebas rápidas, `--difficulty 3` fija tres ceros hexadecimales en todos los nodos y desactiva el ajuste.

La versión 2 incorpora la oferta y el inicio de ronda al hash, por lo que usa un génesis y un protocolo nuevos. Conserva la carpeta anterior para consultar el historial con la versión 1. Puedes conservar tu dirección copiando únicamente tu propio `identity.json` a la nueva carpeta antes de arrancar.

## Prueba rápida en una computadora

Abrir tres terminales en la carpeta del proyecto:

```sh
python -m socketblock --name Ana --host 127.0.0.1 --port 6001 --data-dir data/ana --difficulty 4
```

```sh
python -m socketblock --name Beto --host 127.0.0.1 --port 6002 --data-dir data/beto --difficulty 4 --peer 127.0.0.1:6001
```

```sh
python -m socketblock --name Carla --host 127.0.0.1 --port 6003 --data-dir data/carla --difficulty 4 --peer 127.0.0.1:6001
```

Escribir `/ofrecer Primera oferta` en una terminal y luego `/iniciar`. Las tres deben anunciar al ganador, detener la minería y mostrar la misma cadena con `/cadena todo`. Se puede cerrar Ana y Beto y Carla continúan conectados. Al reiniciar Ana con la misma carpeta, recupera su identidad y cadena y busca a los pares guardados.

Para una demostración automática de **20 identidades, 20 puertos TCP y 20 procesos PoW**:

```sh
python -m socketblock.demo --nodes 20 --blocks 5
```

La demostración verifica descubrimiento completo, entrega del chat, difusión de ofertas, detención tras cada ronda, igualdad de cadenas y saldos y emisión correcta de leonelcoin. Usa datos temporales y se cierra sola. Esto prueba el software localmente; la conectividad del Wi-Fi del salón se comprueba en las computadoras de los participantes.

## Pruebas automatizadas

```sh
python -m unittest discover -s tests -v
```

Las pruebas abren sockets reales en loopback. Cubren 20 nodos descubriéndose y propagando chat sin duplicados, continuidad sin el primer nodo, minería concurrente y chat directo y grupal durante el PoW, detención tras el ganador, recompensas, bifurcaciones, recuperación de padres faltantes, sincronización de más de 200 bloques, reinicios, persistencia, tramas TCP fragmentadas, datos inválidos y rechazo de redes incompatibles.

## Organización

```text
socketblock/
  models.py    Bloques canónicos, SHA-256, génesis y reglas PoW
  chain.py     Validación, selección de cadena, saldos y SQLite
  mining.py    Procesos de búsqueda de nonces
  network.py   Sockets TCP, handshake, descubrimiento y reconexión
  node.py      Chat, difusión de ganadores y sincronización de cadena
  storage.py   Identidad persistente y bloqueo de carpeta
  cli.py       Comandos y eventos de terminal
  demo.py      Verificación automática de un salón de 20 nodos
tests/         Pruebas unitarias e integración
```

El protocolo usa JSON terminado en salto de línea sobre TCP, con versión y un identificador de red derivado de los parámetros de consenso. Los tipos principales son `hello`, `peers`, `ping`, `pong`, `chat`, `direct_chat`, `offer`, `get_offers`, `offers`, `mining_start`, `block`, `head`, `get_blocks` y `blocks`. Hay límites de trama (128 KiB), colas de salida acotadas, tiempos de espera y reconexión automática. Los bloques incluyen red, altura, hash padre, oferta, inicio y fin de minería, minero, recompensa, dificultad, nonce y hash.

## Alcance

Proyecto educativo para una **red de confianza**. Las direcciones son identificadores aleatorios persistentes; los nombres y mensajes no tienen firma criptográfica y TCP transporta el chat sin cifrado. Los mensajes directos se envían únicamente por la conexión del destinatario. Cualquier participante de esta red puede solicitar el inicio de minería. Leonelcoin es una recompensa simulada contabilizada por bloque; esta versión no implementa transferencias, firmas de monedero ni dinero real. Para equipos detrás de routers distintos se necesita una VPN o configuración de puertos: no hay un servicio central de retransmisión ni perforación automática de NAT.

## Interfaz gráfica

Hay un dashboard web en vivo del minado y la cadena en [`gui/`](gui/README.md):

```sh
python3 gui/bridge.py --name Ana --advertise 192.168.1.11 --peer 192.168.1.10:6000
```

Compila el front una vez con `cd gui/web && npm install && npm run build`.
