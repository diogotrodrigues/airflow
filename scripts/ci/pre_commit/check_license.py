#!/usr/bin/env python
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import annotations

import os
import subprocess
import sys

from common_precommit_utils import AIRFLOW_ROOT_PATH

# This is the target of a symlink in airflow/www/static/docs -
# and rat exclude doesn't cope with the symlink target doesn't exist
os.makedirs(AIRFLOW_ROOT_PATH / "docs" / "_build" / "html", exist_ok=True)

cmd = [
    "docker",
    "run",
    "-v",
    f"{AIRFLOW_ROOT_PATH}:/opt/airflow",
    "-t",
    "--user",
    f"{os.getuid()}:{os.getgid()}",
    "--rm",
    "--platform",
    "linux/amd64",
    "ghcr.io/apache/airflow-apache-rat:0.16.1-2024.03.23@sha256:83c4d2610ec4a439d1809a67fadbdc9a1df089ab130b32209351bdd4527a3f02",
    "-d",
    "/opt/airflow",
    "--exclude-file",
    "/opt/airflow/.rat-excludes",
]

print("Running command:")
print(" ".join(cmd))
print()
result = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    check=False,
)
output = result.stdout
if result.returncode != 0:
    print(f"\033[0;31mERROR: {result.returncode} when running rat\033[0m\n")
    print(output)
    sys.exit(result.returncode)
unknown_licences = [line for line in output.splitlines() if "??" in line]
if unknown_licences:
    print("\033[0;31mERROR: Could not find Apache licences in some files:\033[0m\n")
    for line in unknown_licences:
        print(line)
    print()
    sys.exit(1)
