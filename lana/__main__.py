import argparse

from . import web


def main():
    ap = argparse.ArgumentParser(prog="lana", description="Installer et administrer des serveurs de jeu.")
    ap.add_argument("--lan", action="store_true", help="écouter sur le réseau local (par défaut : cette machine seulement)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    web.serve("0.0.0.0" if args.lan else "127.0.0.1", args.port)


if __name__ == "__main__":
    main()
