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

**4. Un compañero escribe:**

```text
/iniciar
```

El aviso se propaga por TCP y todos los nodos conectados comienzan a minar. Un nodo que se incorpore durante esa sesión recibe la cadena y el aviso de inicio. También se puede usar `/minar` o `--mine` para iniciar únicamente la minería local.

**5. Observen los ganadores y comparen la cadena:**

```text
/estado
/ganadores
/saldo
/verificar
```

Cada bloque muestra su altura, el nombre del ganador, el hash completo y la recompensa. Para tomar una captura con un hash inmóvil, escriban `/pausar` **en cada nodo**, esperen unos segundos y ejecuten `/verificar`. Todos deben mostrar la misma altura y el mismo hash; los anuncios de estado se actualizan cada cinco segundos. `/pausar` no desconecta el nodo ni detiene la recepción de bloques. `/iniciar` vuelve a arrancar la minería del salón.

## Cómo se cumplen los objetivos de la actividad

| Objetivo | Implementación y evidencia |
| --- | --- |
| Conectar a todo el salón por P2P | TCP bidireccional, descubrimiento automático y `/usuarios` con 20 identidades |
| Ver a los otros nodos mientras se mina | La red corre con `asyncio`; la búsqueda de nonces ocurre en procesos separados |
| Detener a los demás al encontrar un hash | Al validar el bloque ganador se reemplaza el trabajo anterior; cada minero revisa trabajos nuevos cada lote de 2048 intentos y se descartan resultados atrasados |
| Distribuir la nueva cadena | El ganador propaga el bloque con su hash y el hash padre; los pares solicitan cualquier segmento faltante en lotes de hasta 100 bloques |
| Terminar con la misma cadena | Todos verifican PoW y reglas de consenso, resuelven bifurcaciones con la misma regla y convergen al mismo historial y saldo |

La detención es **del trabajo del bloque anterior**: después de incorporar el ganador, todos continúan automáticamente con el siguiente bloque. Así se conserva el requisito de minería continua. No se transmite todo el historial con cada bloque; se distribuye la extensión y, cuando hace falta, se sincroniza el historial completo por partes.

Dos computadoras pueden encontrar bloques válidos antes de recibir el aviso de la otra. En una red distribuida eso produce una bifurcación temporal. Se elige la cadena con más trabajo acumulado; con esta dificultad fija equivale a mayor altura. En empate se elige el **hash lexicográficamente menor**. Las ramas alternativas se guardan, y una rama más larga puede reemplazar a la actual. Las recompensas se recalculan usando solo la cadena principal, por lo que un premio reciente es provisional. `/saldo` muestra también el saldo con seis confirmaciones.

## Comandos

| Comando | Acción |
| --- | --- |
| Cualquier texto sin `/` | Envía chat a todos los pares; los mensajes se retransmiten sin duplicarse |
| `/iniciar` | Inicia o reanuda la minería en todo el salón |
| `/minar` | Inicia o reanuda solo tu minero |
| `/pausar` | Pausa solo tu minero |
| `/usuarios`, `/pares` | Usuarios, direcciones, puertos, alturas y hashes anunciados |
| `/estado` | Estado local, saldo, configuración y hash completo |
| `/verificar` | Compara tu hash con los últimos anuncios de tus pares |
| `/saldo [direccion]` | Saldo actual y con seis confirmaciones |
| `/cadena [cantidad]` | Últimos bloques, incluyendo hash padre y nonce |
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
- `--data-dir`: carpeta de este nodo, por defecto `data/default`. **Cada nodo debe tener una carpeta propia**, incluso si se ejecutan varios en una computadora.
- `--network`, `--difficulty`, `--reward`: parámetros de consenso que **deben coincidir en todos los nodos**. Por defecto: `leonelcoin-v1`, seis ceros hexadecimales y 50 monedas. Si cambian, usen una carpeta de datos nueva.
- `--workers`: procesos PoW por nodo, por defecto uno. Cada alumno puede minar a la vez que los demás.
- `--mine`: arranca minando localmente.
- `--no-input`: funciona sin consola interactiva hasta recibir Ctrl+C/SIGTERM.
- `--json`: eventos JSON por línea, útil para registrar la evidencia de la actividad.

La carpeta contiene `identity.json` con la dirección y nombre, `chain.sqlite3` con la cadena y las ramas alternativas, y `peers.json` con puntos de conexión para el siguiente arranque. SQLite se usa con transacciones y WAL. Un bloqueo de archivo impide que dos procesos utilicen la misma carpeta. No copien `identity.json` entre alumnos: cada uno necesita su propia identidad.

La dificultad representa ceros **hexadecimales** al inicio de SHA-256. Cada cero multiplica por 16 el número esperado de intentos. Para una prueba rápida pueden usar `--difficulty 3`; para el salón se propone `6`, de modo que las rondas no sean demasiado breves con 20 computadoras minando. El tiempo depende del hardware y del número de mineros, y los bloques no tienen un intervalo fijo. Esta versión no cambia la dificultad automáticamente.

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

Escribir `/iniciar` en cualquiera de ellas. Las tres deben anunciar ganadores y avanzar a la siguiente ronda. Se puede cerrar Ana y Beto y Carla continúan conectados. Al reiniciar Ana con la misma carpeta, recupera su identidad y cadena y busca a los pares guardados.

Para una demostración automática de **20 identidades, 20 puertos TCP y 20 procesos PoW**:

```sh
python -m socketblock.demo --nodes 20 --blocks 5
```

La demostración verifica descubrimiento completo, entrega del chat, inicio simultáneo de mineros, continuidad, igualdad de cadenas y saldos y emisión correcta de leonelcoin. Usa datos temporales y se cierra sola. Esto prueba el software localmente; la conectividad del Wi-Fi del salón se comprueba en las computadoras de los participantes.

## Pruebas automatizadas

```sh
python -m unittest discover -s tests -v
```

Las pruebas abren sockets reales en loopback. Cubren 20 nodos descubriéndose y propagando chat sin duplicados, continuidad sin el primer nodo, minería concurrente y chat durante el PoW, ganadores, recompensas, bifurcaciones, recuperación de padres faltantes, sincronización de más de 200 bloques, reinicios, persistencia, tramas TCP fragmentadas, datos inválidos y rechazo de redes incompatibles.

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

El protocolo usa JSON terminado en salto de línea sobre TCP, con versión y un identificador de red derivado de los parámetros de consenso. Los tipos principales son `hello`, `peers`, `ping`, `pong`, `chat`, `mining_start`, `block`, `head`, `get_blocks` y `blocks`. Hay límites de trama (128 KiB), colas de salida acotadas, tiempos de espera y reconexión automática. Los bloques incluyen red, altura, hash padre, fecha, minero, recompensa, dificultad, nonce y hash.

## Alcance

Proyecto educativo para una **red de confianza**. Las direcciones son identificadores aleatorios persistentes; los nombres y mensajes no tienen firma criptográfica y el chat no está cifrado. Cualquier participante de esta red puede solicitar el inicio de minería. Leonelcoin es una recompensa simulada contabilizada por bloque; esta versión no implementa transferencias, firmas de monedero ni dinero real. Para equipos detrás de routers distintos se necesita una VPN o configuración de puertos: no hay un servicio central de retransmisión ni perforación automática de NAT.

## Interfaz gráfica

Hay un dashboard web en vivo del minado y la cadena en [`gui/`](gui/README.md):

```sh
python3 gui/bridge.py --name Ana --advertise 192.168.1.11 --peer 192.168.1.10:6000
```

Compila el front una vez con `cd gui/web && npm install && npm run build`.
