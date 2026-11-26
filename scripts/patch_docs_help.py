"""
Patch navigation and deep-links in docs/help.html
"""

from pathlib import Path

HELP_DOC = Path(r"D:\Sentinari\docs\help.html")

def patch_help():
    text = HELP_DOC.read_text(encoding="utf-8")

    text = text.replace('href="/ui/oncology"', 'href="./oncology.html"')
    text = text.replace('href="/ui/threats"', 'href="./threats.html"')
    text = text.replace('href="/ui/vision"', 'href="./vision.html"')
    text = text.replace('href="/ui/skills"', 'href="./skills.html"')
    text = text.replace('href="/ui/start"', 'href="./index.html"')
    text = text.replace('href="/ui/playground"', 'href="./index.html"')
    text = text.replace('href="/ui/video"', 'href="./#deliverables"')
    text = text.replace('href="/ui/ace-step"', 'href="./#deliverables"')
    text = text.replace('href="/ui/wan21"', 'href="./#deliverables"')

    HELP_DOC.write_text(text, encoding="utf-8")
    print("Successfully patched docs/help.html!")

if __name__ == "__main__":
    patch_help()
