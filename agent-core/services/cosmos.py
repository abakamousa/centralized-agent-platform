import asyncio
import base64
import os
from typing import Any

from azure.cosmos import CosmosClient, exceptions
from azure.identity import DefaultAzureCredential
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)


class CosmosConfigurationError(RuntimeError):
    pass


class CosmosClientFactory:
    def __init__(self, cosmos_config: dict[str, Any] | None = None) -> None:
        config = cosmos_config or {}
        self.is_enabled = bool(config.get("enabled", False))
        self.endpoint = str(config.get("endpoint") or "").rstrip("/")
        self.database_name = str(config.get("database") or "")
        self.app_container_name = str(config.get("app_container") or "")
        self.memory_container_name = str(config.get("memory_container") or "")
        self.credential_mode = str(config.get("credential_mode") or "managed_identity")
        self.key = str(config.get("key") or os.getenv("COSMOS_KEY", ""))
        self._client: CosmosClient | None = None

    @property
    def enabled(self) -> bool:
        return self.is_enabled and bool(self.endpoint and self.database_name)

    def get_database_client(self):
        if not self.enabled:
            raise CosmosConfigurationError("Cosmos DB is not configured")

        if self._client is None:
            credential: str | DefaultAzureCredential
            if self.credential_mode == "key":
                if not self.key:
                    raise CosmosConfigurationError(
                        "Cosmos DB key credential mode requires a key"
                    )
                credential = self.key
            else:
                credential = DefaultAzureCredential()
            self._client = CosmosClient(self.endpoint, credential=credential)

        return self._client.get_database_client(self.database_name)

    def get_app_container(self):
        if not self.app_container_name:
            raise CosmosConfigurationError("Cosmos app container is not configured")
        return self.get_database_client().get_container_client(self.app_container_name)

    def get_memory_container(self):
        if not self.memory_container_name:
            raise CosmosConfigurationError("Cosmos memory container is not configured")
        return self.get_database_client().get_container_client(self.memory_container_name)


class CosmosAppConfigStore:
    def __init__(self, client_factory: CosmosClientFactory) -> None:
        self.client_factory = client_factory

    @property
    def enabled(self) -> bool:
        return self.client_factory.enabled and bool(self.client_factory.app_container_name)

    def load_application(self, application_id: str) -> dict[str, Any]:
        container = self.client_factory.get_app_container()
        try:
            item = container.read_item(item=application_id, partition_key=application_id)
        except exceptions.CosmosResourceNotFoundError as exc:
            raise FileNotFoundError(
                f"Application configuration not found in Cosmos DB: {application_id}"
            ) from exc
        return dict(item)


