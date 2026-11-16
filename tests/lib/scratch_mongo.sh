#!/usr/bin/env bash
# Source me.  A SCRATCH MongoDB for tests - never the shared `rooted-mongo` (the store refuses any other host when DUSU_SCRATCH_ONLY=1).
#
#   NET="xx-test-net-$$"; MG="xx-scratch-mongo-$$"
#   docker network create --internal "$NET" >/dev/null          # no route to the internet
#   scratch_mongo_up "$NET" "$MG"                               # a one-member replica set: transactions work, like the shared one
#   URI=$(scratch_mongo_uri "$MG" mydb)                         # mongodb://<container>:27017/mydb?replicaSet=rs0
#
# The container name MUST contain "scratch". A small cache and a memory cap keep it polite on a RAM-tight host.
scratch_mongo_up() {
  local net="$1" name="$2"
  case "$name" in *scratch*) ;; *) echo "scratch mongo container names must contain 'scratch': $name" >&2; return 2 ;; esac
  docker run -d --name "$name" --network "$net" --memory 768m "${MONGO_SCRATCH_IMAGE:-mongo:7}" \
      --replSet rs0 --bind_ip_all --wiredTigerCacheSizeGB 0.25 --oplogSize 64 >/dev/null
  local i
  for i in $(seq 1 120); do docker exec "$name" mongosh --quiet --eval 'db.adminCommand("ping").ok' >/dev/null 2>&1 && break; sleep 0.5; done
  # a member host that is the container name, so the driver can reach it by that name from the same network
  docker exec "$name" mongosh --quiet --eval "rs.initiate({_id:'rs0',members:[{_id:0,host:'$name:27017'}]})" >/dev/null 2>&1
  for i in $(seq 1 120); do [ "$(docker exec "$name" mongosh --quiet --eval 'db.hello().isWritablePrimary' 2>/dev/null)" = true ] && return 0; sleep 0.5; done
  echo "scratch mongo $name did not become primary" >&2; return 1
}
scratch_mongo_uri() { echo "mongodb://$1:27017/${2:-scratch}?replicaSet=rs0"; }
scratch_pg_up() {   # optional: a scratch Postgres for the differential tests and the ETL rehearsal
  local net="$1" name="$2"
  case "$name" in *scratch*) ;; *) echo "scratch pg container names must contain 'scratch': $name" >&2; return 2 ;; esac
  docker run -d --name "$name" --network "$net" --memory 512m -e POSTGRES_USER=sc -e POSTGRES_PASSWORD=sc -e POSTGRES_DB=sc "${PG_SCRATCH_IMAGE:-postgres:18-alpine}" >/dev/null
  local i
  for i in $(seq 1 90); do docker exec "$name" pg_isready -U sc -d sc >/dev/null 2>&1 && break; sleep 1; done
  sleep 2   # the entrypoint restarts postgres once after initdb
}
