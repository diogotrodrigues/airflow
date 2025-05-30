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

import re
from base64 import b64decode
from subprocess import CalledProcessError

import jmespath
import pytest
from chart_utils.helm_template_generator import prepare_k8s_lookup_dict, render_chart

RELEASE_NAME_REDIS = "test-redis"

REDIS_OBJECTS = {
    "NETWORK_POLICY": ("NetworkPolicy", f"{RELEASE_NAME_REDIS}-redis-policy"),
    "SERVICE": ("Service", f"{RELEASE_NAME_REDIS}-redis"),
    "STATEFUL_SET": ("StatefulSet", f"{RELEASE_NAME_REDIS}-redis"),
    "SECRET_PASSWORD": ("Secret", f"{RELEASE_NAME_REDIS}-redis-password"),
    "SECRET_BROKER_URL": ("Secret", f"{RELEASE_NAME_REDIS}-broker-url"),
}
SET_POSSIBLE_REDIS_OBJECT_KEYS = set(REDIS_OBJECTS.values())

CELERY_EXECUTORS_PARAMS = ["CeleryExecutor", "CeleryKubernetesExecutor", "CeleryExecutor,KubernetesExecutor"]


class TestRedis:
    """Tests redis."""

    @staticmethod
    def get_broker_url_in_broker_url_secret(k8s_obj_by_key):
        broker_url_in_obj = b64decode(
            k8s_obj_by_key[REDIS_OBJECTS["SECRET_BROKER_URL"]]["data"]["connection"]
        ).decode("utf-8")
        return broker_url_in_obj

    @staticmethod
    def get_redis_password_in_password_secret(k8s_obj_by_key):
        password_in_obj = b64decode(
            k8s_obj_by_key[REDIS_OBJECTS["SECRET_PASSWORD"]]["data"]["password"]
        ).decode("utf-8")
        return password_in_obj

    @staticmethod
    def get_broker_url_secret_in_deployment(k8s_obj_by_key, kind: str, name: str) -> str:
        deployment_obj = k8s_obj_by_key[(kind, f"{RELEASE_NAME_REDIS}-{name}")]
        containers = deployment_obj["spec"]["template"]["spec"]["containers"]
        container = next(obj for obj in containers if obj["name"] == name)

        envs = container["env"]
        env = next(obj for obj in envs if obj["name"] == "AIRFLOW__CELERY__BROKER_URL")
        return env["valueFrom"]["secretKeyRef"]["name"]

    def assert_password_and_broker_url_secrets(
        self, k8s_obj_by_key, expected_password_match: str | None, expected_broker_url_match: str | None
    ):
        if expected_password_match is not None:
            redis_password_in_password_secret = self.get_redis_password_in_password_secret(k8s_obj_by_key)
            assert re.search(expected_password_match, redis_password_in_password_secret)
        else:
            assert REDIS_OBJECTS["SECRET_PASSWORD"] not in k8s_obj_by_key.keys()

        if expected_broker_url_match is not None:
            # assert redis broker url in secret
            broker_url_in_broker_url_secret = self.get_broker_url_in_broker_url_secret(k8s_obj_by_key)
            assert re.search(expected_broker_url_match, broker_url_in_broker_url_secret)
        else:
            assert REDIS_OBJECTS["SECRET_BROKER_URL"] not in k8s_obj_by_key.keys()

    def assert_broker_url_env(
        self, k8s_obj_by_key, expected_broker_url_secret_name=REDIS_OBJECTS["SECRET_BROKER_URL"][1]
    ):
        broker_url_secret_in_scheduler = self.get_broker_url_secret_in_deployment(
            k8s_obj_by_key, "StatefulSet", "worker"
        )
        assert broker_url_secret_in_scheduler == expected_broker_url_secret_name
        broker_url_secret_in_worker = self.get_broker_url_secret_in_deployment(
            k8s_obj_by_key, "Deployment", "scheduler"
        )
        assert broker_url_secret_in_worker == expected_broker_url_secret_name

    @pytest.mark.parametrize("executor", CELERY_EXECUTORS_PARAMS)
    def test_redis_by_chart_default(self, executor):
        k8s_objects = render_chart(
            RELEASE_NAME_REDIS,
            {
                "executor": executor,
                "networkPolicies": {"enabled": True},
                "redis": {"enabled": True},
            },
        )
        k8s_obj_by_key = prepare_k8s_lookup_dict(k8s_objects)

        created_redis_objects = SET_POSSIBLE_REDIS_OBJECT_KEYS & set(k8s_obj_by_key.keys())
        assert created_redis_objects == SET_POSSIBLE_REDIS_OBJECT_KEYS

        self.assert_password_and_broker_url_secrets(
            k8s_obj_by_key,
            expected_password_match=r"\w+",
            expected_broker_url_match=rf"redis://:.+@{RELEASE_NAME_REDIS}-redis:6379/0",
        )

        self.assert_broker_url_env(k8s_obj_by_key)

    @pytest.mark.parametrize("executor", CELERY_EXECUTORS_PARAMS)
    def test_redis_by_chart_password(self, executor):
        k8s_objects = render_chart(
            RELEASE_NAME_REDIS,
            {
                "executor": executor,
                "networkPolicies": {"enabled": True},
                "redis": {"enabled": True, "password": "test-redis-password!@#$%^&*()_+"},
            },
        )
        k8s_obj_by_key = prepare_k8s_lookup_dict(k8s_objects)

        created_redis_objects = SET_POSSIBLE_REDIS_OBJECT_KEYS & set(k8s_obj_by_key.keys())
        assert created_redis_objects == SET_POSSIBLE_REDIS_OBJECT_KEYS

        self.assert_password_and_broker_url_secrets(
            k8s_obj_by_key,
            expected_password_match="test-redis-password",
            expected_broker_url_match=re.escape(
                "redis://:test-redis-password%21%40%23$%25%5E&%2A%28%29_+@test-redis-redis:6379/0"
            ),
        )

        self.assert_broker_url_env(k8s_obj_by_key)

    @pytest.mark.parametrize("executor", CELERY_EXECUTORS_PARAMS)
    def test_redis_by_chart_password_secret_name_missing_broker_url_secret_name_and_broker_url_cmd(
        self, executor
    ):
        with pytest.raises(CalledProcessError):
            render_chart(
                RELEASE_NAME_REDIS,
                {
                    "executor": executor,
                    "redis": {
                        "enabled": True,
                        "passwordSecretName": "test-redis-password-secret-name",
                    },
                },
            )

    @pytest.mark.parametrize("executor", CELERY_EXECUTORS_PARAMS)
    def test_redis_by_chart_password_secret_name(self, executor):
        expected_broker_url_secret_name = "test-redis-broker-url-secret-name"
        k8s_objects = render_chart(
            RELEASE_NAME_REDIS,
            {
                "executor": executor,
                "networkPolicies": {"enabled": True},
                "data": {"brokerUrlSecretName": expected_broker_url_secret_name},
                "redis": {
                    "enabled": True,
                    "passwordSecretName": "test-redis-password-secret-name",
                },
            },
        )
        k8s_obj_by_key = prepare_k8s_lookup_dict(k8s_objects)

        created_redis_objects = SET_POSSIBLE_REDIS_OBJECT_KEYS & set(k8s_obj_by_key.keys())
        assert created_redis_objects == SET_POSSIBLE_REDIS_OBJECT_KEYS - {
            REDIS_OBJECTS["SECRET_PASSWORD"],
            REDIS_OBJECTS["SECRET_BROKER_URL"],
        }

        self.assert_password_and_broker_url_secrets(
            k8s_obj_by_key, expected_password_match=None, expected_broker_url_match=None
        )

        self.assert_broker_url_env(k8s_obj_by_key, expected_broker_url_secret_name)

    @pytest.mark.parametrize("executor", CELERY_EXECUTORS_PARAMS)
    def test_redis_by_chart_password_secret_name_without_broker_url_secret(self, executor):
        k8s_objects = render_chart(
            RELEASE_NAME_REDIS,
            {
                "executor": executor,
                "redis": {
                    "enabled": True,
                    "passwordSecretName": "test-redis-password-secret-name",
                },
                "env": [
                    {"name": "AIRFLOW__CELERY__BROKER_URL_CMD", "value": "test-broker-url"},
                ],
                "enableBuiltInSecretEnvVars": {"AIRFLOW__CELERY__BROKER_URL": False},
            },
        )
        k8s_obj_by_key = prepare_k8s_lookup_dict(k8s_objects)
        created_redis_objects = SET_POSSIBLE_REDIS_OBJECT_KEYS & set(k8s_obj_by_key.keys())

        assert created_redis_objects == SET_POSSIBLE_REDIS_OBJECT_KEYS - {
            REDIS_OBJECTS["SECRET_PASSWORD"],
            REDIS_OBJECTS["NETWORK_POLICY"],
        }

    @pytest.mark.parametrize("executor", CELERY_EXECUTORS_PARAMS)
    def test_external_redis_broker_url(self, executor):
        k8s_objects = render_chart(
            RELEASE_NAME_REDIS,
            {
                "executor": executor,
                "networkPolicies": {"enabled": True},
                "data": {
                    "brokerUrl": "redis://redis-user:password@redis-host:6379/0",
                },
                "redis": {"enabled": False},
            },
        )
        k8s_obj_by_key = prepare_k8s_lookup_dict(k8s_objects)

        created_redis_objects = SET_POSSIBLE_REDIS_OBJECT_KEYS & set(k8s_obj_by_key.keys())
        assert created_redis_objects == {REDIS_OBJECTS["SECRET_BROKER_URL"]}

        self.assert_password_and_broker_url_secrets(
            k8s_obj_by_key,
            expected_password_match=None,
            expected_broker_url_match="redis://redis-user:password@redis-host:6379/0",
        )

        self.assert_broker_url_env(k8s_obj_by_key)

    def test_should_add_annotations_to_redis_broker_url_secret(self):
        docs = render_chart(
            values={
                "executor": "CeleryExecutor",
                "networkPolicies": {"enabled": True},
                "data": {
                    "brokerUrl": "redis://redis-user:password@redis-host:6379/0",
                    "brokerUrlSecretAnnotations": {"test_annotation": "test_annotation_value"},
                },
                "redis": {"enabled": False},
            },
            show_only=["templates/secrets/redis-secrets.yaml"],
        )[0]

        assert "annotations" in jmespath.search("metadata", docs)
        assert jmespath.search("metadata.annotations", docs)["test_annotation"] == "test_annotation_value"

    @pytest.mark.parametrize("executor", CELERY_EXECUTORS_PARAMS)
    def test_external_redis_broker_url_secret_name(self, executor):
        expected_broker_url_secret_name = "redis-broker-url-secret-name"
        k8s_objects = render_chart(
            RELEASE_NAME_REDIS,
            {
                "executor": executor,
                "networkPolicies": {"enabled": True},
                "data": {"brokerUrlSecretName": expected_broker_url_secret_name},
                "redis": {"enabled": False},
            },
        )
        k8s_obj_by_key = prepare_k8s_lookup_dict(k8s_objects)

        created_redis_objects = SET_POSSIBLE_REDIS_OBJECT_KEYS & set(k8s_obj_by_key.keys())
        assert created_redis_objects == set()

        self.assert_password_and_broker_url_secrets(
            k8s_obj_by_key, expected_password_match=None, expected_broker_url_match=None
        )

        self.assert_broker_url_env(k8s_obj_by_key, expected_broker_url_secret_name)

    def test_default_redis_secrets_created_with_non_celery_executor(self):
        # We want to make sure default redis secrets (if needed) are still
        # created during install, as they are marked "pre-install".
        # See note in templates/secrets/redis-secrets.yaml for more.
        docs = render_chart(
            values={"executor": "KubernetesExecutor"}, show_only=["templates/secrets/redis-secrets.yaml"]
        )
        assert len(docs) == 2

    def test_scheduler_name(self):
        docs = render_chart(
            values={"schedulerName": "airflow-scheduler"},
            show_only=["templates/redis/redis-statefulset.yaml"],
        )

        assert (
            jmespath.search(
                "spec.template.spec.schedulerName",
                docs[0],
            )
            == "airflow-scheduler"
        )

    def test_should_create_valid_affinity_tolerations_and_node_selector(self):
        docs = render_chart(
            values={
                "executor": "CeleryExecutor",
                "redis": {
                    "affinity": {
                        "nodeAffinity": {
                            "requiredDuringSchedulingIgnoredDuringExecution": {
                                "nodeSelectorTerms": [
                                    {
                                        "matchExpressions": [
                                            {"key": "foo", "operator": "In", "values": ["true"]},
                                        ]
                                    }
                                ]
                            }
                        }
                    },
                    "tolerations": [
                        {"key": "dynamic-pods", "operator": "Equal", "value": "true", "effect": "NoSchedule"}
                    ],
                    "nodeSelector": {"diskType": "ssd"},
                },
            },
            show_only=["templates/redis/redis-statefulset.yaml"],
        )

        assert jmespath.search("kind", docs[0]) == "StatefulSet"
        assert (
            jmespath.search(
                "spec.template.spec.affinity.nodeAffinity."
                "requiredDuringSchedulingIgnoredDuringExecution."
                "nodeSelectorTerms[0]."
                "matchExpressions[0]."
                "key",
                docs[0],
            )
            == "foo"
        )
        assert (
            jmespath.search(
                "spec.template.spec.nodeSelector.diskType",
                docs[0],
            )
            == "ssd"
        )
        assert (
            jmespath.search(
                "spec.template.spec.tolerations[0].key",
                docs[0],
            )
            == "dynamic-pods"
        )

    def test_redis_resources_are_configurable(self):
        docs = render_chart(
            values={
                "redis": {
                    "resources": {
                        "limits": {"cpu": "200m", "memory": "128Mi"},
                        "requests": {"cpu": "300m", "memory": "169Mi"},
                    }
                },
            },
            show_only=["templates/redis/redis-statefulset.yaml"],
        )
        assert jmespath.search("spec.template.spec.containers[0].resources.limits.memory", docs[0]) == "128Mi"
        assert (
            jmespath.search("spec.template.spec.containers[0].resources.requests.memory", docs[0]) == "169Mi"
        )
        assert jmespath.search("spec.template.spec.containers[0].resources.requests.cpu", docs[0]) == "300m"

    def test_redis_resources_are_not_added_by_default(self):
        docs = render_chart(
            show_only=["templates/redis/redis-statefulset.yaml"],
        )
        assert jmespath.search("spec.template.spec.containers[0].resources", docs[0]) == {}

    def test_should_set_correct_helm_hooks_weight(self):
        docs = render_chart(
            values={
                "executor": "CeleryExecutor",
            },
            show_only=["templates/secrets/redis-secrets.yaml"],
        )
        annotations = jmespath.search("metadata.annotations", docs[0])
        assert annotations["helm.sh/hook-weight"] == "0"

    def test_should_add_annotations_to_redis_password_secret(self):
        docs = render_chart(
            values={
                "executor": "CeleryExecutor",
                "redis": {
                    "enabled": True,
                    "password": "password",
                    "passwordSecretAnnotations": {"test_annotation": "test_annotation_value"},
                },
            },
            show_only=["templates/secrets/redis-secrets.yaml"],
        )[0]

        assert "annotations" in jmespath.search("metadata", docs)
        assert jmespath.search("metadata.annotations", docs)["test_annotation"] == "test_annotation_value"

    def test_persistence_volume_annotations(self):
        docs = render_chart(
            values={"redis": {"persistence": {"annotations": {"foo": "bar"}}}},
            show_only=["templates/redis/redis-statefulset.yaml"],
        )
        assert jmespath.search("spec.volumeClaimTemplates[0].metadata.annotations", docs[0]) == {"foo": "bar"}

    @pytest.mark.parametrize(
        "redis_values, expected",
        [
            ({"persistence": {"enabled": False}}, {"emptyDir": {}}),
            (
                {"persistence": {"enabled": False}, "emptyDirConfig": {"sizeLimit": "10Gi"}},
                {"emptyDir": {"sizeLimit": "10Gi"}},
            ),
        ],
    )
    def test_should_use_empty_dir_on_persistence_disabled(self, redis_values, expected):
        docs = render_chart(
            values={"redis": redis_values},
            show_only=["templates/redis/redis-statefulset.yaml"],
        )
        assert {"name": "redis-db", **expected} in jmespath.search("spec.template.spec.volumes", docs[0])

    def test_priority_class_name(self):
        docs = render_chart(
            values={"redis": {"priorityClassName": "airflow-priority-class-name"}},
            show_only=["templates/redis/redis-statefulset.yaml"],
        )

        assert (
            jmespath.search(
                "spec.template.spec.priorityClassName",
                docs[0],
            )
            == "airflow-priority-class-name"
        )

    def test_redis_template_storage_class_name(self):
        docs = render_chart(
            values={"redis": {"persistence": {"storageClassName": "{{ .Release.Name }}-storage-class"}}},
            show_only=["templates/redis/redis-statefulset.yaml"],
        )
        assert (
            jmespath.search("spec.volumeClaimTemplates[0].spec.storageClassName", docs[0])
            == "release-name-storage-class"
        )

    def test_redis_template_persistence_storage_existing_claim(self):
        docs = render_chart(
            values={"redis": {"persistence": {"existingClaim": "test-existing-claim"}}},
            show_only=["templates/redis/redis-statefulset.yaml"],
        )
        assert {
            "name": "redis-db",
            "persistentVolumeClaim": {"claimName": "test-existing-claim"},
        } in jmespath.search("spec.template.spec.volumes", docs[0])

    @pytest.mark.parametrize(
        "redis_values, expected",
        [
            ({}, 600),
            ({"redis": {"terminationGracePeriodSeconds": 1200}}, 1200),
        ],
    )
    def test_redis_termination_grace_period_seconds(self, redis_values, expected):
        docs = render_chart(
            values=redis_values,
            show_only=["templates/redis/redis-statefulset.yaml"],
        )
        assert expected == jmespath.search("spec.template.spec.terminationGracePeriodSeconds", docs[0])


