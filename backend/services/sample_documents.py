"""Development sample documents used when a caller doesn't supply `documents`.

These are plain Japanese sentences with a `{brand}` placeholder,
thematically similar to the fixed dummy data (mock_analysis.py) so a
demo run "feels" consistent, but the co-occurrence keywords extracted
from them are genuinely computed, not fixed.

This module owns the "Provider" stage of the Document Pipeline (see
docs/11_architecture_v1.md "4. Document Pipeline") for the
`development_sample` source — the same role services/web_fetcher.py
plays for `web_fetch` and main.py's _documents_from_strings() plays
for `user_provided`.
"""

from datetime import datetime, timezone

from models import Document
from services.document_normalizer import normalize_text

SAMPLE_DOCUMENT_TEMPLATES = [
    "{brand}は料金プランが分かりやすく、導入事例も豊富だと評判です。",
    "競合他社と比較しても、{brand}のサポート体制は充実していると口コミで評価されています。",
    "{brand}のAPI連携は非常にスムーズで、開発者からの評判も良いです。",
    "導入事例を見ると、{brand}を使うことで業務効率が大きく改善したという声が多いです。",
    "料金プランについては、{brand}は他社より分かりやすいという口コミが目立ちます。",
    "サポート体制の面でも、{brand}は迅速な対応で評判を得ています。",
]


def build_sample_documents(brand_name: str) -> list[str]:
    return [template.format(brand=brand_name) for template in SAMPLE_DOCUMENT_TEMPLATES]


def build_sample_documents_as_documents(brand_name: str) -> list[Document]:
    """Wraps the development sample templates as Document[] (see
    docs/11_architecture_v1.md "4. Document Pipeline"), the Provider
    role for the development_sample source. Each text is run through
    the Normalizer stage (normalize_text()) just like user_provided
    and web_fetch text, so all three sources reach the Analyzer
    through the same Document[]-based path.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    return [
        Document(
            id=f"development-sample-{index + 1}",
            sourceType="development_sample",
            title="開発用サンプル",
            fetchedAt=fetched_at,
            text=normalize_text(text),
            metadata={"purpose": "development_sample"},
        )
        for index, text in enumerate(build_sample_documents(brand_name))
    ]
