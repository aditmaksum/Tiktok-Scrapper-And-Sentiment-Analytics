from typing import Optional

import yaml

CONFIG_KEY: str = 'ambiguous_confidence_threshold'


def load_threshold_config(
    path: Optional[str]
) -> float:
    """ambiguous_confidence_threshold, calibrated against the Tahap B labeled sample.

    Unlike Rules.md §6's usual "load config with a built-in default" pattern,
    this one has NO fallback number in code. docs/designs/sentiment-model-cascade.md
    (Reviewer Concerns) explicitly rejects a placeholder threshold - two earlier
    written assumptions in this project (a Sastrawi per-token cache, an
    LLM-is-expensive cost estimate) turned out wrong once actually measured, so a
    guessed number here risks the same failure mode, silently, forever, if nobody
    re-calibrates it. Run scripts/calibrate_threshold.py against a labeled sample
    and pass its output explicitly.
    """
    if not path:
        raise ValueError(
            'ambiguous_confidence_threshold belum dikalibrasi. Jalankan '
            'scripts/calibrate_threshold.py terhadap sampel Tahap B, lalu tunjuk '
            '--threshold-config ke hasilnya (mis. config/thresholds.yaml). Tidak ada '
            'angka default ditulis di kode - lihat docs/designs/sentiment-model-cascade.md, '
            'bagian Reviewer Concerns.'
        )

    with open(path, encoding='utf-8') as handle:
        data = yaml.safe_load(handle) or {}

    if CONFIG_KEY not in data:
        raise ValueError('%s: key %r tidak ditemukan' % (path, CONFIG_KEY))

    return float(data[CONFIG_KEY])
