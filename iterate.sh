#!/bin/sh

fswatch -o test.py engine.py | \
    xargs -n1 -I{} bash -c '
        clear
        sh test.sh
    '