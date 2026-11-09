"""Build a hosted copy of the simulated dashboard for a claude.ai Artifact.

    python3 tools/build_artifact.py      ->  dist/artifact/{index.html, app.js, data.js, presentation/}

Differences from dashboard/index.html: no <html>/<head>/<body> (added at publish time),
Leaflet's stylesheet and app.css inlined (hosted pages load only scripts from CDNs),
the frame's height instead of 100vh, a simplified California outline instead of map
tiles, and a note that this is the hosted copy. Rebuild after changing the dashboard.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "artifact"


def main() -> None:
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "dashboard" / "app.css").read_text(encoding="utf-8")
    leaflet_css = (ROOT / "tools" / "vendor" / "leaflet-1.9.4.css").read_text(encoding="utf-8")
    css = css.replace("body { height: 100vh; overflow: hidden; }", "body { height: 100%; overflow: hidden; }")
    css = css.replace("min-height: 100vh;", "min-height: 100%;")
    body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
    body = body.replace("California fleet · demo data ·", "California fleet · demo data, hosted copy ·")
    body = body.replace('<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>',
                        '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>\n'
                        '  <script>window.HYBRID_HOSTED = true;</script>')
    page = ('<meta charset="utf-8">\n<title>hybrid-ai Field Ops</title>\n'
            f"<style>\n/* Leaflet 1.9.4 */\n{leaflet_css}\n</style>\n"
            f"<style>\n{css}\n</style>\n{body.strip()}\n")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(page, encoding="utf-8")
    for f in ("app.js", "data.js"):
        shutil.copy2(ROOT / "dashboard" / f, OUT / f)
    # the Presentation tab: page images, the PDF and the manifest, published as supporting files
    shutil.copytree(ROOT / "dashboard" / "presentation", OUT / "presentation", dirs_exist_ok=True)
    print(f"wrote {OUT}: " + ", ".join(f"{p.name} ({p.stat().st_size // 1024} KB)" for p in sorted(OUT.iterdir()) if p.is_file())
          + f", presentation/ ({len(list((OUT / 'presentation').iterdir()))} files)")


if __name__ == "__main__":
    main()
