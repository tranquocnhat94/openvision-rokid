# Rokid STT Evaluation

This folder contains the command-first STT evaluation assets for the Rokid + Jetson stack.

## Files

- `stt_command_suite.json`
  Real voice clips with expected transcript, expected command routing, and strict/non-strict labels.
- `reports/stt_command_suite_20260423.json`
  Current evaluation snapshot for the live `PhoWhisper-small + 4 threads + hotwords + binary_wav` setup.

## How to run

From `rokidjetson/backend_mvp`:

```bash
python3 scripts/evaluate_stt_command_suite.py
```

This evaluates:

- transcript exactness on isolated command clips
- required token coverage
- routed intent / mode / target query correctness
- safety on ambiguous prefixes that should not trigger a command

## Current interpretation

The current stack is suitable for:

- short Vietnamese command utterances
- domain-specific command phrases with hotwords
- intent routing where final transcript accuracy matters more than live partial captions

The current stack is not yet suitable for:

- word-by-word live caption UX
- long natural Vietnamese dictation as a polished product transcript
- evaluating command quality from one long mixed session without utterance-level segmentation

## Product guidance

- Treat the current worker as `accuracy-first final command STT`.
- Keep `localPartialEnabled = false` until a genuinely useful partial path exists.
- Grow the suite with more real clips before claiming product-grade accuracy beyond the current command set.