class CosmosCheckpointSaver(BaseCheckpointSaver[str]):
    def __init__(self, client_factory: CosmosClientFactory) -> None:
        super().__init__()
        self.client_factory = client_factory

    @property
    def enabled(self) -> bool:
        return self.client_factory.enabled and bool(self.client_factory.memory_container_name)

    def _container(self):
        return self.client_factory.get_memory_container()

    @staticmethod
    def _encode_typed(value: tuple[str, bytes]) -> dict[str, str]:
        value_type, payload = value
        return {
            "type": value_type,
            "payload": base64.b64encode(payload).decode("ascii"),
        }

    @staticmethod
    def _decode_typed(payload: dict[str, str]) -> tuple[str, bytes]:
        return (
            payload["type"],
            base64.b64decode(payload["payload"].encode("ascii")),
        )

    def _load_blobs(
        self, thread_id: str, checkpoint_ns: str, versions: ChannelVersions
    ) -> dict[str, Any]:
        container = self._container()
        channel_values: dict[str, Any] = {}

        for channel, version in versions.items():
            blob_id = f"blob:{checkpoint_ns}:{channel}:{version}"
            try:
                blob = container.read_item(item=blob_id, partition_key=thread_id)
            except exceptions.CosmosResourceNotFoundError:
                continue
            if blob.get("value_type") != "empty":
                channel_values[channel] = self.serde.loads_typed(
                    (
                        blob["value_type"],
                        base64.b64decode(blob["value_payload"].encode("ascii")),
                    )
                )
        return channel_values

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        container = self._container()
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        if checkpoint_id:
            try:
                checkpoint_doc = container.read_item(
                    item=f"checkpoint:{checkpoint_ns}:{checkpoint_id}",
                    partition_key=thread_id,
                )
            except exceptions.CosmosResourceNotFoundError:
                return None
        else:
            query = (
                "SELECT TOP 1 * FROM c "
                "WHERE c.doc_type = 'checkpoint' AND c.thread_id = @thread_id "
                "AND c.checkpoint_ns = @checkpoint_ns "
                "ORDER BY c.checkpoint_id DESC"
            )
            items = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@thread_id", "value": thread_id},
                        {"name": "@checkpoint_ns", "value": checkpoint_ns},
                    ],
                    partition_key=thread_id,
                )
            )
            if not items:
                return None
            checkpoint_doc = items[0]
            checkpoint_id = str(checkpoint_doc["checkpoint_id"])

        writes = list(
            container.query_items(
                query=(
                    "SELECT * FROM c WHERE c.doc_type = 'write' AND c.thread_id = @thread_id "
                    "AND c.checkpoint_ns = @checkpoint_ns AND c.checkpoint_id = @checkpoint_id"
                ),
                parameters=[
                    {"name": "@thread_id", "value": thread_id},
                    {"name": "@checkpoint_ns", "value": checkpoint_ns},
                    {"name": "@checkpoint_id", "value": checkpoint_id},
                ],
                partition_key=thread_id,
            )
        )

        checkpoint = self.serde.loads_typed(
            (checkpoint_doc["checkpoint_type"], base64.b64decode(checkpoint_doc["checkpoint_payload"]))
        )
        metadata = self.serde.loads_typed(
            (checkpoint_doc["metadata_type"], base64.b64decode(checkpoint_doc["metadata_payload"]))
        )

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint={
                **checkpoint,
                "channel_values": self._load_blobs(
                    thread_id, checkpoint_ns, checkpoint["channel_versions"]
                ),
            },
            metadata=metadata,
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_doc.get("parent_checkpoint_id"),
                    }
                }
                if checkpoint_doc.get("parent_checkpoint_id")
                else None
            ),
            pending_writes=[
                (
                    str(write["task_id"]),
                    str(write["channel"]),
                    self.serde.loads_typed(
                        (
                            write["value_type"],
                            base64.b64decode(write["value_payload"]),
                        )
                    ),
                )
                for write in sorted(writes, key=lambda item: item["write_idx"])
            ],
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ):
        del filter
        if not config:
            return iter(())

        container = self._container()
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        before_checkpoint_id = get_checkpoint_id(before) if before else None
        query = (
            "SELECT * FROM c WHERE c.doc_type = 'checkpoint' AND c.thread_id = @thread_id "
            "AND c.checkpoint_ns = @checkpoint_ns"
        )
        parameters = [
            {"name": "@thread_id", "value": thread_id},
            {"name": "@checkpoint_ns", "value": checkpoint_ns},
        ]
        if before_checkpoint_id:
            query += " AND c.checkpoint_id < @before_checkpoint_id"
            parameters.append(
                {"name": "@before_checkpoint_id", "value": before_checkpoint_id}
            )
        query += " ORDER BY c.checkpoint_id DESC"

        count = 0
        for item in container.query_items(
            query=query,
            parameters=parameters,
            partition_key=thread_id,
        ):
            if limit is not None and count >= limit:
                break
            checkpoint_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": item["checkpoint_id"],
                }
            }
            checkpoint_tuple = self.get_tuple(checkpoint_config)
            if checkpoint_tuple is not None:
                count += 1
                yield checkpoint_tuple

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        container = self._container()
        checkpoint_copy = checkpoint.copy()
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        values: dict[str, Any] = checkpoint_copy.pop("channel_values")

        for channel, version in new_versions.items():
            blob_value = (
                self.serde.dumps_typed(values[channel])
                if channel in values
                else ("empty", b"")
            )
            container.upsert_item(
                {
                    "id": f"blob:{checkpoint_ns}:{channel}:{version}",
                    "doc_type": "blob",
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "channel": channel,
                    "version": str(version),
                    "value_type": blob_value[0],
                    "value_payload": base64.b64encode(blob_value[1]).decode("ascii"),
                }
            )

        checkpoint_blob = self.serde.dumps_typed(checkpoint_copy)
        metadata_blob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        container.upsert_item(
            {
                "id": f"checkpoint:{checkpoint_ns}:{checkpoint['id']}",
                "doc_type": "checkpoint",
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
                "parent_checkpoint_id": config["configurable"].get("checkpoint_id"),
                "checkpoint_type": checkpoint_blob[0],
                "checkpoint_payload": base64.b64encode(checkpoint_blob[1]).decode("ascii"),
                "metadata_type": metadata_blob[0],
                "metadata_payload": base64.b64encode(metadata_blob[1]).decode("ascii"),
            }
        )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        container = self._container()
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        for idx, (channel, value) in enumerate(writes):
            write_idx = WRITES_IDX_MAP.get(channel, idx)
            encoded = self.serde.dumps_typed(value)
            container.upsert_item(
                {
                    "id": f"write:{checkpoint_ns}:{checkpoint_id}:{task_id}:{write_idx}",
                    "doc_type": "write",
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "task_id": task_id,
                    "task_path": task_path,
                    "channel": channel,
                    "write_idx": write_idx,
                    "value_type": encoded[0],
                    "value_payload": base64.b64encode(encoded[1]).decode("ascii"),
                }
            )

    def delete_thread(self, thread_id: str) -> None:
        container = self._container()
        items = list(
            container.query_items(
                query="SELECT c.id FROM c WHERE c.thread_id = @thread_id",
                parameters=[{"name": "@thread_id", "value": thread_id}],
                partition_key=thread_id,
            )
        )
        for item in items:
            container.delete_item(item=item["id"], partition_key=thread_id)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ):
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self.delete_thread, thread_id)

    def get_next_version(self, current: str | None, channel: None) -> str:
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        return f"{next_v:032}.0000000000000000"
