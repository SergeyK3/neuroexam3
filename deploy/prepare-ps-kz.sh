#!/usr/bin/env bash
set -euo pipefail

readonly CONFIG_DIR=/etc/neuroexam3
readonly ENV_FILE=${CONFIG_DIR}/neuroexam3.env
readonly CREDENTIALS_FILE=${CONFIG_DIR}/google-service-account.json
readonly CONTAINER_UID=10001

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi

# This script deliberately does not create or change /opt/projects.
install -d -o root -g root -m 0700 "${CONFIG_DIR}"

if [[ -L ${ENV_FILE} || (-e ${ENV_FILE} && ! -f ${ENV_FILE}) ]]; then
  echo "Environment path must be a regular file, not a symlink." >&2
  exit 1
fi
if [[ ! -e ${ENV_FILE} ]]; then
  install -o root -g root -m 0600 /dev/null "${ENV_FILE}"
else
  chown root:root "${ENV_FILE}"
  chmod 0600 "${ENV_FILE}"
fi

if [[ -L ${CREDENTIALS_FILE} || (-e ${CREDENTIALS_FILE} && ! -f ${CREDENTIALS_FILE}) ]]; then
  echo "Credentials path must be a regular file, not a symlink." >&2
  exit 1
elif [[ -e ${CREDENTIALS_FILE} ]]; then
  owner_uid=$(stat -c '%u' "${CREDENTIALS_FILE}")
  mode=$(stat -c '%a' "${CREDENTIALS_FILE}")
  if [[ ${owner_uid} != ${CONTAINER_UID} || ${mode} != 400 ]]; then
    echo "Credentials must be owned by UID 10001 and have mode 0400." >&2
    exit 1
  fi
else
  echo "Credentials are absent; install them separately as UID 10001, mode 0400." >&2
fi

echo "NeuroExam 3 configuration directory is prepared. Application was not started."
