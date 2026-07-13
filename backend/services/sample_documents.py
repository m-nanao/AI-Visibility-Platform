"""Development sample documents used when a caller doesn't supply `documents`.

These are plain Japanese sentences with a `{brand}` placeholder,
thematically similar to the fixed dummy data (mock_analysis.py) so a
demo run "feels" consistent, but the co-occurrence keywords extracted
from them are genuinely computed, not fixed.
"""

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