class TestRedisServiceAccount:
    """Tests redis service account."""

    def test_default_automount_service_account_token(self):
        docs = render_chart(
            values={
                "redis": {
                    "serviceAccount": {"create": True},
                },
            },
            show_only=["templates/redis/redis-serviceaccount.yaml"],
        )
        assert jmespath.search("automountServiceAccountToken", docs[0]) is True

    def test_overridden_automount_service_account_token(self):
        docs = render_chart(
            values={
                "redis": {
                    "serviceAccount": {"create": True, "automountServiceAccountToken": False},
                },
            },
            show_only=["templates/redis/redis-serviceaccount.yaml"],
        )
        assert jmespath.search("automountServiceAccountToken", docs[0]) is False


class TestRedisService:
    """Tests redis service."""

    @pytest.mark.parametrize(
        "redis_values, expected",
        [
            ({"redis": {"service": {"type": "ClusterIP"}}}, "ClusterIP"),
            ({"redis": {"service": {"type": "NodePort"}}}, "NodePort"),
            ({"redis": {"service": {"type": "LoadBalancer"}}}, "LoadBalancer"),
        ],
    )
    def test_redis_service_type(self, redis_values, expected):
        docs = render_chart(
            values=redis_values,
            show_only=["templates/redis/redis-service.yaml"],
        )
        assert expected == jmespath.search("spec.type", docs[0])

    def test_redis_service_nodeport(self):
        docs = render_chart(
            values={
                "redis": {
                    "service": {"type": "NodePort", "nodePort": 11111},
                },
            },
            show_only=["templates/redis/redis-service.yaml"],
        )
        assert jmespath.search("spec.ports[0].nodePort", docs[0]) == 11111

    def test_redis_service_clusterIP(self):
        docs = render_chart(
            values={
                "redis": {
                    "service": {"type": "ClusterIP", "clusterIP": "127.0.0.1"},
                },
            },
            show_only=["templates/redis/redis-service.yaml"],
        )
        assert jmespath.search("spec.clusterIP", docs[0]) == "127.0.0.1"
