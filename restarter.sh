#!/bin/sh
# Restarts az-monitor containers. POSIX sh: runs in the docker:cli (busybox) image.
#  - every pass: restart managed containers whose healthcheck says "unhealthy"
#  - once per calendar day, at or after RESTART_AT: restart all managed containers
# Test hooks: DOCKER, RUN_ONCE=1, NOW_HM, NOW_DAY (see test_restarter.py).

DOCKER="${DOCKER:-docker}"
RESTART_AT="${RESTART_AT:-05:00}"
RESTARTER_STATE="${RESTARTER_STATE:-/tmp/restarter.last}"
LABEL="label=az-monitor.managed=true"

first_pass=1

restart_ids() {
    for id in $1; do
        echo "restarting $id ($2)"
        "$DOCKER" restart "$id"
    done
}

while true; do
    hm="${NOW_HM:-$(date +%H:%M)}"
    day="${NOW_DAY:-$(date +%F)}"

    restart_ids "$("$DOCKER" ps -q --filter "$LABEL" --filter health=unhealthy)" unhealthy

    # test(1) has no portable string ordering; compare HH:MM strings with expr.
    # Both are zero-padded, so string order is time order.
    at_or_after=0
    after=0
    if [ "$(expr "$hm" \>= "$RESTART_AT")" = 1 ]; then at_or_after=1; fi
    if [ "$(expr "$hm" \> "$RESTART_AT")" = 1 ]; then after=1; fi

    last=""
    [ -f "$RESTARTER_STATE" ] && last="$(cat "$RESTARTER_STATE")"

    if [ "$at_or_after" = 1 ] && [ "$last" != "$day" ]; then
        if [ "$first_pass" = 1 ] && [ -z "$last" ] && [ "$after" = 1 ]; then
            # Restarter was (re)created after today's restart time: do not
            # bounce every monitor, just mark today as done.
            echo "startup after $RESTART_AT: marking $day done without restarting"
        else
            restart_ids "$("$DOCKER" ps -q --filter "$LABEL")" daily
        fi
        echo "$day" > "$RESTARTER_STATE"
    fi

    first_pass=0
    [ "$RUN_ONCE" = 1 ] && exit 0
    sleep 60
done
