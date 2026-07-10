"""Pydantic models for the LLMO analysis API.

Field names are kept in camelCase to match app/lib/types.ts's
AnalysisResult exactly, so Next.js can consume the response without a
transformation layer. See docs/07_decisions.md for why.
"""

from typing import Literal

from pydantic import BaseModel

Trend = Literal["up", "down", "flat"]
Sentiment = Literal["positive", "neutral", "negative"]
Priority = Literal["high", "medium", "low"]
AnalysisSource = Literal["python_mock", "nextjs_mock", "real_analysis"]

MAX_BRAND_NAME_LENGTH = 200


class AnalysisMeta(BaseModel):
    source: AnalysisSource
    isMock: bool
    generatedAt: str


class SentimentBreakdown(BaseModel):
    positive: int
    neutral: int
    negative: int


class BrandSummary(BaseModel):
    brandName: str
    visibilityScore: int
    totalMentions: int
    sentimentBreakdown: SentimentBreakdown
    topPlatforms: list[str]
    summaryText: str


class CooccurrenceKeyword(BaseModel):
    keyword: str
    count: int
    trend: Trend


class ContextAnalysisItem(BaseModel):
    context: str
    description: str
    sentiment: Sentiment
    exampleQuote: str


class AIOverviewComparisonItem(BaseModel):
    platform: str
    mentioned: bool
    rank: int | None
    summary: str


class ImprovementSuggestion(BaseModel):
    title: str
    description: str
    priority: Priority


class AnalysisResult(BaseModel):
    brandName: str
    summary: BrandSummary
    cooccurrenceRanking: list[CooccurrenceKeyword]
    contextAnalysis: list[ContextAnalysisItem]
    aiOverviewComparison: list[AIOverviewComparisonItem]
    improvements: list[ImprovementSuggestion]
    meta: AnalysisMeta


class AnalyzeRequest(BaseModel):
    brandName: str | None = None


class ErrorResponse(BaseModel):
    error: str
