#!/usr/bin/env bash
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

# Install airflow using regular 'pip install' command. This install airflow depending on the arguments:
#
# AIRFLOW_INSTALLATION_METHOD - determines where to install airflow form:
#             "." - installs airflow from local sources
#             "apache-airflow" - installs airflow from PyPI 'apache-airflow' package
#             "apache-airflow @ URL - installs from URL
#
# (example GitHub URL https://github.com/apache/airflow/archive/main.tar.gz)
#
# AIRFLOW_VERSION_SPECIFICATION - optional specification for Airflow version to install (
#                                 might be ==2.0.2 for example or <3.0.0
# UPGRADE_INVALIDATION_STRING - if set with random value determines whether eager-upgrade should be done
#                               for the dependencies (with EAGER_UPGRADE_ADDITIONAL_REQUIREMENTS added)
#
# shellcheck shell=bash disable=SC2086
# shellcheck source=scripts/docker/common.sh
. "$( dirname "${BASH_SOURCE[0]}" )/common.sh"

function install_airflow() {
    # Remove mysql from extras if client is not going to be installed
    if [[ ${INSTALL_MYSQL_CLIENT} != "true" ]]; then
        AIRFLOW_EXTRAS=${AIRFLOW_EXTRAS/mysql,}
        echo "${COLOR_YELLOW}MYSQL client installation is disabled. Extra 'mysql' installations were therefore omitted.${COLOR_RESET}"
    fi
    # Remove postgres from extras if client is not going to be installed
    if [[ ${INSTALL_POSTGRES_CLIENT} != "true" ]]; then
        AIRFLOW_EXTRAS=${AIRFLOW_EXTRAS/postgres,}
        echo "${COLOR_YELLOW}Postgres client installation is disabled. Extra 'postgres' installations were therefore omitted.${COLOR_RESET}"
    fi
    # Determine the installation_command_flags based on AIRFLOW_INSTALLATION_METHOD method
    local installation_command_flags
    if [[ ${AIRFLOW_INSTALLATION_METHOD} == "." ]]; then
        # We do not yet use ``uv sync`` because we are not committing and using uv.lock yet and uv sync
        # cannot use constraints - once we switch to uv.lock (with the workflow that dependabot will update it
        # and constraints will be generated from it, we should be able to simply use ``uv sync`` here
        installation_command_flags=" --editable .[${AIRFLOW_EXTRAS}] --editable ./airflow-core --editable ./task-sdk --editable ./airflow-ctl --editable ./devel-common"
        while IFS= read -r -d '' pyproject_toml_file; do
            project_folder=$(dirname ${pyproject_toml_file})
            installation_command_flags="${installation_command_flags} --editable ${project_folder}"
        done < <(find "providers" -name "pyproject.toml" -print0)
    elif [[ ${AIRFLOW_INSTALLATION_METHOD} == "apache-airflow" ]]; then
        installation_command_flags="apache-airflow[${AIRFLOW_EXTRAS}]${AIRFLOW_VERSION_SPECIFICATION}"
    elif [[ ${AIRFLOW_INSTALLATION_METHOD} == apache-airflow\ @\ * ]]; then
        installation_command_flags="apache-airflow[${AIRFLOW_EXTRAS}] @ ${AIRFLOW_VERSION_SPECIFICATION/apache-airflow @//}"
    else
        echo
        echo "${COLOR_RED}The '${INSTALLATION_METHOD}' installation method is not supported${COLOR_RESET}"
        echo
        echo "${COLOR_YELLOW}Supported methods are ('.', 'apache-airflow', 'apache-airflow @ URL')${COLOR_RESET}"
        echo
        exit 1
    fi
    if [[ "${UPGRADE_INVALIDATION_STRING=}" != "" ]]; then
        echo
        echo "${COLOR_BLUE}Remove airflow and all provider distributions installed before potentially${COLOR_RESET}"
        echo
        set -x
        ${PACKAGING_TOOL_CMD} freeze | grep apache-airflow | xargs ${PACKAGING_TOOL_CMD} uninstall ${EXTRA_UNINSTALL_FLAGS} 2>/dev/null || true
        set +x
        echo
        echo "${COLOR_BLUE}Installing all packages in eager upgrade mode. Installation method: ${AIRFLOW_INSTALLATION_METHOD}${COLOR_RESET}"
        echo
        set -x
        ${PACKAGING_TOOL_CMD} install ${EXTRA_INSTALL_FLAGS} ${UPGRADE_EAGERLY} ${ADDITIONAL_PIP_INSTALL_FLAGS} ${installation_command_flags} ${EAGER_UPGRADE_ADDITIONAL_REQUIREMENTS=}
        set +x
        common::install_packaging_tools
        echo
        echo "${COLOR_BLUE}Running 'pip check'${COLOR_RESET}"
        echo
        pip check
    else
        echo
        echo "${COLOR_BLUE}Installing all packages with constraints. Installation method: ${AIRFLOW_INSTALLATION_METHOD}${COLOR_RESET}"
        echo
        set -x
        # TODO(potiuk) - when we switch to storing uv.lock in the repo, we might use `uv sync` here - but that requires changing our upgrade dependency workflow and strategy
        if ! ${PACKAGING_TOOL_CMD} install ${EXTRA_INSTALL_FLAGS} ${ADDITIONAL_PIP_INSTALL_FLAGS} ${installation_command_flags} --constraint "${HOME}/constraints.txt"; then
            set +x
            echo
            echo "${COLOR_YELLOW}Likely pyproject.toml has new dependencies conflicting with constraints.${COLOR_RESET}"
            echo
            echo "${COLOR_BLUE}Falling back to no-constraints installation.${COLOR_RESET}"
            echo
            set -x
            ${PACKAGING_TOOL_CMD} install ${EXTRA_INSTALL_FLAGS} ${UPGRADE_IF_NEEDED} ${ADDITIONAL_PIP_INSTALL_FLAGS} ${installation_command_flags}
        fi
        set +x
        common::install_packaging_tools
        echo
        echo "${COLOR_BLUE}Running 'pip check'${COLOR_RESET}"
        echo
        pip check
    fi

}

common::get_colors
common::get_packaging_tool
common::get_airflow_version_specification
common::get_constraints_location
common::show_packaging_tool_version_and_location

install_airflow
