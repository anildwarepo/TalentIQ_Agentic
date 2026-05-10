"""Azure Cosmos DB client wrapper for the MCP server."""

from azure.core.credentials import TokenCredential
from azure.cosmos import CosmosClient


class CosmosService:
    """Cosmos DB client using shared Entra ID credential (MSI / az login)."""

    def __init__(self, endpoint: str, database: str, container: str, credential: TokenCredential):
        client = CosmosClient(url=endpoint, credential=credential)
        db = client.get_database_client(database)
        self._container = db.get_container_client(container)

    def query(self, query: str, parameters: list | None = None) -> list[dict]:
        """Run a SQL query across all partitions."""
        items = self._container.query_items(
            query=query,
            parameters=parameters or [],
            enable_cross_partition_query=True,
        )
        return list(items)

    def get_by_id(self, item_id: str, partition_key: str) -> dict | None:
        """Read a single item by id and partition key."""
        try:
            return self._container.read_item(item=item_id, partition_key=partition_key)
        except Exception:
            return None
