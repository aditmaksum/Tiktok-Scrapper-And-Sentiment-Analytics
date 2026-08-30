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


class ReportBuildError(PipelineError):
    """The HTML report could not be assembled from a schema-valid JSON."""
