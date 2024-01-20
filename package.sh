#!/bin/sh

set -ex
cd $(dirname $0)

zip="calibre_gpt.zip"

rm "$zip" || true
zip -r "$zip" __init__.py about.txt config.py images main.py \
    plugin-import-name-calibre_gpt.txt translations \
    ui.py engine.py secondary.py tertiary.py strings.py