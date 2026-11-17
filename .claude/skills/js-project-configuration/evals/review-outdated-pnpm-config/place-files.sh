#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
# Copia los archivos de entrada del caso al directorio de la corrida.
set -eu
cp -R "$(dirname "$0")/files/." .
