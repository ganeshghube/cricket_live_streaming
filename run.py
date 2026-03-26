#!/usr/bin/env python3
"""SportsCaster Pro v2 - Dev Launcher"""
import subprocess, sys, os, threading, time

ROOT        = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT, "backend")
FRONTEND_DIR= os.path.join(ROOT, "frontend")

def _find_python():
    for c in [
        os.path.join(ROOT,"venv","Scripts","python.exe"),
        os.path.join(ROOT,"venv","Scripts","python"),
        os.path.join(ROOT,"venv","bin","python3"),
        os.path.join(ROOT,"venv","bin","python"),
    ]:
        if os.path.isfile(c): return os.path.abspath(c)
    return sys.executable

PYTHON = _find_python()

def pipe(proc, tag):
    for line in iter(proc.stdout.readline, b""):
        print(f"[{tag}] {line.decode(errors='replace').rstrip()}", flush=True)

def main():
    print("="*54)
    print("  SportsCaster Pro v2")
    print(f"  Python  : {PYTHON}")
    print("="*54)
    if not os.path.isdir(BACKEND_DIR):
        print("ERROR: Run from sportscaster2 root."); sys.exit(1)

    print("\n[1/2] Backend  → http://localhost:8000")
    be = subprocess.Popen(
        [PYTHON,"-m","uvicorn","main:app","--host","0.0.0.0","--port","8000","--reload"],
        cwd=BACKEND_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    threading.Thread(target=pipe, args=(be,"API"), daemon=True).start()
    time.sleep(2)

    print("[2/2] Frontend → http://localhost:3000")
    fe = subprocess.Popen(
        [PYTHON,"-m","http.server","3000"],
        cwd=FRONTEND_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    threading.Thread(target=pipe, args=(fe,"FE "), daemon=True).start()

    print("\n"+"="*54)
    print("  Frontend : http://localhost:3000")
    print("  API Docs : http://localhost:8000/docs")
    print("  Overlay  : http://localhost:8000/overlay/index.html")
    print("  Login    : admin / admin")
    print("  Ctrl+C   : stop all")
    print("="*54+"\n")
    try:
        while True:
            time.sleep(1)
            if be.poll() is not None:
                print("\n[ERROR] Backend crashed — see [API] lines above.")
                fe.terminate(); sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        be.terminate(); fe.terminate()
        try: be.wait(3); fe.wait(3)
        except: be.kill(); fe.kill()
        print("Done.")

if __name__ == "__main__":
    main()
