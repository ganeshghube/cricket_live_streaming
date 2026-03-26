#!/usr/bin/env python3
"""SportsCaster Pro — Dev Launcher"""
import subprocess, sys, os, threading, time

ROOT         = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR  = os.path.join(ROOT, "backend")
FRONTEND_DIR = os.path.join(ROOT, "frontend")

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
    print("="*60)
    print("  SportsCaster Pro")
    print(f"  Python: {PYTHON}")
    print("="*60)

    if not os.path.isdir(BACKEND_DIR):
        print("ERROR: Run from project root."); sys.exit(1)

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

    print("\n" + "="*60)
    print("  MAIN UI        : http://localhost:3000")
    print("  API DOCS       : http://localhost:8000/docs")
    print()
    print("  CRICKET ADMIN  : http://localhost:3000/admin/cricket.html")
    print("  FOOTBALL ADMIN : http://localhost:3000/admin/football.html")
    print("  HOCKEY ADMIN   : http://localhost:3000/admin/hockey.html")
    print("  VOLLEYBALL ADM : http://localhost:3000/admin/volleyball.html")
    print("  CUSTOM ADMIN   : http://localhost:3000/admin/custom.html")
    print()
    print("  CRICKET OVR    : http://localhost:8000/overlay/index.html")
    print("  CRICKET OVR    : http://localhost:8000/overlay/cricket_overlay.html")
    print("  FOOTBALL OVR   : http://localhost:8000/overlay/football_overlay.html")
    print("  HOCKEY OVR     : http://localhost:8000/overlay/hockey_overlay.html")
    print("  VOLLEYBALL OVR : http://localhost:8000/overlay/volleyball_overlay.html")
    print("  CUSTOM OVR     : http://localhost:8000/overlay/custom_overlay.html")
    print()
    print("  LOGIN          : admin / admin")
    print("="*60 + "\n")

    try:
        while True:
            time.sleep(1)
            if be.poll() is not None:
                print("\n[ERROR] Backend crashed — check [API] output above.")
                fe.terminate(); sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        be.terminate(); fe.terminate()
        try: be.wait(3); fe.wait(3)
        except: be.kill(); fe.kill()
        print("Done.")

if __name__ == "__main__":
    main()
