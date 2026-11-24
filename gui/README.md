# SocketBlock Live — interfaz gráfica

Dashboard en vivo para tu nodo: minado en tiempo real, cadena de bloques animada, red del salón, ranking de mineros y chat.

- **Panel de minado:** número del bloque en letrero tipo aeropuerto, flujo de hashes SHA-256 de tu siguiente bloque con los ceros resaltados, mejor intento contra el objetivo de dificultad.
- **Red P2P:** mapa de compañeros conectados; cuando alguien mina, el bloque se ve viajar a los demás.
- **Cadena en vivo:** cada bloque entra animado; clic para ver hash, padre, nonce y minero.
- **Ranking, actividad y chat**, más aviso (y confeti) cuando encuentras un bloque.
- Botones **Minar / Pausar / Iniciar salón**.

Los hashes del panel se calculan en el navegador solo para visualizar el trabajo; el minero real es el de Python.
Componentes `background-paths` y `split-flap-text` de [kokonutui](https://github.com/kokonut-labs/kokonutui) (MIT).

## Cómo funciona

`bridge.py` arranca el nodo con `--json`, lee sus eventos y los manda al navegador (Server-Sent Events). Los botones envían comandos al nodo. Solo escucha en `127.0.0.1`: nadie más en la red puede controlar tu nodo. No necesita paquetes de Python.

## Uso

Requiere Node.js 18+ solo para compilar el front una vez:

```sh
cd gui/web
npm install
npm run build
cd ../..
```

Luego, desde la raíz del repo (sin otro nodo usando el puerto 6000 ni la misma `--data-dir`):

```sh
python3 gui/bridge.py --name Ana --advertise 192.168.1.11 --peer 192.168.1.10:6000
```

Abre http://127.0.0.1:8765. Todo lo que va después de `bridge.py` se pasa al nodo (`--workers 4`, `--port`, `--data-dir`, etc.); `--ui-port` cambia el puerto de la página. Ctrl+C cierra la interfaz y el nodo.

Para desarrollo con recarga en caliente: deja corriendo `bridge.py` y usa `npm run dev` dentro de `gui/web`.
