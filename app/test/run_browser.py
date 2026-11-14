"""Open an app test page in headless Edge / Chrome and wait for it to finish (DevTools protocol).

  python app/test/run_browser.py [page]        (default: app/test/synth_test.html)

The page writes its result into <pre id="out">, starting with DONE or ERROR. Needs websocket-client and a
Chromium-based browser (BROWSER, else Edge or Chrome at their usual places)."""
import json, os, subprocess, sys, tempfile, time, urllib.request
import websocket

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = [os.environ.get("BROWSER", ""),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              "/usr/bin/chromium", "/usr/bin/google-chrome"]


def main():
    page = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "synth_test.html"))
    exe = next(c for c in CANDIDATES if c and os.path.exists(c))
    prof = tempfile.mkdtemp(prefix="tsp_browser_")
    port = 9333
    proc = subprocess.Popen([exe, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={prof}",
                             f"--remote-debugging-port={port}", "--autoplay-policy=no-user-gesture-required",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                tab = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.2)
        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        n = [0]

        def call(method, **params):
            n[0] += 1
            ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == n[0]:
                    return m.get("result", {})

        call("Page.navigate", url="file:///" + page.replace("\\", "/"))
        t0 = time.time()
        while time.time() - t0 < 60:
            r = call("Runtime.evaluate", expression="(document.getElementById('out')||{}).textContent||''")
            text = r.get("result", {}).get("value", "")
            if text.startswith("DONE") or text.startswith("ERROR"):
                print(text)
                return 0 if text.startswith("DONE") else 1
            time.sleep(0.3)
        print("timeout:", text)
        return 1
    finally:
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
