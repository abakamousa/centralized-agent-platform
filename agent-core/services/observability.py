from typing import Any

import mlflow


class ObservabilityClient:
    def __init__(self, tracking_uri: str | None) -> None:
        self.enabled = bool(tracking_uri)
        if self.enabled:
            mlflow.set_tracking_uri(tracking_uri)

    def start_trace(self, application_id: str, user_id: str) -> None:
        if not self.enabled:
            return

        mlflow.set_experiment("centralized-agent-platform")
        with mlflow.start_run(nested=True):
            mlflow.log_params(
                {
                    "application_id": application_id,
                    "user_id": user_id,
                }
            )

    def log_result(self, result: dict[str, Any]) -> None:
        if not self.enabled:
            return

        mlflow.log_dict(result, "result.json")
