from pydantic import BaseModel

from librarian.common.settings.base import YamlSettings
from librarian.common.settings.embeddings import EmbeddingsSettings
from librarian.common.settings.google_oauth import GoogleOAuthSettings
from librarian.common.settings.http_client import HttpClientSettings
from librarian.common.settings.model_catalog import ModelCatalog
from librarian.common.settings.ollama import OllamaSettings
from librarian.common.settings.postgres import PostgresSettings
from librarian.common.settings.user_tokens import UserTokensSettings
from librarian.service.blob_extractor.settings import BlobExtractorSettings
from librarian.service.node_extractor.settings import NodeExtractorSettings
from librarian.service.tree_builder.settings import TreeBuilderSettings


class GlobalServiceSettings(BaseModel):
    autoreload: bool = False


class Settings(YamlSettings):
    service: GlobalServiceSettings = GlobalServiceSettings()
    database: PostgresSettings = PostgresSettings()
    http_client: HttpClientSettings = HttpClientSettings()
    google_oauth: GoogleOAuthSettings = GoogleOAuthSettings()
    blob_extractor: BlobExtractorSettings = BlobExtractorSettings()
    tree_builder: TreeBuilderSettings = TreeBuilderSettings()
    node_extractor: NodeExtractorSettings = NodeExtractorSettings()
    # Shared LLM/embedder runtime knobs and the per-user-token encryption
    # key. Identical YAML on the api side; see common/settings/*.
    ollama: OllamaSettings = OllamaSettings()
    embeddings: EmbeddingsSettings = EmbeddingsSettings()
    user_tokens: UserTokensSettings = UserTokensSettings()
    # Operator-defined whitelist of allowed models per slot, plus
    # defaults. No default — required configuration; workers refuse to
    # start without it.
    model_catalog: ModelCatalog


settings = Settings()
