#!/usr/bin/env python3
"""
SportsCaster Pro — Launcher
Run: python run.py   (NOT bash run.py)

ONE server on port 8000. Serves everything:
  http://YOUR-IP:8000  — main app, admin pages, overlays, API
"""
import subprocess, sys, os, threading, time, shutil, socket

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


def _get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return "YOUR-IP"


def _pipe(proc, tag):
    for line in iter(proc.stdout.readline, b""):
        print(f"[{tag}] {line.decode(errors='replace').rstrip()}", flush=True)


def main():
    PY = _find_python()

    if not os.path.isdir(BACKEND_DIR):
        print("ERROR: Run from the project root (where run.py is)."); sys.exit(1)

    # Sync overlay/ → frontend/overlay/ so port 8000 can serve both paths
    overlay_src = os.path.join(ROOT, "overlay")
    overlay_dst = os.path.join(FRONTEND_DIR, "overlay")
    if os.path.isdir(overlay_src):
        if os.path.exists(overlay_dst): shutil.rmtree(overlay_dst)
        shutil.copytree(overlay_src, overlay_dst)

    print("=" * 62)
    print("  SportsCaster Pro")
    print(f"  Python: {PY}")
    print("=" * 62)
    print("  Run with:  python run.py   (NOT bash run.py)")
    print()

    # Start single server on port 8000
    print("[..] Starting server on port 8000...")
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
        cwd=BACKEND_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    threading.Thread(target=_pipe, args=(proc, "API"), daemon=True).start()
    time.sleep(3)

    ip = _get_ip()
    print()
    print("=" * 62)
    print(f"  Open in browser:  http://{ip}:8000")
    print(f"  Login:            admin / admin")
    print()
    print(f"  Admin pages:")
    print(f"    Cricket:    http://{ip}:8000/admin/cricket.html")
    print(f"    Football:   http://{ip}:8000/admin/football.html")
    print(f"    Hockey:     http://{ip}:8000/admin/hockey.html")
    print(f"    Volleyball: http://{ip}:8000/admin/volleyball.html")
    print()
    print(f"  OBS Overlay sources:")
    print(f"    Cricket:    http://{ip}:8000/overlay/cricket_overlay.html")
    print(f"    Football:   http://{ip}:8000/overlay/football_overlay.html")
    print(f"    Hockey:     http://{ip}:8000/overlay/hockey_overlay.html")
    print(f"    Volleyball: http://{ip}:8000/overlay/volleyball_overlay.html")
    print()
    print(f"  API Docs:   http://{ip}:8000/docs")
    print("=" * 62)
    print("  Press Ctrl+C to stop")
    print()

    try:
        while True:
            time.sleep(1)
            if proc.poll() is not None:
                print("\n[ERROR] Server crashed. Check [API] output above.")
                sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        proc.terminate()
        try: proc.wait(5)
        except: proc.kill()
        print("Done.")


if __name__ == "__main__":
    main()
