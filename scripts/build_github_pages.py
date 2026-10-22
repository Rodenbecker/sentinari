"""Script to compile templates/portal_landing.html into a standalone docs/index.html for GitHub Pages."""

import re
from pathlib import Path

def main() -> None:
    root = Path(__file__).resolve().parent.parent
    template_path = root / "templates" / "portal_landing.html"
    raw = template_path.read_text(encoding="utf-8")

    cloud_url = "https://sentinari-core-250830594433.us-central1.run.app"

    # 1. Fill template counts
    html = (
        raw.replace("{{PATTERNS_COUNT}}", "233")
        .replace("{{DOCS_COUNT}}", "15,041")
        .replace("{{ANALYZED_COUNT}}", "1,280")
    )

    # 2. Update relative URLs to Cloud Run production service
    html = html.replace('href="/reports/the-constitution"', 'href="./Constitution.pdf" target="_blank" rel="noopener"')
    html = html.replace('href="/reports/whitepaper"', 'href="./Whitepaper.pdf"')
    html = html.replace('href="/whitepaper?download=1"', 'href="./Whitepaper.pdf" download="Sentinari_Whitepaper.pdf"')
    html = html.replace('href="/reports/the-sentinari-4-hour-adversarial-rd-challenge"', 'href="./The_Sentinari_4_Hour_adversarial_RD_challenge.pdf"')
    html = html.replace('href="/4-hour-challenge?download=1"', 'href="./The_Sentinari_4_Hour_adversarial_RD_challenge.pdf" download="The_Sentinari_4_Hour_Adversarial_RD_Challenge.pdf"')
    html = html.replace('href="/schematic?download=1"', 'href="./sentinari_functional_schematic.png" download="Sentinari_Master_Functional_Schematic.png"')
    html = html.replace('href="/schematic"', 'href="./sentinari_functional_schematic.png" target="_blank" rel="noopener"')
    html = html.replace('src="/static/sentinari_functional_schematic.png"', 'src="./sentinari_functional_schematic.png"')
    html = re.sub(r'href="/(ui/[^"]*)"', f'href="{cloud_url}/\\1" target="_blank" rel="noopener"', html)
    html = re.sub(r'href="/(api/[^"]*)"', f'href="{cloud_url}/\\1" target="_blank" rel="noopener"', html)
    html = re.sub(r'href="/(reports/[^"]*)"', f'href="{cloud_url}/\\1" target="_blank" rel="noopener"', html)
    html = re.sub(r'href="/(health[^"]*)"', f'href="{cloud_url}/\\1" target="_blank" rel="noopener"', html)
    html = re.sub(r'href="/(portal/[^"]*)"', f'href="{cloud_url}/\\1" target="_blank" rel="noopener"', html)
    html = re.sub(r'src="/(api/[^"]*)"', f'src="{cloud_url}/\\1"', html)

    # 3. Update GitHub repo link to active remote
    html = html.replace("https://github.com/PCWepener/sentinari", "https://github.com/Rodenbecker/sentinari")

    # 4. Brand link in header
    html = html.replace('href="/" class="brand"', 'href="#" class="brand"')

    # 5. Telemetry fetch and media API base from Cloud Run
    html = html.replace(
        "const API_BASE = window.API_BASE || '';",
        f"const API_BASE = '{cloud_url}';",
    )

    # 6. Add GitHub Pages Repo link in header navigation
    nav_search = '<a href="#deliverables">Core Deliverables</a>'
    nav_replace = (
        '<a href="https://github.com/Rodenbecker/sentinari" target="_blank" rel="noopener" '
        'style="color:#818cf8;font-weight:600;">&#x1F4BB; GitHub Repo</a>\n'
        '        <a href="#deliverables">Core Deliverables</a>'
    )
    html = html.replace(nav_search, nav_replace)

    out_file = root / "docs" / "index.html"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html, encoding="utf-8")
    print(f"Generated {out_file} successfully ({len(html)} bytes).")

if __name__ == "__main__":
    main()
