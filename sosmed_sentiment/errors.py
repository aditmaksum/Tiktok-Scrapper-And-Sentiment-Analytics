class PipelineError(Exception):
    """Base error for every failure the sentiment pipeline reports to the operator."""


class InvalidInputSchemaError(PipelineError):
    """comments.json (or analysis_result.json) does not match the expected shape.

    Always fatal (exit 2) - data that doesn't match the schema can silently
    corrupt the whole analysis, so it is never skipped quietly.
    """


class LLMCallError(PipelineError):
    """A single comment's LLM escalation call failed.

    Never fatal by itself - the caller catches this per comment and marks
    the comment as failed instead of stopping the batch.
    """


class ModelLoadError(PipelineError):
    """The local sentiment model failed to load (no internet, HF down, disk, etc).

    Always fatal (exit 2) - raised once at process start, before any comment
    is processed, so a failed load means zero work is lost and a rerun once
    the underlying issue is fixed resumes cleanly.
    """


class ModelClassifyError(PipelineError):
    """A single comment's local-model classification call failed.

    Never fatal by itself - sentiment.hybrid catches this per comment and
    falls through to LLM escalation instead of stopping the batch, the same
    isolation LLMCallError already gives the LLM layer.
    """


class ReportBuildError(PipelineError):
    """The HTML report could not be assembled from a schema-valid JSON."""
